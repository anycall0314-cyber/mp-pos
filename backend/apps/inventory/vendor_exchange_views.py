"""廠商換貨的端點。規則在 `vendor_exchange.py`;這裡只管誰看得到、誰能動哪一筆、回什麼給畫面。

送、已換貨、標錯了:誰都可以做(店員也行,不另外開權限勾選);鎖在門市的帳號只看得到、只動得到自己門市的。
不換了(配件少補 / 不補,沒回來的算損失):只有管理員(紅隊:店員能按的話,弄丟的配件送廠商再按不換了就不見了)。
成本只回給管理員(跟其他頁一樣,店員看不到成本)。
"""
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.core.warehouse_scoping import locked_warehouse_id
from apps.tenants.permissions import is_tenant_admin

from . import vendor_exchange as vx
from .identifiers import find_serial_ids
from .models import ProductSerial, StockBalance, VendorExchange, Warehouse

X = VendorExchange.Status
CLOSED_MAX = 200        # 處理過的一次列最近幾筆
PENDING_MAX = 1000


def _bad(exc, status=400):
    return Response({"detail": str(exc)}, status=status)


def _store_check(request):
    """鎖在門市的帳號:鎖住那一筆之後才看它在不在自己門市。"""
    own = locked_warehouse_id(request.user)

    def check(warehouse_id):
        if own is not None and warehouse_id != own:
            raise vx.VendorExchangeDenied("只能動自己門市的")
    return check


def _row(x, today, manager):
    end = timezone.localdate(x.done_at) if x.done_at else today
    out = {
        "id": x.id,
        "kind": "serial" if x.serial_id else "product",
        "status": x.status,
        "status_label": x.get_status_display(),
        "warehouse": {"id": x.warehouse_id, "code": x.warehouse.code, "name": x.warehouse.name},
        "supplier": {"id": x.supplier_id, "name": x.supplier.name} if x.supplier_id else None,
        "product": {"id": x.product_id, "sku": x.product.sku, "name": x.product.name},
        "serial": x.serial_id,
        "qty": x.qty, "back_qty": x.back_qty,
        "sent_imei": x.sent_imei, "sent_sn": x.sent_sn,
        "back_imei": x.back_imei, "back_sn": x.back_sn,
        "swapped": x.swapped,
        "note": x.note,
        # 台灣時間(畫面取前 10 個字當日期;世界時間的話凌晨 0~8 點會變成前一天)
        "sent_by": x.sent_by, "sent_at": timezone.localtime(x.created_at).isoformat(),
        "done_by": x.done_by, "done_at": timezone.localtime(x.done_at).isoformat() if x.done_at else None,
        # 送出到今天(處理過的:到處理那天)幾天
        "days": (end - timezone.localdate(x.created_at)).days,
    }
    if manager:
        # 還在廠商那邊(或不換了 = 沒回來)的成本
        out["amount"] = str((x.unit_cost * (x.qty - x.back_qty)).quantize(Decimal("0.01")))
    return out


def _rows(request, qs):
    today = timezone.localdate()
    manager = is_tenant_admin(request.user)
    return [_row(x, today, manager) for x in qs.select_related("warehouse", "supplier", "product")]


def _one(request, x):
    return _rows(request, VendorExchange.objects.filter(pk=x.pk))[0]


def _find_product(tenant, code):
    """刷到的條碼 / 打的品號是哪一個配件(完全相同、不分大小寫;有序號的、虛擬的不算)。"""
    code = code.strip()
    hits = list(Product.objects.filter(tenant=tenant, requires_serial=False, is_virtual=False)
                .filter(Q(barcode__iexact=code) | Q(sku__iexact=code))[:2])
    if len(hits) > 1:
        raise vx.VendorExchangeError("這個條碼對到不只一個商品,請改打品號")
    return hits[0] if hits else None


def _suppliers(tenant, product):
    return [{"id": sid, "name": name, "last": str(last)} for sid, name, last in vx.suppliers_of(tenant, product)]


@api_view(["GET"])
def vendor_exchange_lookup(request):
    """刷到的碼是哪一台設備 / 哪一個配件,送廠商之前畫面要的:?code=…
    設備:在哪家門市、能不能送、進貨的廠商。配件:各門市有幾個(鎖在門市的只有自己那一家)、進過這個品號的廠商(最近的在前)。"""
    code = request.query_params.get("code") or ""
    if not code.strip() or len(code) > 80:
        return _bad("請刷序號或條碼")
    own = locked_warehouse_id(request.user)
    ids = find_serial_ids(request.tenant, code)
    if len(ids) > 1:
        return _bad("這個碼對到不只一台,請改刷那一台的另一個碼")
    if ids:
        s = (ProductSerial.objects.select_related("product", "warehouse", "purchase_order_item__po__supplier")
             .get(pk=ids[0]))
        po = s.purchase_order_item.po if s.purchase_order_item_id else None
        return Response({
            "kind": "serial",
            "serial": s.id, "serial_no": s.serial_no,
            "product": {"id": s.product_id, "sku": s.product.sku, "name": s.product.name},
            "warehouse": {"id": s.warehouse_id, "name": s.warehouse.name} if s.warehouse_id else None,
            "status": s.status, "status_label": s.get_status_display(),
            "sendable": s.status in vx.SENDABLE and s.warehouse_id is not None
                        and (own is None or s.warehouse_id == own),
            "default_supplier": po.supplier_id if po else None,
            "suppliers": [{"id": po.supplier_id, "name": po.supplier.name, "last": str(po.doc_date)}] if po else [],
        })
    try:
        product = _find_product(request.tenant, code)
    except vx.VendorExchangeError as exc:
        return _bad(exc)
    if product is None:
        return _bad("系統沒有這個序號或條碼")
    stores = Warehouse.objects.filter(tenant=request.tenant, is_active=True).order_by("code")
    if own is not None:
        stores = stores.filter(pk=own)
    have = dict(StockBalance.objects.filter(tenant=request.tenant, product=product)
                .values_list("warehouse_id", "qty"))
    suppliers = _suppliers(request.tenant, product)
    return Response({
        "kind": "product",
        "product": {"id": product.id, "sku": product.sku, "name": product.name},
        "stores": [{"id": w.id, "name": w.name, "qty": have.get(w.id, 0)} for w in stores],
        # 只進過一家 = 就是它;兩家以上要人照標籤選
        "default_supplier": suppliers[0]["id"] if len(suppliers) == 1 else None,
        "suppliers": suppliers,
    })


