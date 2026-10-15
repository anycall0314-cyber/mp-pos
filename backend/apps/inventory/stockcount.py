"""盤點:開單 → 盤(配件輸入數量、手機逐台刷)→ 送出 → 管理員核准(這時才動庫存)。

owner 2026-10-12 定的三條:
1. **盤出來的差異要管理員調整與核准** —— 盤的人只記「數到幾個、刷到哪幾台」,庫存一個數字都不動;
   送出之後管理員看差異表,每一列可以改調整量、或先不調、寫原因,按核准才動。
2. **帶序號的逐台刷** —— 手機不能輸入「幾台」,要一台一台刷碼。
3. **盤點中可以繼續開單** —— 不鎖庫存。配件每一列記的是「輸入那一刻」的帳上數量:差異 = 數到的 − 當時帳上的,
   之後賣掉 / 進貨的是正常的異動。核准時是「現在的帳上數量 加減 差異」,不是把帳上數量改成當時數到的數字。
   手機的差異在送出時算:帳上在這家門市在庫、但沒刷到 = 少的(盤點開始之後才進到這家門市的不算;已經賣掉 / 調走的本來就不在庫)。

其他(動手前紅隊前兩次逾時,第三次用精簡的題目有回,三條都採用):
- 沒有輸入的配件 = 沒盤,不當成 0。**手機要送出的人表明「全部刷完了」才算少了哪幾台**(紅隊第 1 條:只刷了櫃台、
  保險櫃沒刷就送出,不能整櫃都變成盤虧);沒有表明 = 沒刷到的是「沒盤」,不是「少了」。
- 刷到的那一刻就記下那一台在帳上的樣子(紅隊第 2 條):早上刷到、下午正常賣掉的不算「多的」。
  列成「少的」那幾台送出之後還是可以賣(不鎖);核准的當下已經不在庫的就不標盤虧 —— 賣得掉代表它在。
- 配件是先數、後輸入(紅隊第 3 條):數完到輸入之間賣掉的,差異會少算。不擋,但每一列附「開盤之後到輸入那一刻,
  這個商品出了幾個、進了幾個」,盤的人看到有數字就知道要重數;管理員的差異表也看得到。**帳上總數仍然不給盤的人看。**
- 刷到、但帳上不是這家門市在庫的(已售、在別家、系統不認得)= 多出來的:**只列出來,不自動處理**。
  系統不會因為刷到就把一台「已售」的變回在庫 —— 那是哪張單該作廢、哪張調撥沒收貨,要人去查。
- 少的手機核准之後標成「盤虧」(不算在庫、不能賣、還佔著碼);之後找到了管理員按「找回」。
- 庫存的每一次增減都記一筆「盤點調整」異動(增加寫目的門市、減少寫來源門市 —— 每日對帳的「庫存 = 異動加總」靠這個)。
- 鎖的順序照 `locking.py`:先鎖盤點單自己,再鎖序號、庫存餘額(跟銷貨同一個順序;核准時不另外「先鎖商品」)。
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import Category, Product
from apps.identity.normalize import normalize_serial
from apps.tenants.models import Tenant

from .identifiers import IdentifierError, create_serial, find_serial_ids
from .locking import lock_document, lock_stock_rows, locked_balance
from .models import (
    ProductSerial,
    StockBalance,
    StockCount,
    StockCountCategory,
    StockCountLine,
    StockCountMissing,
    StockCountScan,
    StockCountUnknown,
    StockMovement,
)

S = StockCount.Status
OPEN = (S.COUNTING, S.SUBMITTED)
# 刷到時算「帳上就在這家門市」的狀態:在庫、已退(退回來還放在店裡)
ON_SHELF = (ProductSerial.Status.IN_STOCK, ProductSerial.Status.RETURNED)
REF = "stock_count"
REF_FOUND = "stock_count_found"
MAX_QTY = 1_000_000
MAX_AMOUNT = Decimal("1e12")


class CountError(Exception):
    """做不了(狀態不對、商品不對、不夠扣…)。訊息直接給畫面。"""


def scope_ids(count) -> set:
    """這張盤點單只盤哪幾個類別(空的 = 全部)。"""
    return set(count.scope.values_list("category_id", flat=True))


def _locked(count, *allowed):
    """鎖住盤點單那一列再看狀態(兩個人同時按送出 / 核准只會成一次)。"""
    if lock_document(count) is None:
        raise CountError("找不到這張盤點單")
    if count.status not in allowed:
        raise CountError(f"這張盤點單現在是「{count.get_status_display()}」,不能這樣做")
    return count


def _by(user):
    return user if getattr(user, "is_authenticated", False) else None


def open_count(tenant, warehouse, category_ids, user, note=""):
    """開一張盤點單。同一家門市同時只能有一張還沒結束的。"""
    if warehouse.tenant_id != tenant.pk:
        raise CountError("門市不屬於這家公司")
    ids = sorted({int(i) for i in category_ids or []})
    try:
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=tenant.pk)          # 配單號、看有沒有進行中的:一次一個
            going = StockCount.objects.filter(tenant=tenant, warehouse=warehouse, status__in=OPEN).first()
            if going:
                raise CountError(f"這家門市已經有一張還沒結束的盤點單 {going.no}")
            categories = list(Category.objects.filter(tenant=tenant, pk__in=ids))
            if len(categories) != len(ids):
                raise CountError("類別不屬於這家公司")
            seq = StockCount.objects.filter(tenant=tenant).count() + 1
            while StockCount.objects.filter(tenant=tenant, no=f"SC-{seq:06d}").exists():
                seq += 1
            count = StockCount.objects.create(
                tenant=tenant, warehouse=warehouse, no=f"SC-{seq:06d}", note=(note or "")[:200], created_by=_by(user))
            StockCountCategory.objects.bulk_create([
                StockCountCategory(tenant=tenant, count=count, category=category) for category in categories])
            return count
    except IntegrityError:
        raise CountError("這家門市已經有一張還沒結束的盤點單") from None


def _countable(count, product):
    """這個商品可不可以輸入數量(配件、零件:不帶序號、不是虛擬的,而且在這張單的類別裡)。"""
    if product.tenant_id != count.tenant_id:
        raise CountError("商品不屬於這家公司")
    if product.requires_serial:
        raise CountError(f"「{product.name}」是帶序號的,要一台一台刷")
    if product.is_virtual:
        raise CountError(f"「{product.name}」沒有庫存,不用盤")
    scope = scope_ids(count)
    if scope and product.category_id not in scope:
        raise CountError(f"「{product.name}」不在這張盤點單的類別裡")


NOT_SEEN = object()


def set_line(count, product, counted_qty, user, seen=NOT_SEEN):
    """配件:這個商品現場數到幾個(重新輸入 = 整個換掉,帳上數量也重新記)。
    `seen` = 畫面輸入前看到的數字(None = 那時還沒有這一列):**跟現在的不一樣就不換**(手機走動盤點的紅隊:
    手機一直往上加,電腦按下去會把手機剛加的默默蓋掉)。沒帶 = 不核對(舊的呼叫)。"""
    if not isinstance(counted_qty, int) or isinstance(counted_qty, bool) or not 0 <= counted_qty <= MAX_QTY:
        raise CountError("數量要是 0 以上的整數")
    with transaction.atomic():
        _locked(count, S.COUNTING)
        _countable(count, product)
        # create=True:這家門市還沒有這個商品的餘額列時先建一列 0 再鎖(複審 P0)。只「查查看有沒有」的話,
        # 同一瞬間有人正在存第一張進貨(那一列還沒存完、看不到)會被當成帳上 0,核准時就多加一次
        balance = locked_balance(count.tenant, product, count.warehouse, create=True)
        if seen is not NOT_SEEN:
            now = StockCountLine.objects.filter(count=count, product=product).values_list("counted_qty", flat=True).first()
            if now != seen:
                raise CountError(f"「{product.name}」剛剛有人改過,現在是 {now or 0} 個,再確認一次")
        now = timezone.now()
        line, _ = StockCountLine.objects.update_or_create(
            count=count, product=product,
            defaults={
                "tenant": count.tenant, "counted_qty": counted_qty, "book_qty": balance.qty,
                "counted_at": now, "counted_by": _by(user), "replaced_at": now,
            })
        return line


def add_to_line(count, product, delta, user):
    """配件加減幾個(手機走動盤點:每刷一個 +1,「這一堆幾個」、收回)。回 (那一列, 改之前, 改之後);改之前 None = 原本沒有這一列。
    好幾支手機同時加同一個商品:鎖住那個商品在這家門市的餘額列(`locked_balance`)排隊,不會少算。帳上數量照 `set_line` 重新記。"""
    if not isinstance(delta, int) or isinstance(delta, bool) or not -MAX_QTY <= delta <= MAX_QTY or delta == 0:
        raise CountError("數量要是整數")
    with transaction.atomic():
        _locked(count, S.COUNTING)
        _countable(count, product)
        balance = locked_balance(count.tenant, product, count.warehouse, create=True)
        line = StockCountLine.objects.select_for_update().filter(count=count, product=product).first()
        before = line.counted_qty if line else None
        after = (before or 0) + delta
        if not 0 <= after <= MAX_QTY:
            raise CountError(f"「{product.name}」不能少於 0 個")
        if line is None:
            line = StockCountLine.objects.create(
                tenant=count.tenant, count=count, product=product, counted_qty=after, book_qty=balance.qty,
                counted_at=timezone.now(), counted_by=_by(user))
        else:
            line.counted_qty, line.book_qty, line.counted_at, line.counted_by = after, balance.qty, timezone.now(), _by(user)
            line.save(update_fields=["counted_qty", "book_qty", "counted_at", "counted_by", "updated_at"])
        return line, before, after


def take_back_line(count, product, delta, since, user, line_ref=None):
    """手機收回 / 改「這一堆幾個」之前:那個配件可以減掉 `delta` 嗎。`since` = 手機那一下的時間:
    **那之後電腦整格換過(`replaced_at`)就不動** —— 換掉的數字已經定了,再減會錯;只有別的手機也在加不擋(加減不會互相蓋掉)。
    回 (那一列, 減完是幾個, 餘額列);呼叫的人要已經在交易裡。"""
    _locked(count, S.COUNTING)
    _countable(count, product)
    balance = locked_balance(count.tenant, product, count.warehouse, create=True)
    line = StockCountLine.objects.select_for_update().filter(count=count, product=product).first()
    # 那一列被移除、重建過(編號不一樣了)也不動(複審 P0:舊的那一下會扣到別人重新盤的數)
    if line is None or (line_ref is not None and line.pk != line_ref) or (line.replaced_at and line.replaced_at >= since):
        raise CountError(f"「{product.name}」電腦之後改過數字,請到電腦上改")
    after = line.counted_qty - delta
    if not 0 <= after <= MAX_QTY:
        raise CountError(f"「{product.name}」不能少於 0 個")
    return line, after, balance


def put_back_line(count, product, delta, since, user, line_ref=None):
    """「收回這一下」:那個配件減 `delta`(見 `take_back_line`)。減到 0、而且電腦從來沒有整格打過數字(全是手機加減的)
    → 整列拿掉(回到「沒盤」,不是「數到 0 個」);電腦打過的 0 是「數到 0 個」,留著。回減完是幾個(None = 整列拿掉了)。"""
    with transaction.atomic():
        line, after, balance = take_back_line(count, product, delta, since, user, line_ref)
        if after == 0 and line.replaced_at is None:
            line.delete()
            return None
        line.counted_qty, line.book_qty, line.counted_at, line.counted_by = after, balance.qty, timezone.now(), _by(user)
        line.save(update_fields=["counted_qty", "book_qty", "counted_at", "counted_by", "updated_at"])
        return after


def remove_line(count, line_id):
    with transaction.atomic():
        _locked(count, S.COUNTING)
        if not StockCountLine.objects.filter(count=count, pk=line_id).delete()[0]:
            raise CountError("這一列不在這張盤點單上")


def _first_intake(count, code):
    """系統不認得的碼:對舊系統的機器清單(第一次盤點入庫;`legacy/units.py`)。回 (要記的碼, 那一台) 或 (碼, None)。

    刷到型號用的舊貼紙、或是配件的條碼 → 直接講要怎麼刷(紅隊:店員會習慣性刷舊貼紙)。"""
    from apps.legacy import units
    from apps.legacy.products import _barcode_owner

    try:
        hit = units.lookup(count.tenant, code)
    except units.ModelSticker as exc:
        raise CountError(f"這是「{exc}」型號的貼紙,請刷這一台的 IMEI") from None
    if hit is not None:
        return hit.code, hit.unit
    owner = _barcode_owner(count.tenant, code)
    if owner is not None:
        p = Product.objects.filter(pk=owner).values_list("name", "requires_serial").first()
        if p and not p[1]:
            raise CountError(f"「{p[0]}」是配件,請在配件那一格打數量")
    return code, None


def scan(count, code, user):
    """手機:刷一個碼。記下刷的那一刻那一台在帳上是什麼樣子(之後賣掉的不算多、也不算少)。
    系統不認得的碼另外對舊系統的機器清單,照抄那一台的舊品號、舊品名、成本、售價(核准時給管理員看)。"""
    code = str(code or "").strip()
    key = normalize_serial(code)
    if not key or len(code) > 80:
        raise CountError("這不是有效的碼")
    with transaction.atomic():
        _locked(count, S.COUNTING)
        ids = find_serial_ids(count.tenant, code)
        unit = None
        if not ids:
            code, unit = _first_intake(count, code)
            key = normalize_serial(code)
            ids = find_serial_ids(count.tenant, code)
        if StockCountScan.objects.filter(count=count, code_key=key).exists():
            raise CountError("這個碼刷過了")
        if len(ids) > 1:
            raise CountError("這個碼對到不只一台,請改刷那一台的另一個碼")
        serial = ProductSerial.objects.select_related("product").get(pk=ids[0]) if ids else None
        if serial is not None:
            if StockCountScan.objects.filter(count=count, serial=serial).exists():
                raise CountError("這一台刷過了")            # IMEI 刷過、又刷同一台的 SN
            scope = scope_ids(count)
            if scope and serial.product.category_id not in scope:
                raise CountError(f"「{serial.product.name}」不在這張盤點單的類別裡")
        here = bool(serial and serial.warehouse_id == count.warehouse_id and serial.status in ON_SHELF)
        old = unit if serial is None else None
        return StockCountScan.objects.create(
            tenant=count.tenant, count=count, code=code, code_key=key, serial=serial, here=here,
            state=serial.status if serial else "", scanned_at=timezone.now(), scanned_by=_by(user),
            old_code=old.product_code_raw if old else "", old_name=old.product_name_raw if old else "",
            old_cost=old.cost if old else None, old_price=old.price if old else None)


def remove_scan(count, scan_id):
    with transaction.atomic():
        _locked(count, S.COUNTING)
        if not StockCountScan.objects.filter(count=count, pk=scan_id).delete()[0]:
            raise CountError("這個碼不在這張盤點單上")


def expected_serials(count):
    """帳上現在在這家門市在庫、在這張單範圍裡的手機 —— 但盤點開始之後才進到這家門市的不算
    (進貨、調撥收貨、銷退、作廢銷貨放回來的:盤的人可能已經刷完那一區了,下次再盤)。"""
    T = StockMovement.MovementType
    serials = ProductSerial.objects.filter(
        tenant=count.tenant, warehouse=count.warehouse, status=ProductSerial.Status.IN_STOCK)
    scope = scope_ids(count)
    if scope:
        serials = serials.filter(product__category_id__in=scope)
    arrived = StockMovement.objects.filter(
        tenant=count.tenant, serial__isnull=False, to_warehouse=count.warehouse, created_at__gte=count.created_at,
    ).exclude(movement_type=T.TRANSFER_OUT)               # 調撥派發那一筆的「目的」只是路線,貨還沒到
    return serials.exclude(pk__in=arrived.values("serial_id"))


def unknown_key(code: str) -> str:
    return normalize_serial(code)


def tally_unknown(count, code, label):
    """手機在「配件」模式刷到系統不認得的碼:記一次(同一個碼刷幾次記幾次)。回 (那一筆, 改之前, 改之後)。"""
    code = str(code or "").strip()
    key = unknown_key(code)
    if not key or len(code) > 80:
        raise CountError("這不是有效的碼")
    with transaction.atomic():
        _locked(count, S.COUNTING)
        row = StockCountUnknown.objects.select_for_update().filter(count=count, code_key=key).first()
        if row is None:
            row = StockCountUnknown.objects.create(tenant=count.tenant, count=count, code=code, code_key=key, times=0)
        if row.resolved_at:
            raise CountError(f"{code} 已經在電腦上處理過了")
        before = row.times
        row.times, row.last_label = before + 1, label[:20]
        row.save(update_fields=["times", "last_label", "updated_at"])
        return row, before, row.times


def untally_unknown(count, unknown_id):
    """收回手機的那一下(沒對到的碼):還沒處理的才減一(別支手機也在刷不擋);減到 0 整筆拿掉。"""
    with transaction.atomic():
        _locked(count, S.COUNTING)
        row = StockCountUnknown.objects.select_for_update().filter(count=count, pk=unknown_id).first()
        if row is None or row.resolved_at:
            raise CountError("這個碼已經在電腦上處理過了,請到電腦上看")
        if row.times <= 1:
            row.delete()
            return
        row.times -= 1
        row.save(update_fields=["times", "updated_at"])


def resolve_unknown(count, unknown_id, user, product=None, reason=""):
    """電腦處理一個沒對到的碼:指定成某個配件(刷了幾次就加幾個,`add_to_line`),或「不入」(要寫原因)。"""
    with transaction.atomic():
        _locked(count, S.COUNTING)
        row = StockCountUnknown.objects.select_for_update().filter(count=count, pk=unknown_id).first()
        if row is None:
            raise CountError("這個碼不在這張盤點單上")
        if row.resolved_at:
            raise CountError(f"{row.code} 已經處理過了")
        if product is not None:
            if product.tenant_id != count.tenant_id:
                raise CountError("商品不屬於這家公司")
            add_to_line(count, product, row.times, user)
            row.product = product
        else:
            reason = str(reason or "").strip()[:100]
            if not reason:
                raise CountError("不入要寫原因")
            row.skipped, row.reason = True, reason
        row.resolved_at, row.resolved_by = timezone.now(), _by(user)
        row.save(update_fields=["product", "skipped", "reason", "resolved_at", "resolved_by", "updated_at"])
        return row


def submit(count, user, phones_done=False):
    """盤完送出。phones_done = 送出的人表明「這個範圍的手機全部刷完了」:這時才算手機少了哪幾台。
    沒有表明的話,沒刷到的手機是「沒盤」(不進差異、不會變成盤虧)。
    手機刷到、還沒處理的「沒對到的碼」要先處理好(指定配件或不入)才能送出(紅隊:對不上的不能跟著單子消失)。"""
    with transaction.atomic():
        _locked(count, S.COUNTING)
        left = count.unknowns.filter(resolved_at__isnull=True).count()
        if left:
            raise CountError(f"還有 {left} 個沒對到的碼,先指定配件或寫原因不入,才能送出")
        scanned = set(count.scans.exclude(serial=None).values_list("serial_id", flat=True))
        if not count.scans.exists() and not count.lines.exists() and not phones_done:
            raise CountError("還沒有盤任何東西")
        count.phones_done = bool(phones_done)
        if count.phones_done:
            StockCountMissing.objects.bulk_create([
                StockCountMissing(tenant=count.tenant, count=count, serial_id=pk)
                for pk in expected_serials(count).exclude(pk__in=scanned).order_by("pk").values_list("pk", flat=True)
            ])
        count.status, count.submitted_at, count.submitted_by = S.SUBMITTED, timezone.now(), _by(user)
        count.save(update_fields=["status", "phones_done", "submitted_at", "submitted_by", "updated_at"])
        _end_phones(count)
        return count


def give_back(count):
    """退回重盤(管理員):回到盤點中,送出時算的那份手機差異丟掉(再送出時重算)。"""
    with transaction.atomic():
        _locked(count, S.SUBMITTED)
        count.missing.all().delete()
        count.status, count.submitted_at, count.submitted_by, count.phones_done = S.COUNTING, None, None, False
        count.save(update_fields=["status", "phones_done", "submitted_at", "submitted_by", "updated_at"])
        return count


def void(count, by_manager=False):
    """作廢(還沒核准的才可以;核准之後庫存已經動了,要再盤一次或再調一次)。
    還在盤的,盤的人自己可以作廢;**已經送出的只有管理員**(by_manager)。

    誰可以作廢要在**鎖到這張單之後**才看(複審 P0):先看狀態、後上鎖的話,一個人按送出、另一個人同時按作廢,
    作廢那邊看到的還是「盤點中」,等到鎖的時候單已經送出了,店員就把待核准的單作廢掉了。
    """
    with transaction.atomic():
        _locked(count, S.COUNTING, *([S.SUBMITTED] if by_manager else []))
        count.status = S.VOID
        count.save(update_fields=["status", "updated_at"])
        _end_phones(count)
        return count


def _end_phones(count):
    """送出 / 作廢:發出去的手機一律結束(複審 P1:退回重盤之後舊的 QR Code 不能自己活過來,要重新產生)。"""
    count.phones.filter(ended_at__isnull=True).update(ended_at=timezone.now())


def _decision(decisions, pk):
    d = decisions.get(pk) or decisions.get(str(pk)) or {}
    if not isinstance(d, dict):
        raise CountError("送來的內容格式不對")
    return d


def _amount(value, what, required=True):
    """管理員填的成本 / 售價:0 以上、到分。空的:要的話擋下,不要的話是 None。"""
    text = str(value if value is not None else "").replace(",", "").strip()
    if not text:
        if required:
            raise CountError(f"{what}要填(沒有就填 0)")
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise CountError(f"{what}要是數字") from None
    if not amount.is_finite() or amount < 0 or amount >= MAX_AMOUNT:
        raise CountError(f"{what}要是 0 以上的數字")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _new_units(count, extras):
    """系統不認得、要入庫的那幾台:[(刷碼那一列, 品號編號, 成本, 售價)]。沒有送的 = 不入(沒講就不入,不猜)。"""
    plans = []
    for row in count.scans.filter(serial__isnull=True).order_by("id"):
        d = _decision(extras, row.pk)
        row.reason = str(d.get("reason") or "")[:100]
        pid = d.get("product")
        row.skipped = bool(d.get("skipped", False)) or pid in (None, "")
        if row.skipped:
            row.product = row.unit_cost = row.unit_price = None
            row.save(update_fields=["skipped", "reason", "product", "unit_cost", "unit_price"])
            continue
        if not isinstance(pid, int) or isinstance(pid, bool):
            raise CountError(f"{row.code}:品號不對")
        plans.append((row, pid, _amount(d.get("unit_cost"), f"{row.code} 的成本"),
                      _amount(d.get("unit_price"), f"{row.code} 的售價", required=False)))
    return plans


def approve(count, user, lines=None, missing=None, extras=None):
    """核准(管理員):照差異動庫存。lines / missing = {編號: {"adjust_qty": 整數, "skipped": 是否, "reason": 字}}
    沒有送的列 = 照「數到的 − 當時帳上的」調;手機沒有送的 = 標成盤虧。
    extras = 系統不認得的碼 {刷碼編號: {"product": 品號編號, "unit_cost": 成本, "unit_price": 售價, "skipped", "reason"}}:
    有給品號的入庫成那個品號的一台(第一次盤點入庫,記成盤點調整);**沒有送的不入**。

    這一步才動庫存,而且整張在一個交易裡:任何一列不夠扣就整張不動、講是哪一個商品。
    """
    lines, missing, extras = lines or {}, missing or {}, extras or {}
    M = StockMovement.MovementType
    with transaction.atomic():
        _locked(count, S.SUBMITTED)
        tenant, wh = count.tenant, count.warehouse
        rows = list(count.lines.select_related("product").order_by("id"))
        gone = list(count.missing.select_related("serial__product").order_by("id"))
        plans = _new_units(count, extras)
        for row in rows:
            d = _decision(lines, row.pk)
            row.skipped = bool(d.get("skipped", False))
            row.reason = str(d.get("reason") or "")[:100]
            adjust = d.get("adjust_qty", row.counted_qty - row.book_qty)
            if not isinstance(adjust, int) or isinstance(adjust, bool) or abs(adjust) > MAX_QTY:
                raise CountError(f"「{row.product.name}」的調整量要是整數")
            row.adjust_qty = 0 if row.skipped else adjust
        for m in gone:
            d = _decision(missing, m.pk)
            m.skipped = bool(d.get("skipped", False))
            m.reason = str(d.get("reason") or "")[:100]
        todo = [row for row in rows if row.adjust_qty]
        # 鎖的順序跟銷貨一樣:**序號 → 庫存餘額**。讀餘額的那個查詢照品號排序、會帶到商品那一列,
        # 所以鎖到餘額的同時商品那一列也鎖住了(銷貨也是這樣)。
        # **配件的商品不可以改成「先鎖商品」**(複審第二輪 P1):那樣這裡是 商品 → 序號,銷貨是 序號 → 餘額連帶商品,
        # 一張銷貨單同時有那一台手機與那個配件、又剛好同時核准時,兩邊會互相等到死結。
        # 第一次入庫的手機要重算它的平均成本,所以**那幾個(帶序號的)品號**照 locking.py 先鎖(跟進貨一樣:商品 → 序號);
        # 銷貨不鎖帶序號的商品那一列,不會反過來等。
        targets = {p.pk: p for p in Product.objects.filter(tenant=tenant, pk__in=[pid for _, pid, _, _ in plans])}
        if len(targets) != len({pid for _, pid, _, _ in plans}):
            raise CountError("品號不屬於這家公司")
        lock_stock_rows(
            tenant, products=[p for p in targets.values() if p.requires_serial],
            serial_ids=[m.serial_id for m in gone if not m.skipped],
            balances=[(row.product, wh) for row in todo], create=True)
        # 送出之後商品被改成「帶序號」或「虛擬」(複審 P0):那種商品不能有數量庫存,這一列不能調 —— 管理員把它勾成先不調。
        # 在餘額(連帶商品)鎖住之後才讀;這裡再明確鎖一次商品(已經握著,不會等),讀到的就是鎖住的那一刻的樣子
        kinds = {
            pk: (serial, virtual) for pk, serial, virtual in Product.objects.select_for_update(no_key=True).filter(
                tenant=tenant, pk__in=[row.product_id for row in todo],
            ).order_by("pk").values_list("pk", "requires_serial", "is_virtual")}
        for row in todo:
            serial_now, virtual_now = kinds[row.product_id]
            if serial_now or virtual_now:
                raise CountError(
                    f"「{row.product.name}」現在是{'帶序號的' if serial_now else '沒有庫存的'}商品,不能調數量;請把這一列勾成先不調")
        for row in todo:
            balance = StockBalance.objects.get(tenant=tenant, product=row.product, warehouse=wh)
            after = balance.qty + row.adjust_qty
            if after < 0:
                raise CountError(
                    f"「{row.product.name}」帳上現在只有 {balance.qty} 個,不夠扣 {-row.adjust_qty} 個;請改這一列的調整量或先不調")
            if balance.qty == 0 and not balance.weighted_avg_cost:
                # 這家門市從來沒有過這個商品:成本先用公司的平均(不然盤盈進來的是 0 元的貨)
                balance.weighted_avg_cost = row.product.weighted_avg_cost or 0
            balance.qty = after
            balance.save(update_fields=["qty", "weighted_avg_cost"])
            row.unit_cost = balance.weighted_avg_cost
            more = row.adjust_qty > 0
            StockMovement.objects.create(
                tenant=tenant, product=row.product, qty=abs(row.adjust_qty), movement_type=M.ADJUST,
                to_warehouse=wh if more else None, from_warehouse=None if more else wh,
                ref_doc_type=REF, ref_doc_id=count.id,
                note=f"盤點單 {count.no} {'盤盈' if more else '盤虧'} {row.product.sku} ×{abs(row.adjust_qty)}"[:200])
        StockCountLine.objects.bulk_update(rows, ["skipped", "reason", "adjust_qty", "unit_cost"])
        for m in gone:
            if m.skipped:
                continue
            serial = ProductSerial.objects.get(pk=m.serial_id)           # 鎖到之後重讀
            # 核准的當下已經不在這家門市在庫的(盤完才賣掉、調走)不動:它不是不見了
            if serial.status == ProductSerial.Status.IN_STOCK and serial.warehouse_id == wh.pk:
                serial.status = ProductSerial.Status.LOST
                serial.save(update_fields=["status"])
                StockMovement.objects.create(
                    tenant=tenant, serial=serial, qty=1, movement_type=M.ADJUST, from_warehouse=wh,
                    ref_doc_type=REF, ref_doc_id=count.id, note=f"盤點單 {count.no} 盤虧"[:200])
                m.applied = True
        StockCountMissing.objects.bulk_update(gone, ["skipped", "reason", "applied"])
        _blend_average(tenant, plans, targets)      # 先算(在庫的台數是入庫之前的),跟進貨一樣
        _add_units(count, plans, targets, user)
        count.status, count.approved_at, count.approved_by = S.APPROVED, timezone.now(), _by(user)
        count.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
        return count


def _blend_average(tenant, plans, targets):
    """入庫之前先算那幾個品號的平均成本,**跟進貨同一個算法**(`purchasing.commit_purchase_order`):
    (全公司現在在庫的台數 × 現在的平均成本 + 這一次的成本合計)÷(台數 + 這一次的台數)。
    不可以用「現在在庫那幾台的成本平均」重算(複審 P0):中間賣掉過的話,兩種算法的數字不一樣,
    同一個品號從進貨入、從盤點入會得到不同的平均成本。品號已經鎖住、平均成本是鎖到之後重讀的。"""
    from apps.purchasing.services import CENTS

    batches: dict[int, list] = {}
    for _, pid, cost, _ in plans:
        batches.setdefault(pid, []).append(cost)
    for pid in sorted(batches):
        product = targets[pid]
        product.refresh_from_db(fields=["weighted_avg_cost"])
        here = ProductSerial.objects.filter(tenant=tenant, product=product, status=ProductSerial.Status.IN_STOCK).count()
        costs = batches[pid]
        product.weighted_avg_cost = (
            (Decimal(here) * product.weighted_avg_cost + sum(costs, Decimal("0"))) / Decimal(here + len(costs))
        ).quantize(CENTS)
        product.save(update_fields=["weighted_avg_cost"])


def _add_units(count, plans, targets, user):
    """第一次盤點入庫:每一台建成那個品號在這家門市在庫的一台(成本 = 管理員核准的),記一筆盤點調整。
    品號已經在 `approve` 裡鎖住(商品 → 序號);平均成本照進貨的算法(`_blend_average`)。"""
    from apps.legacy import units

    tenant, wh = count.tenant, count.warehouse
    scope = scope_ids(count)
    now = timezone.now()
    for row, pid, cost, price in plans:
        product = targets[pid]
        product.refresh_from_db(fields=["requires_serial", "is_virtual", "is_active", "is_secondhand", "condition"])
        if not product.requires_serial or product.is_virtual:
            raise CountError(f"{row.code}:「{product.name}」不是一台一個碼的商品")
        if not product.is_active:
            raise CountError(f"{row.code}:「{product.name}」已停用")
        if scope and product.category_id not in scope:
            raise CountError(f"{row.code}:「{product.name}」不在這張盤點單的類別裡")
        # 舊系統是中古機的只能指定中古機的品號、新機只能指定不是中古機的(紅隊:店員習慣點全新的品號,中古就混進全新)
        used = units.is_used_name(row.old_name)
        if used is not None and used != product.is_secondhand:
            if used:
                raise CountError(f"{row.code}:舊系統是中古機,「{product.name}」不是中古機的品號")
            raise CountError(f"{row.code}:舊系統是新機,「{product.name}」是中古機的品號")
        extra = {}
        if product.tracks_unit_condition:
            if price:
                extra["custom_unit_price"] = price
            battery = units.battery_of(row.old_name)
            if battery is not None:
                extra["battery_health"] = battery
            if row.old_name:
                extra["condition_note"] = f"舊系統:{row.old_name}"[:200]
        try:
            serial = create_serial(
                tenant=tenant, product=product, code=row.code, warehouse=wh, status=ProductSerial.Status.IN_STOCK,
                purchase_unit_cost=cost, received_at=now, **extra)
        except IdentifierError as exc:
            raise CountError(f"{row.code}:{exc}") from None
        StockMovement.objects.create(
            tenant=tenant, serial=serial, qty=1, movement_type=StockMovement.MovementType.ADJUST, to_warehouse=wh,
            ref_doc_type=REF, ref_doc_id=count.id, note=f"盤點單 {count.no} 第一次入庫"[:200])
        row.product, row.unit_cost, row.unit_price, row.added = product, cost, price, serial
        row.save(update_fields=["skipped", "reason", "product", "unit_cost", "unit_price", "added"])
        if row.old_code:
            _remember(tenant, row.old_code, row.old_name, product, user)


def _remember(tenant, old_code, old_name, product, user):
    """舊品號 → 這一次指定的品號,記在舊品號對照(下一次刷到同一個舊品號的機器就先帶出來)。已經對照到別的不動。"""
    from apps.legacy.archive import SOURCE_SYSTEM
    from apps.legacy.mapping import confirm_map
    from apps.legacy.models import LegacyMappingLog, LegacyProductMap, MapMethod, MapStatus

    row, _ = LegacyProductMap.objects.get_or_create(
        tenant=tenant, source_system=SOURCE_SYSTEM, product_code_raw=old_code[:60],
        defaults={"product_name_seen": old_name[:500]})
    if row.status != MapStatus.CONFIRMED:
        confirm_map(LegacyMappingLog.Kind.PRODUCT, row, product, user, method=MapMethod.MANUAL, note="盤點入庫")


def suggested_products(tenant, old_codes) -> dict:
    """舊品號 → 已經對照好的品號(核准畫面先帶出來,管理員確認)。"""
    from apps.legacy.archive import SOURCE_SYSTEM
    from apps.legacy.models import LegacyProductMap, MapStatus

    rows = LegacyProductMap.objects.filter(
        tenant=tenant, source_system=SOURCE_SYSTEM, status=MapStatus.CONFIRMED,
        product_code_raw__in=[c for c in old_codes if c], product__requires_serial=True, product__is_active=True,
    ).select_related("product")
    return {r.product_code_raw: r.product for r in rows}


def found(count, missing_id, user):
    """核准之後手機找到了(管理員):那一台回到在庫、記一筆異動。"""
    with transaction.atomic():
        _locked(count, S.APPROVED)
        m = count.missing.filter(pk=missing_id).first()
        if m is None:
            raise CountError("這一台不在這張盤點單上")
        if not m.applied or m.found_at:
            raise CountError("這一台沒有標成盤虧,不用找回")
        lock_stock_rows(count.tenant, serial_ids=[m.serial_id])
        serial = ProductSerial.objects.get(pk=m.serial_id)
        if serial.status != ProductSerial.Status.LOST:
            raise CountError("這一台現在不是盤虧")
        serial.status = ProductSerial.Status.IN_STOCK
        serial.save(update_fields=["status"])
        StockMovement.objects.create(
            tenant=count.tenant, serial=serial, qty=1, movement_type=StockMovement.MovementType.ADJUST,
            to_warehouse=serial.warehouse, ref_doc_type=REF_FOUND, ref_doc_id=count.id,
            note=f"盤點單 {count.no} 盤虧的找回來了"[:200])
        m.found_at, m.found_by = timezone.now(), _by(user)
        m.save(update_fields=["found_at", "found_by", "updated_at"])
        return m


def left_to_count(count) -> int:
    """帳上有數量、在這張單範圍裡、還沒輸入的配件有幾樣(只給數字;盤的人看不到帳上是幾個)。"""
    stocked = StockBalance.objects.filter(
        tenant=count.tenant, warehouse=count.warehouse, qty__gt=0,
        product__requires_serial=False, product__is_virtual=False)
    scope = scope_ids(count)
    if scope:
        stocked = stocked.filter(product__category_id__in=scope)
    return stocked.exclude(product_id__in=count.lines.values("product_id")).count()


def moved_since_start(count, lines):
    """每一列:開盤之後到輸入那一刻,這個商品在這家門市出了幾個、進了幾個 → {明細編號: (出, 進)}。

    盤的人常常先數、後輸入;中間賣掉的,輸入時記到的帳上數量已經扣掉了,差異會少算。這裡不擋,
    只把「這一樣開盤之後有動過」講出來(不是帳上總數),盤的人知道要重數、管理員知道這一列要小心。
    """
    from .flows import deltas

    by_product = {line.product_id: line for line in lines}
    out = {line.pk: [0, 0] for line in lines}
    if not by_product:
        return {}
    wh = count.warehouse_id
    moves = StockMovement.objects.filter(
        tenant=count.tenant, serial__isnull=True, product_id__in=list(by_product), created_at__gte=count.created_at,
    ).exclude(ref_doc_type=REF, ref_doc_id=count.id).values_list(       # 這張單自己核准時記的那幾筆不算
        "product_id", "movement_type", "from_warehouse_id", "to_warehouse_id", "qty", "created_at")
    for product_id, kind, w_from, w_to, qty, at in moves:
        line = by_product[product_id]
        if at > line.counted_at:
            continue
        for warehouse_id, delta in deltas(kind, w_from, w_to, qty):
            if warehouse_id == wh:
                out[line.pk][0 if delta < 0 else 1] += abs(delta)
    return {pk: tuple(v) for pk, v in out.items()}

