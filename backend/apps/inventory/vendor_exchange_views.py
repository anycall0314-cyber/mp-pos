"""廠商換貨的端點。規則在 `vendor_exchange.py`;這裡只管誰看得到、誰能動哪一台、回什麼給畫面。

誰都可以做(店員也行,不另外開權限勾選);鎖在門市的帳號只看得到、只動得到自己門市的。
"""
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.core.warehouse_scoping import locked_warehouse_id

from . import vendor_exchange as vx
from .identifiers import find_serial_ids
from .models import VendorExchange

X = VendorExchange.Status
CLOSED_MAX = 200        # 換完 / 取消的一次列最近幾筆
PENDING_MAX = 1000


def _bad(exc, status=400):
    return Response({"detail": str(exc)}, status=status)


def _store_check(request):
    """鎖在門市的帳號:鎖住那一台之後才看它在不在自己門市。"""
    own = locked_warehouse_id(request.user)

    def check(serial):
        if own is not None and serial.warehouse_id != own:
            raise vx.VendorExchangeDenied("只能動自己門市的設備")
    return check


def _row(x, today):
    end = timezone.localdate(x.done_at) if x.done_at else today
    return {
        "id": x.id,
        "status": x.status,
        "status_label": x.get_status_display(),
        "warehouse": {"id": x.warehouse_id, "code": x.warehouse.code, "name": x.warehouse.name},
        "supplier": {"id": x.supplier_id, "name": x.supplier.name} if x.supplier_id else None,
        "product": {"id": x.serial.product_id, "sku": x.serial.product.sku, "name": x.serial.product.name},
        "serial": x.serial_id,
        "sent_imei": x.sent_imei, "sent_sn": x.sent_sn,
        "back_imei": x.back_imei, "back_sn": x.back_sn,
        "swapped": x.swapped,
        "note": x.note,
        # 台灣時間(畫面取前 10 個字當日期;世界時間的話凌晨 0~8 點會變成前一天)
        "sent_by": x.sent_by, "sent_at": timezone.localtime(x.created_at).isoformat(),
        "done_by": x.done_by, "done_at": timezone.localtime(x.done_at).isoformat() if x.done_at else None,
        # 送出到今天(換完的:到換回來那天)幾天
        "days": (end - timezone.localdate(x.created_at)).days,
    }


def _rows(qs):
    today = timezone.localdate()
    return [_row(x, today) for x in qs.select_related("warehouse", "supplier", "serial__product")]


@api_view(["GET", "POST"])
def vendor_exchanges(request):
    """GET ?status=pending(還在換,最久的在前)| closed(換完與取消,最近的在前);
    POST 送廠商換貨 {code: 刷到的碼 或 serial: 設備編號, supplier: 廠商編號(可空 = 照進貨單), note: 瑕疵狀況}。"""
    if request.method == "GET":
        qs = VendorExchange.objects.filter(tenant=request.tenant)
        own = locked_warehouse_id(request.user)
        if own is not None:
            qs = qs.filter(warehouse_id=own)
        if request.query_params.get("status") == "closed":
            qs = qs.exclude(status=X.PENDING).order_by("-done_at", "-id")
            limit = CLOSED_MAX
        else:
            qs = qs.filter(status=X.PENDING).order_by("created_at", "id")
            limit = PENDING_MAX
        count = qs.count()
        return Response({"results": _rows(qs[:limit]), "count": count, "limit": limit})

    data = request.data if isinstance(request.data, dict) else {}
    serial_id = data.get("serial")
    code = data.get("code")
    if serial_id in (None, ""):
        if not isinstance(code, str) or not code.strip():
            return _bad("請刷要送廠商的那一台")
        ids = find_serial_ids(request.tenant, code)
        if not ids:
            return _bad("系統沒有這個碼")
        if len(ids) > 1:
            return _bad("這個碼對到不只一台,請改刷那一台的另一個碼")
        serial_id = ids[0]
    elif not str(serial_id).isdigit():
        return _bad("設備編號不對")
    supplier = data.get("supplier")
    if supplier in ("", None):
        supplier = None
    elif not str(supplier).isdigit():
        return _bad("廠商編號不對")
    note = data.get("note") or ""
    if not isinstance(note, str):
        return _bad("瑕疵狀況要是文字")
    try:
        x = vx.send(request.tenant, int(serial_id), user=request.user,
                    supplier_id=int(supplier) if supplier is not None else None,
                    note=note, check=_store_check(request))
    except vx.VendorExchangeDenied as exc:
        return _bad(exc, 403)
    except vx.VendorExchangeError as exc:
        return _bad(exc)
    return Response(_rows(VendorExchange.objects.filter(pk=x.pk))[0], status=201)


def _code(request):
    data = request.data if isinstance(request.data, dict) else {}
    code = data.get("code")
    return code if isinstance(code, str) else "", data


@api_view(["POST"])
def vendor_exchange_done(request, pk):
    """已換貨 {code: 刷回來那一台的 IMEI 或 SN}。"""
    code, _ = _code(request)
    try:
        x = vx.done(request.tenant, code, exchange_id=pk, user=request.user, check=_store_check(request))
    except vx.VendorExchangeDenied as exc:
        return _bad(exc, 403)
    except vx.VendorExchangeError as exc:
        return _bad(exc)
    return Response(_rows(VendorExchange.objects.filter(pk=x.pk))[0])


@api_view(["POST"])
def vendor_exchange_done_serial(request):
    """開單刷到換貨中的那一台、按「已換貨」{serial: 設備編號, code: 剛刷的碼}:碼一定要是這一台的(同一台回來)。"""
    code, data = _code(request)
    serial_id = data.get("serial")
    if not str(serial_id or "").isdigit():
        return _bad("設備編號不對")
    hits = find_serial_ids(request.tenant, code)
    if hits != [int(serial_id)]:
        return _bad("刷的碼不是這一台,請到「廠商換貨」那一頁處理")
    try:
        x = vx.done(request.tenant, code, serial_id=int(serial_id), user=request.user, check=_store_check(request))
    except vx.VendorExchangeDenied as exc:
        return _bad(exc, 403)
    except vx.VendorExchangeError as exc:
        return _bad(exc)
    return Response(_rows(VendorExchange.objects.filter(pk=x.pk))[0])


@api_view(["POST"])
def vendor_exchange_cancel(request, pk):
    """標錯了:回到在庫。"""
    try:
        x = vx.cancel(request.tenant, pk, user=request.user, check=_store_check(request))
    except vx.VendorExchangeDenied as exc:
        return _bad(exc, 403)
    except vx.VendorExchangeError as exc:
        return _bad(exc)
    return Response(_rows(VendorExchange.objects.filter(pk=x.pk))[0])