def _int_or_none(value, label):
    if value in (None, ""):
        return None
    if not str(value).isdigit():
        raise vx.VendorExchangeError(f"{label}不對")
    return int(value)


@api_view(["GET", "POST"])
def vendor_exchanges(request):
    """GET ?status=pending(還在換,最久的在前)| closed(處理過的,最近的在前);
    POST 送廠商換貨:設備 {serial 或 code, supplier, note};配件 {product 或 code, warehouse, qty, supplier, note}。"""
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
        return Response({"results": _rows(request, qs[:limit]), "count": count, "limit": limit})

    data = request.data if isinstance(request.data, dict) else {}
    note = data.get("note") or ""
    if not isinstance(note, str):
        return _bad("瑕疵狀況要是文字")
    try:
        serial_id = _int_or_none(data.get("serial"), "設備編號")
        product_id = _int_or_none(data.get("product"), "商品編號")
        supplier_id = _int_or_none(data.get("supplier"), "廠商編號")
        warehouse_id = _int_or_none(data.get("warehouse"), "門市編號")
        code = data.get("code")
        if serial_id is None and product_id is None:
            if not isinstance(code, str) or not code.strip():
                return _bad("請刷要送廠商的序號或條碼")
            ids = find_serial_ids(request.tenant, code)
            if len(ids) > 1:
                return _bad("這個碼對到不只一台,請改刷那一台的另一個碼")
            if ids:
                serial_id = ids[0]
            else:
                product = _find_product(request.tenant, code)
                if product is None:
                    return _bad("系統沒有這個序號或條碼")
                product_id = product.id
        if serial_id is None:
            own = locked_warehouse_id(request.user)
            if own is not None:
                warehouse_id = own
        x = vx.send(request.tenant, serial_id=serial_id, product_id=product_id, warehouse_id=warehouse_id,
                    qty=data.get("qty", 1), user=request.user, supplier_id=supplier_id, note=note,
                    check=_store_check(request))
    except vx.VendorExchangeDenied as exc:
        return _bad(exc, 403)
    except vx.VendorExchangeError as exc:
        return _bad(exc)
    return Response(_one(request, x), status=201)


@api_view(["POST"])
def vendor_exchange_done(request, pk):
    """已換貨。設備 {code: 刷回來那一台的 IMEI 或 SN};配件 {qty: 回來幾個(沒給 = 剩下的全部)}。"""
    data = request.data if isinstance(request.data, dict) else {}
    code = data.get("code")
    try:
        x = vx.done(request.tenant, code if isinstance(code, str) else "", qty=data.get("qty"),
                    exchange_id=pk, user=request.user, check=_store_check(request))
    except vx.VendorExchangeDenied as exc:
        return _bad(exc, 403)
    except vx.VendorExchangeError as exc:
        return _bad(exc)
    return Response(_one(request, x))


@api_view(["POST"])
def vendor_exchange_done_serial(request):
    """開單刷到換貨中的那一台、按「已換貨」{serial: 設備編號, code: 剛刷的碼}:碼一定要是這一台的(同一台回來)。"""
    data = request.data if isinstance(request.data, dict) else {}
    code = data.get("code") if isinstance(data.get("code"), str) else ""
    serial_id = data.get("serial")
    if not str(serial_id or "").isdigit():
        return _bad("設備編號不對")
    if find_serial_ids(request.tenant, code) != [int(serial_id)]:
        return _bad("刷的碼不是這一台,請到「廠商換貨」那一頁處理")
    try:
        x = vx.done(request.tenant, code, serial_id=int(serial_id), user=request.user, check=_store_check(request))
    except vx.VendorExchangeDenied as exc:
        return _bad(exc, 403)
    except vx.VendorExchangeError as exc:
        return _bad(exc)
    return Response(_one(request, x))


@api_view(["POST"])
def vendor_exchange_cancel(request, pk):
    """標錯了:回到原樣(還沒回來任何東西時)。"""
    try:
        x = vx.cancel(request.tenant, pk, user=request.user, check=_store_check(request))
    except vx.VendorExchangeDenied as exc:
        return _bad(exc, 403)
    except vx.VendorExchangeError as exc:
        return _bad(exc)
    return Response(_one(request, x))


@api_view(["POST"])
def vendor_exchange_unreturned(request, pk):
    """不換了(配件,只有管理員):沒回來的不加回,這一筆結束。"""
    if not is_tenant_admin(request.user):
        return _bad("不換了只有管理員可以按", 403)
    try:
        x = vx.unreturned(request.tenant, pk, user=request.user, check=_store_check(request))
    except vx.VendorExchangeDenied as exc:
        return _bad(exc, 403)
    except vx.VendorExchangeError as exc:
        return _bad(exc)
    return Response(_one(request, x))
