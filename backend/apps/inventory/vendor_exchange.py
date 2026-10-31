"""瑕疵品送廠商換貨(owner 2026-10-21)。

以前:調去維修倉寄放,廠商換完再調回門市 —— 門市常漏調回。現在不搬、不調撥,兩種:

**有序號的設備**(手機、平板、手錶)
- 送廠商換貨:那一台留在原門市的帳上,狀態「廠商換貨中」(`ProductSerial.Status.RMA`):不能賣、不能調撥、
  盤點不用刷(盤點單另外列出來,不會從表上消失);報表、每日快照、平均成本都照樣算它。
- 已換貨:一定要刷回來的那一台(紅隊:不刷就按,廠商換了新機、帳上還是舊序號,掉包查不出來)。
  碼是這一台的 = 同一台回來;系統沒有的碼 = 廠商換了一台 → 這一台的碼改成新的(`set_codes`,留修改紀錄),
  舊機另外登記的碼(IMEI2、EID…)一起拿掉;成本、進貨來源、門市照舊。別台設備的碼不收。
- 異動寫一筆「廠商換貨」、不寫門市 = 只是紀錄、不動數量。

**配件**(按數量的;owner:「換貨的通常都是配件沒序號也可以嗎」)
- 送廠商換貨:從這家門市的數量扣掉(異動寫來源門市;進銷存表的「換貨」欄),記下送出那一刻的平均成本。
- 已換貨:填回來幾個(可以分批),加回原門市,成本照送出時的(跟現在的平均再平均,跟進貨一樣算)。
- 不換了(畫面只給管理員):廠商少補 / 不補,沒回來的不加回,這一筆結束(紅隊)。

兩種共用:
- **廠商一定要有**(紅隊:可以空著的話,弄丟的按送廠商就從庫存消失了)。設備沒選就照進貨單;配件要人選。
- 標錯了:還沒回來任何東西時可以取消,回到原樣、留紀錄。
- 鎖的順序:設備 = 先鎖設備、再鎖換貨那一筆;配件 = 先鎖換貨那一筆(單據),再照 `lock_stock_rows` 鎖商品與庫存餘額。
- `check(門市編號)`:鎖住、重讀之後才呼叫,不准就丟 `VendorExchangeDenied`(在不在他的門市要在這裡判斷)。
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.identity.normalize import normalize_serial

from .identifiers import IdentifierError, codes_of, find_serial_ids, looks_like_imei, set_codes
from .locking import lock_stock_rows, locked_balance
from .models import ProductSerial, StockMovement, VendorExchange, Warehouse, book_cost

S = ProductSerial.Status
X = VendorExchange.Status
SENDABLE = (S.IN_STOCK, S.RETURNED)
REF = "vendor_exchange"
CENTS = Decimal("0.01")
MAX_QTY = 9999


class VendorExchangeError(ValueError):
    """不能這樣做(訊息直接給畫面)。"""


class VendorExchangeDenied(VendorExchangeError):
    """這個帳號不能動這一筆。"""


def _by(user) -> str:
    return user.get_username() if user is not None else ""


def _record(exchange, note, *, serial=None, qty=1, source=None, target=None):
    StockMovement.objects.create(
        tenant_id=exchange.tenant_id, serial=serial, product=None if serial else exchange.product,
        qty=qty, movement_type=StockMovement.MovementType.VENDOR_EXCHANGE,
        from_warehouse=source, to_warehouse=target,
        ref_doc_type=REF, ref_doc_id=exchange.pk, note=note[:200],
    )


def _note(note):
    note = str(note or "").strip()
    if len(note) > 200:
        raise VendorExchangeError("瑕疵狀況最多 200 個字")
    return note


def _supplier(tenant, supplier_id):
    from apps.parties.models import Supplier

    if supplier_id is None:
        return None
    if not Supplier.objects.filter(tenant=tenant, pk=supplier_id).exists():
        raise VendorExchangeError("找不到這家廠商")
    return supplier_id


def suppliers_of(tenant, product):
    """進過這個商品的廠商,最近進過的在前:[(廠商編號, 名稱, 最近一次進貨日)]。作廢的進貨單不算。
    同一個品號跟兩家進過的,配件分不出這一個是哪家的 —— 畫面列這幾家讓人照標籤選(owner 2026-10-21)。"""
    from django.db.models import Max

    from apps.purchasing.models import PurchaseOrderItem

    rows = (PurchaseOrderItem.objects.filter(tenant=tenant, product=product, po__is_void=False)
            .values("po__supplier_id", "po__supplier__name")
            .annotate(last=Max("po__doc_date"), newest=Max("po_id"))      # 同一天的:後建的那張在前
            .order_by("-last", "-newest"))
    return [(r["po__supplier_id"], r["po__supplier__name"], r["last"]) for r in rows]


def send(tenant, *, serial_id=None, product_id=None, warehouse_id=None, qty=1,
         user=None, supplier_id=None, note="", check=None):
    """送廠商換貨:有 serial_id = 那一台設備;否則 = 配件(商品、門市、數量)。回那一筆 `VendorExchange`。"""
    note = _note(note)
    supplier_id = _supplier(tenant, supplier_id)
    if serial_id is not None:
        return _send_serial(tenant, serial_id, user=user, supplier_id=supplier_id, note=note, check=check)
    return _send_product(tenant, product_id, warehouse_id, qty, user=user, supplier_id=supplier_id,
                         note=note, check=check)


def _send_serial(tenant, serial_id, *, user, supplier_id, note, check):
    with transaction.atomic():
        serial = (ProductSerial.objects.select_for_update(of=("self",))
                  .select_related("purchase_order_item__po", "warehouse")
                  .filter(tenant=tenant, pk=serial_id).first())
        if serial is None:
            raise VendorExchangeError("找不到這一台")
        if check is not None:
            check(serial.warehouse_id)
        if serial.status not in SENDABLE or serial.warehouse_id is None:
            raise VendorExchangeError(f"這一台{serial.get_status_display()},不能送廠商換貨")
        if supplier_id is None and serial.purchase_order_item is not None:
            supplier_id = serial.purchase_order_item.po.supplier_id
        if supplier_id is None:
            raise VendorExchangeError("請選廠商")
        codes = codes_of(serial)
        exchange = VendorExchange.objects.create(
            tenant=tenant, serial=serial, product_id=serial.product_id, warehouse_id=serial.warehouse_id,
            supplier_id=supplier_id, note=note, unit_cost=book_cost(serial),
            sent_imei=codes["imei"], sent_sn=codes["sn"], sent_by=_by(user),
            was_returned=serial.status == S.RETURNED,
        )
        serial.status = S.RMA
        serial.save(update_fields=["status", "updated_at"])
        _record(exchange, f"送廠商換貨 {serial.warehouse.code}" + (f":{note}" if note else ""), serial=serial)
    return exchange


def _count(qty, most=MAX_QTY):
    try:
        n = int(qty)
    except (TypeError, ValueError):
        raise VendorExchangeError("數量要是整數")
    if n < 1 or n > most:
        raise VendorExchangeError(f"數量要在 1 到 {most} 之間")
    return n


def _send_product(tenant, product_id, warehouse_id, qty, *, user, supplier_id, note, check):
    from apps.catalog.models import Product

    n = _count(qty)
    product = Product.objects.filter(tenant=tenant, pk=product_id).first()
    if product is None:
        raise VendorExchangeError("找不到這個商品")
    if product.requires_serial:
        raise VendorExchangeError("有序號的商品請刷那一台的序號")
    if product.is_virtual:
        raise VendorExchangeError("虛擬商品沒有庫存,不能送廠商")
    warehouse = Warehouse.objects.filter(tenant=tenant, pk=warehouse_id).first()
    if warehouse is None:
        raise VendorExchangeError("請選門市")
    if supplier_id is None:
        raise VendorExchangeError("請選廠商")
    with transaction.atomic():
        if check is not None:
            check(warehouse.pk)
        lock_stock_rows(tenant, balances=[(product, warehouse)])
        balance = locked_balance(tenant, product, warehouse)
        have = balance.qty if balance is not None else 0
        if have < n:
            raise VendorExchangeError(f"{warehouse.name}只有 {have} 個")
        balance.qty -= n
        balance.save(update_fields=["qty"])
        exchange = VendorExchange.objects.create(
            tenant=tenant, product=product, warehouse=warehouse, qty=n, supplier_id=supplier_id,
            unit_cost=balance.weighted_avg_cost, note=note, sent_by=_by(user),
        )
        _record(exchange, f"送廠商換貨 {product.sku} ×{n}" + (f":{note}" if note else ""),
                qty=n, source=warehouse)
    return exchange


def _locked_serial(tenant, *, exchange_id=None, serial_id=None, check=None):
    """設備:鎖住設備、再鎖還在換的那一筆;回 (設備, 換貨)。"""
    serial = ProductSerial.objects.select_for_update().filter(tenant=tenant, pk=serial_id).first()
    if serial is None:
        raise VendorExchangeError("找不到這一台")
    pending = VendorExchange.objects.select_for_update().filter(tenant=tenant, serial=serial, status=X.PENDING)
    if exchange_id is not None:
        pending = pending.filter(pk=exchange_id)
    exchange = pending.first()
    if exchange is None:
        raise VendorExchangeError("這一筆已經處理過了" if exchange_id is not None else "這一台沒有在廠商換貨")
    if check is not None:
        check(exchange.warehouse_id)
    # 不該發生(換貨中的設備只有這裡會改狀態);發生了就別亂動,交給每日對帳與人工
    if serial.status != S.RMA or serial.warehouse_id != exchange.warehouse_id:
        raise VendorExchangeError(f"這一台現在{serial.get_status_display()},跟換貨紀錄對不上,請管理員處理")
    return serial, exchange


def _locked_product(tenant, exchange_id, check=None):
    """配件:先鎖換貨那一筆(單據)、重讀,再鎖商品與原門市的庫存餘額;回 (換貨, 庫存餘額)。"""
    exchange = (VendorExchange.objects.select_for_update(of=("self",)).select_related("product", "warehouse")
                .filter(tenant=tenant, pk=exchange_id).first())
    if exchange is None:
        raise VendorExchangeError("找不到這一筆廠商換貨")
    if exchange.status != X.PENDING:
        raise VendorExchangeError("這一筆已經處理過了")
    if check is not None:
        check(exchange.warehouse_id)
    lock_stock_rows(tenant, products=[exchange.product], balances=[(exchange.product, exchange.warehouse)],
                    create=True)
    return exchange, locked_balance(tenant, exchange.product, exchange.warehouse)


def _put_back(exchange, balance, n):
    """配件 n 個加回原門市,成本照送出時的(跟現在的平均再平均)。"""
    from apps.purchasing.services import _recompute_product_avg_cost

    total = balance.qty + n
    balance.weighted_avg_cost = (
        (Decimal(balance.qty) * balance.weighted_avg_cost + Decimal(n) * exchange.unit_cost) / Decimal(total)
    ).quantize(CENTS)
    balance.qty = total
    balance.save(update_fields=["qty", "weighted_avg_cost"])
    _recompute_product_avg_cost(exchange.tenant, exchange.product)


def _close(exchange, status, user, fields=()):
    exchange.status = status
    exchange.done_by = _by(user)
    exchange.done_at = timezone.now()
    exchange.save(update_fields=["status", "done_by", "done_at", "updated_at", *fields])


def kind_of(tenant, exchange_id):
    """這一筆是設備還是配件:回設備編號(配件 = None)。找不到丟錯。"""
    row = (VendorExchange.objects.filter(tenant=tenant, pk=exchange_id)
           .values_list("serial_id", flat=True))
    if not row.exists():
        raise VendorExchangeError("找不到這一筆廠商換貨")
    return row.first()


def done(tenant, code=None, *, qty=None, exchange_id=None, serial_id=None, user=None, check=None):
    """已換貨。設備:刷回來的那一台(code);配件:回來幾個(qty,沒給 = 剩下的全部)。回那一筆 `VendorExchange`。"""
    if serial_id is None:
        serial_id = kind_of(tenant, exchange_id)
    if serial_id is None:
        return _done_product(tenant, exchange_id, qty, user=user, check=check)
    return _done_serial(tenant, code, exchange_id=exchange_id, serial_id=serial_id, user=user, check=check)


def _done_serial(tenant, code, *, exchange_id, serial_id, user, check):
    code = str(code or "").strip()
    key = normalize_serial(code)
    if not key or len(code) > 80:
        raise VendorExchangeError("請刷回來那一台的 IMEI 或 SN")
    with transaction.atomic():
        serial, exchange = _locked_serial(tenant, exchange_id=exchange_id, serial_id=serial_id, check=check)
        hits = find_serial_ids(tenant, code)
        if hits and hits != [serial.pk]:
            raise VendorExchangeError("這個碼是別台設備的,請刷廠商換回來的那一台")
        swapped = not hits
        gone = []
        if swapped:
            imei, sn = (code, "") if looks_like_imei(code) else ("", code)
            try:
                set_codes(serial, imei=imei, sn=sn, user=user, may_change=True)
            except IdentifierError as exc:
                raise VendorExchangeError(str(exc))
            # 舊機另外登記的碼(拍照入庫才會有:IMEI2、EID、第二個 SN)是舊機的,不能留在這一台
            extra = serial.identifiers.exclude(normalized_value=key)
            gone = [f"{i.get_kind_display()} {i.value}" for i in extra]
            extra.delete()
            serial.refresh_from_db()
        codes = codes_of(serial)
        serial.status = S.IN_STOCK
        serial.save(update_fields=["status", "updated_at"])
        exchange.back_imei, exchange.back_sn = codes["imei"], codes["sn"]
        exchange.swapped = swapped
        exchange.back_qty = 1
        _close(exchange, X.DONE, user, ("back_imei", "back_sn", "swapped", "back_qty"))
        if swapped:
            old = "/".join(c for c in (exchange.sent_imei, exchange.sent_sn) if c)
            note = f"已換貨:換成另一台 {code}(原本 {old})"
            if gone:
                note += ";舊機的 " + "、".join(gone) + " 一起拿掉"
        else:
            note = "已換貨:同一台回來"
        _record(exchange, note, serial=serial)
    return exchange


def _done_product(tenant, exchange_id, qty, *, user, check):
    with transaction.atomic():
        exchange, balance = _locked_product(tenant, exchange_id, check=check)
        left = exchange.qty - exchange.back_qty
        n = left if qty in (None, "") else _count(qty, left)
        _put_back(exchange, balance, n)
        exchange.back_qty += n
        if exchange.back_qty == exchange.qty:
            _close(exchange, X.DONE, user, ("back_qty",))
        else:
            exchange.save(update_fields=["back_qty", "updated_at"])
        rest = exchange.qty - exchange.back_qty
        _record(exchange, f"已換貨 {exchange.product.sku} ×{n}" + (f"(還有 {rest} 個在廠商)" if rest else ""),
                qty=n, target=exchange.warehouse)
    return exchange


def cancel(tenant, exchange_id, *, user=None, check=None):
    """標錯了:回到原樣(設備回在庫 —— 送出前是已退的回到已退;配件數量加回去)。已經回來一部分的不能取消。"""
    serial_id = kind_of(tenant, exchange_id)
    with transaction.atomic():
        if serial_id is not None:
            serial, exchange = _locked_serial(tenant, exchange_id=exchange_id, serial_id=serial_id, check=check)
            serial.status = S.RETURNED if exchange.was_returned else S.IN_STOCK
            serial.save(update_fields=["status", "updated_at"])
            _close(exchange, X.CANCELLED, user)
            _record(exchange, "取消送廠商換貨", serial=serial)
            return exchange
        exchange, balance = _locked_product(tenant, exchange_id, check=check)
        if exchange.back_qty:
            raise VendorExchangeError("已經回來一部分了,不能取消")
        _put_back(exchange, balance, exchange.qty)
        _close(exchange, X.CANCELLED, user)
        _record(exchange, f"取消送廠商換貨 {exchange.product.sku} ×{exchange.qty}", qty=exchange.qty,
                target=exchange.warehouse)
    return exchange


def unreturned(tenant, exchange_id, *, user=None, check=None):
    """不換了(配件;要不要只給管理員由端點決定):沒回來的不加回,這一筆結束。"""
    if kind_of(tenant, exchange_id) is not None:
        raise VendorExchangeError("設備請刷回來的那一台按已換貨")
    with transaction.atomic():
        exchange, _ = _locked_product(tenant, exchange_id, check=check)
        lost = exchange.qty - exchange.back_qty
        _close(exchange, X.UNRETURNED, user)
        # 數量在送出時就扣了,這裡不動數量,只留紀錄(不寫門市)
        _record(exchange, f"不換了 {exchange.product.sku}:少回 {lost} 個", qty=lost)
    return exchange
