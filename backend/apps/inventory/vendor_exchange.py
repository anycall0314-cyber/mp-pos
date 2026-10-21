"""瑕疵設備送廠商換貨(owner 2026-10-21)。

以前:調去維修倉寄放,廠商換完再調回門市 —— 門市常漏調回。現在不搬:
- **送廠商換貨**:那一台留在原門市的帳上,狀態「廠商換貨中」(`ProductSerial.Status.RMA`):不能賣、不能調撥、
  盤點不用刷(盤點單另外列出來,不會從表上消失);報表與每日快照本來就把它算在門市。
- **已換貨**:一定要刷回來的那一台(紅隊:不刷就按,廠商換了新機、帳上還是舊序號,掉包查不出來)。
  碼是這一台的 = 同一台回來;系統沒有的碼 = 廠商換了一台 → 這一台的碼改成新的(`set_codes`,留修改紀錄),
  舊機另外登記的碼(IMEI2、EID…)一起拿掉;成本、進貨來源、門市照舊。別台設備的碼不收。
- **取消**:標錯了,回到在庫、留紀錄。
- 每一次都寫一筆 `StockMovement`(廠商換貨,不寫門市 = 只是紀錄、不動數量),序號履歷看得到。

鎖的順序:先鎖那一台設備,再鎖換貨那一筆(跟賣、調撥一樣先鎖設備)。
`check(設備)`:鎖住、重讀之後才呼叫,不准就丟 `VendorExchangeDenied`(在不在他的門市要在這裡判斷)。
"""
from django.db import transaction
from django.utils import timezone

from apps.identity.normalize import normalize_serial

from .identifiers import IdentifierError, codes_of, find_serial_ids, looks_like_imei, set_codes
from .models import ProductSerial, StockMovement, VendorExchange

S = ProductSerial.Status
X = VendorExchange.Status
SENDABLE = (S.IN_STOCK, S.RETURNED)
REF = "vendor_exchange"


class VendorExchangeError(ValueError):
    """不能這樣做(訊息直接給畫面)。"""


class VendorExchangeDenied(VendorExchangeError):
    """這個帳號不能動這一台。"""


def _by(user) -> str:
    return user.get_username() if user is not None else ""


def _record(serial, exchange, note):
    StockMovement.objects.create(
        tenant_id=serial.tenant_id, serial=serial, qty=1,
        movement_type=StockMovement.MovementType.VENDOR_EXCHANGE,
        ref_doc_type=REF, ref_doc_id=exchange.pk, note=note[:200],
    )


def _supplier_of(serial):
    item = serial.purchase_order_item
    return item.po.supplier_id if item is not None else None


def send(tenant, serial_id, *, user=None, supplier_id=None, note="", check=None):
    """送廠商換貨。回那一筆 `VendorExchange`。"""
    note = str(note or "").strip()
    if len(note) > 200:
        raise VendorExchangeError("瑕疵狀況最多 200 個字")
    with transaction.atomic():
        serial = (ProductSerial.objects.select_for_update(of=("self",))
                  .select_related("purchase_order_item__po", "warehouse")
                  .filter(tenant=tenant, pk=serial_id).first())
        if serial is None:
            raise VendorExchangeError("找不到這一台")
        if check is not None:
            check(serial)
        if serial.status not in SENDABLE or serial.warehouse_id is None:
            raise VendorExchangeError(f"這一台{serial.get_status_display()},不能送廠商換貨")
        if supplier_id is not None:
            from apps.parties.models import Supplier
            if not Supplier.objects.filter(tenant=tenant, pk=supplier_id).exists():
                raise VendorExchangeError("找不到這家廠商")
        codes = codes_of(serial)
        exchange = VendorExchange.objects.create(
            tenant=tenant, serial=serial, warehouse_id=serial.warehouse_id,
            supplier_id=supplier_id if supplier_id is not None else _supplier_of(serial),
            note=note, sent_imei=codes["imei"], sent_sn=codes["sn"], sent_by=_by(user),
        )
        serial.status = S.RMA
        serial.save(update_fields=["status", "updated_at"])
        _record(serial, exchange, f"送廠商換貨 {serial.warehouse.code}" + (f":{note}" if note else ""))
    return exchange


def _locked(tenant, *, exchange_id=None, serial_id=None, check=None):
    """鎖住設備、再鎖還在換的那一筆;回 (設備, 換貨)。"""
    if exchange_id is not None:
        serial_id = (VendorExchange.objects.filter(tenant=tenant, pk=exchange_id)
                     .values_list("serial_id", flat=True).first())
        if serial_id is None:
            raise VendorExchangeError("找不到這一筆廠商換貨")
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
        check(serial)
    # 不該發生(換貨中的設備只有這裡會改狀態);發生了就別亂動,交給每日對帳與人工
    if serial.status != S.RMA or serial.warehouse_id != exchange.warehouse_id:
        raise VendorExchangeError(f"這一台現在{serial.get_status_display()},跟換貨紀錄對不上,請管理員處理")
    return serial, exchange


def done(tenant, code, *, exchange_id=None, serial_id=None, user=None, check=None):
    """已換貨:刷回來的那一台。回那一筆 `VendorExchange`。"""
    code = str(code or "").strip()
    key = normalize_serial(code)
    if not key or len(code) > 80:
        raise VendorExchangeError("請刷回來那一台的 IMEI 或 SN")
    with transaction.atomic():
        serial, exchange = _locked(tenant, exchange_id=exchange_id, serial_id=serial_id, check=check)
        hits = find_serial_ids(tenant, code)
        if hits and hits != [serial.pk]:
            raise VendorExchangeError("這個碼是別台設備的,請刷廠商換回來的那一台")
        swapped = not hits
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
        exchange.status = X.DONE
        exchange.back_imei, exchange.back_sn = codes["imei"], codes["sn"]
        exchange.swapped = swapped
        exchange.done_by = _by(user)
        exchange.done_at = timezone.now()
        exchange.save(update_fields=["status", "back_imei", "back_sn", "swapped", "done_by", "done_at", "updated_at"])
        if swapped:
            old = "/".join(c for c in (exchange.sent_imei, exchange.sent_sn) if c)
            note = f"已換貨:換成另一台 {code}(原本 {old})"
            if gone:
                note += ";舊機的 " + "、".join(gone) + " 一起拿掉"
        else:
            note = "已換貨:同一台回來"
        _record(serial, exchange, note)
    return exchange


def cancel(tenant, exchange_id, *, user=None, check=None):
    """標錯了:回到在庫。"""
    with transaction.atomic():
        serial, exchange = _locked(tenant, exchange_id=exchange_id, check=check)
        serial.status = S.IN_STOCK
        serial.save(update_fields=["status", "updated_at"])
        exchange.status = X.CANCELLED
        exchange.done_by = _by(user)
        exchange.done_at = timezone.now()
        exchange.save(update_fields=["status", "done_by", "done_at", "updated_at"])
        _record(serial, exchange, "取消送廠商換貨")
    return exchange
