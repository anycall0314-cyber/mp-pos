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
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import Category, Product
from apps.identity.normalize import normalize_serial
from apps.tenants.models import Tenant

from .identifiers import find_serial_ids
from .locking import lock_document, lock_stock_rows, locked_balance
from .models import (
    ProductSerial,
    StockBalance,
    StockCount,
    StockCountCategory,
    StockCountLine,
    StockCountMissing,
    StockCountScan,
    StockMovement,
)

S = StockCount.Status
OPEN = (S.COUNTING, S.SUBMITTED)
# 刷到時算「帳上就在這家門市」的狀態:在庫、已退(退回來還放在店裡)
ON_SHELF = (ProductSerial.Status.IN_STOCK, ProductSerial.Status.RETURNED)
REF = "stock_count"
REF_FOUND = "stock_count_found"
MAX_QTY = 1_000_000


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


def set_line(count, product, counted_qty, user):
    """配件:這個商品現場數到幾個(重新輸入 = 整個換掉,帳上數量也重新記)。"""
    if not isinstance(counted_qty, int) or isinstance(counted_qty, bool) or not 0 <= counted_qty <= MAX_QTY:
        raise CountError("數量要是 0 以上的整數")
    with transaction.atomic():
        _locked(count, S.COUNTING)
        _countable(count, product)
        # create=True:這家門市還沒有這個商品的餘額列時先建一列 0 再鎖(複審 P0)。只「查查看有沒有」的話,
        # 同一瞬間有人正在存第一張進貨(那一列還沒存完、看不到)會被當成帳上 0,核准時就多加一次
        balance = locked_balance(count.tenant, product, count.warehouse, create=True)
        line, _ = StockCountLine.objects.update_or_create(
            count=count, product=product,
            defaults={
                "tenant": count.tenant, "counted_qty": counted_qty, "book_qty": balance.qty,
                "counted_at": timezone.now(), "counted_by": _by(user),
            })
        return line


def remove_line(count, line_id):
    with transaction.atomic():
        _locked(count, S.COUNTING)
        if not StockCountLine.objects.filter(count=count, pk=line_id).delete()[0]:
            raise CountError("這一列不在這張盤點單上")


def scan(count, code, user):
    """手機:刷一個碼。記下刷的那一刻那一台在帳上是什麼樣子(之後賣掉的不算多、也不算少)。"""
    code = str(code or "").strip()
    key = normalize_serial(code)
    if not key or len(code) > 80:
        raise CountError("這不是有效的碼")
    with transaction.atomic():
        _locked(count, S.COUNTING)
        if StockCountScan.objects.filter(count=count, code_key=key).exists():
            raise CountError("這個碼刷過了")
        ids = find_serial_ids(count.tenant, code)
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
        return StockCountScan.objects.create(
            tenant=count.tenant, count=count, code=code, code_key=key, serial=serial, here=here,
            state=serial.status if serial else "", scanned_at=timezone.now(), scanned_by=_by(user))


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


def submit(count, user, phones_done=False):
    """盤完送出。phones_done = 送出的人表明「這個範圍的手機全部刷完了」:這時才算手機少了哪幾台。
    沒有表明的話,沒刷到的手機是「沒盤」(不進差異、不會變成盤虧)。"""
    with transaction.atomic():
        _locked(count, S.COUNTING)
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
        return count


def _decision(decisions, pk):
    d = decisions.get(pk) or decisions.get(str(pk)) or {}
    if not isinstance(d, dict):
        raise CountError("送來的內容格式不對")
    return d


def approve(count, user, lines=None, missing=None):
    """核准(管理員):照差異動庫存。lines / missing = {編號: {"adjust_qty": 整數, "skipped": 是否, "reason": 字}}
    沒有送的列 = 照「數到的 − 當時帳上的」調;手機沒有送的 = 標成盤虧。

    這一步才動庫存,而且整張在一個交易裡:任何一列不夠扣就整張不動、講是哪一個商品。
    """
    lines, missing = lines or {}, missing or {}
    M = StockMovement.MovementType
    with transaction.atomic():
        _locked(count, S.SUBMITTED)
        tenant, wh = count.tenant, count.warehouse
        rows = list(count.lines.select_related("product").order_by("id"))
        gone = list(count.missing.select_related("serial__product").order_by("id"))
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
        # **不可以改成「先鎖商品」**(複審第二輪 P1):那樣這裡是 商品 → 序號,銷貨是 序號 → 餘額連帶商品,
        # 一張銷貨單同時有那一台手機與那個配件、又剛好同時核准時,兩邊會互相等到死結。
        lock_stock_rows(
            tenant, serial_ids=[m.serial_id for m in gone if not m.skipped],
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
        count.status, count.approved_at, count.approved_by = S.APPROVED, timezone.now(), _by(user)
        count.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
        return count


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

