"""廠商叫貨的 API。一律只看自己公司;鎖在門市的帳號只能用、只看得到自己門市的。

- 叫貨串接(金鑰與預設):看 → 登入的人(自己門市);改 → 只有管理員。**金鑰原文任何回應都沒有**;前幾碼只有管理員看得到。
- 叫貨(看廠商的商品與進價、送出、再送一次、更新進度)→ 要有員工帳號的「廠商叫貨」。看叫貨單清單照舊。
- 到貨入庫(看這張單到了什麼、入庫、把不是從這裡叫的單認進來、記到貨問題)→ 要有「進貨入庫」(它開出來的就是進貨單)。
"""
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.warehouse_scoping import locked_warehouse_id
from apps.inventory.models import Warehouse
from apps.tenants import abilities
from apps.tenants.permissions import is_tenant_admin

from apps.parties.models import Supplier

from . import moceo, receiving, secrets, services
from .models import Provider, VendorLink, VendorOrder, VendorSecret

LIST_ROWS = 100
LINK_FIELDS = ("payment_method", "delivery_method", "ship_name", "ship_phone", "ship_address",
               "invoice_type", "buyer_tax_id", "buyer_name", "invoice_email")
LINK_LIMITS = {"payment_method": 20, "delivery_method": 20, "ship_name": 60, "ship_phone": 40, "ship_address": 200,
               "invoice_type": 10, "buyer_tax_id": 20, "buyer_name": 120, "invoice_email": 200}


def _bad(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"detail": str(message)}, status=code)


def _store(request, raw, *, required=True):
    """這個請求指的是哪一家門市。鎖在門市的帳號只能是自己那一家(指別家 → 403)。"""
    own = locked_warehouse_id(request.user)
    wanted = int(raw) if isinstance(raw, int) and not isinstance(raw, bool) else (
        int(raw) if isinstance(raw, str) and raw.isdigit() else None)
    if own is not None:
        if wanted is not None and wanted != own:
            raise PermissionDenied("不可以用別家門市叫貨")
        wanted = own
    if wanted is None:
        if required:
            raise services.VendorError("要指定門市")
        return None
    store = Warehouse.objects.filter(tenant=request.tenant, pk=wanted).first()
    if store is None:
        raise services.VendorError("找不到這家門市")
    return store


def _link(request, store):
    return VendorLink.objects.filter(tenant=request.tenant, provider=Provider.MOCEO, warehouse=store).first()


def _money(value):
    return None if value is None else str(value)


def _link_data(store, link, hints, manager) -> dict:
    """`hints` = {串接編號: (前幾碼, 是不是沙盒)},只列有金鑰的。"""
    data = {
        "warehouse": store.id,
        "warehouse_name": store.name,
        "provider": Provider.MOCEO,
        "provider_label": Provider.MOCEO.label,
        "saved": link is not None,
        # 沒設定過的門市:收件先帶門市自己的名稱、電話、地址(存了才算數)
        "payment_method": link.payment_method if link else "月結",
        "delivery_method": link.delivery_method if link else "宅配",
        "ship_name": link.ship_name if link else store.name,
        "ship_phone": link.ship_phone if link else store.phone,
        "ship_address": link.ship_address if link else store.address,
        "invoice_type": link.invoice_type if link else "個人",
        "buyer_tax_id": link.buyer_tax_id if link else "",
        "buyer_name": link.buyer_name if link else "",
        "invoice_email": link.invoice_email if link else "",
        # 到貨入庫:進貨單記在哪個供應商(沒指定 = 第一次入庫時自動用 / 建一筆跟廠商同名的)、運費要不要算進成本
        "supplier": link.supplier_id if link else None,
        "supplier_name": link.supplier.name if link and link.supplier_id else "",
        "freight_into_cost": link.freight_into_cost if link else True,
        "has_key": bool(link and link.id in hints),
        # 廠商說這把是測試(沙盒)金鑰:用它叫的是測試單。大家都看得到(叫貨的人要知道現在是不是玩真的)
        "sandbox": hints[link.id][1] if link and link.id in hints else None,
        "choices": {"payment_method": list(moceo.PAYMENT_METHODS), "delivery_method": list(moceo.DELIVERY_METHODS),
                    "invoice_type": list(moceo.INVOICE_TYPES)},
    }
    if manager:
        data["key_hint"] = hints[link.id][0] if link and link.id in hints else ""
    return data


def _hints(tenant, link=None) -> dict:
    rows = VendorSecret.objects.filter(tenant=tenant)
    if link is not None:
        rows = rows.filter(link=link)
    return {link_id: (hint, sandbox) for link_id, hint, sandbox in rows.values_list("link_id", "hint", "sandbox")}


def _receipt_data(receipt) -> dict:
    po = receipt.purchase_order
    return {
        "id": receipt.id,
        "purchase_order": po.id,
        "purchase_order_no": po.no,
        "is_void": po.is_void,
        "total_cost": _money(po.total_cost),
        "freight": _money(receipt.freight),
        "qty": sum(i.qty for i in receipt.items.all()),
        "created_at": receipt.created_at,
        "created_by": receipt.created_by.get_username() if receipt.created_by else "",
    }


def _order_data(order: VendorOrder) -> dict:
    return {
        "id": order.id,
        "provider": order.provider,
        "source": order.source,
        "issue_note": order.issue_note,
        "receipts": [_receipt_data(r) for r in order.receipts.all()],
        "warehouse": order.warehouse_id,
        "warehouse_name": order.warehouse.name,
        "request_key": order.request_key,
        "state": order.state,
        "state_label": order.get_state_display(),
        "problem": order.problem,
        "vendor_order_no": order.vendor_order_no,
        "total_amount": _money(order.total_amount),
        "shipping_fee": _money(order.shipping_fee),
        "expected_goods": _money(order.expected_goods),
        "amount_matches": order.amount_matches,
        "is_test": order.is_test,
        "payment_method": order.payment_method,
        "delivery_method": order.delivery_method,
        "ship_name": order.ship_name,
        "ship_phone": order.ship_phone,
        "ship_address": order.ship_address,
        "invoice_type": order.invoice_type,
        "note": order.note,
        "vendor_status": order.vendor_status,
        "vendor_payment_status": order.vendor_payment_status,
        "vendor_logistics_status": order.vendor_logistics_status,
        "vendor_shipping_method": order.vendor_shipping_method,
        "vendor_tracking_no": order.vendor_tracking_no,
        "vendor_ordered_at": order.vendor_ordered_at,
        "status_checked_at": order.status_checked_at,
        "created_at": order.created_at,
        "created_by": order.created_by.get_username() if order.created_by else "",
        "items": [{
            "line_no": i.line_no, "sku": i.sku, "spec_id": i.spec_id, "spec_label": i.spec_label, "name": i.name,
            "unit": i.unit, "pack_qty": i.pack_qty, "packs": i.packs, "qty": i.qty, "unit_price": _money(i.unit_price),
        } for i in order.items.all()],
    }


def _orders(request, store=None):
    qs = VendorOrder.objects.filter(tenant=request.tenant).select_related("warehouse", "created_by") \
        .prefetch_related("items", "receipts__purchase_order", "receipts__items", "receipts__created_by")
    own = locked_warehouse_id(request.user)
    if own is not None:
        qs = qs.filter(warehouse_id=own)
    if store is not None:
        qs = qs.filter(warehouse=store)
    return qs


# ── 叫貨串接 ────────────────────────────────────────────────────────────────
@api_view(["GET", "POST"])
def links(request):
    manager = is_tenant_admin(request.user)
    if request.method == "GET":
        stores = Warehouse.objects.filter(tenant=request.tenant, is_active=True).order_by("code", "id")
        own = locked_warehouse_id(request.user)
        if own is not None:
            stores = stores.filter(pk=own)
        by_store = {l.warehouse_id: l for l in VendorLink.objects.filter(tenant=request.tenant, provider=Provider.MOCEO)}
        hints = _hints(request.tenant)
        return Response({"results": [_link_data(s, by_store.get(s.id), hints, manager) for s in stores]})

    if not manager:
        return _bad("只有管理員可以設定叫貨串接", status.HTTP_403_FORBIDDEN)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        store = _store(request, data.get("warehouse"))
        link = _link(request, store)
        values = {}
        for name in LINK_FIELDS:
            if name in data:
                value = data[name]
                if not isinstance(value, str) or len(value.strip()) > LINK_LIMITS[name]:
                    raise services.VendorError("有一格的內容太長或格式不對")
                values[name] = value.strip()
        current = _link_data(store, link, {}, False)
        merged = {name: values.get(name, current[name]) for name in LINK_FIELDS}
        services.check_header(**merged)
        if "freight_into_cost" in data:
            if not isinstance(data["freight_into_cost"], bool):
                raise services.VendorError("運費要不要算進成本,只能是「要」或「不要」")
            merged["freight_into_cost"] = data["freight_into_cost"]
        if "supplier" in data:
            raw_supplier = data["supplier"]
            supplier = None
            if raw_supplier is not None:
                supplier = Supplier.objects.filter(tenant=request.tenant, pk=raw_supplier).first() \
                    if isinstance(raw_supplier, int) and not isinstance(raw_supplier, bool) else None
                if supplier is None:
                    raise services.VendorError("找不到這個供應商")
            merged["supplier"] = supplier
        raw, sandbox = services.check_key(data["key"]) if data.get("key") else (None, None)   # 會去打廠商一次
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    if link is None:
        link, _ = VendorLink.objects.get_or_create(
            tenant=request.tenant, provider=Provider.MOCEO, warehouse=store,
            defaults={**merged, "updated_by": request.user})
    for name, value in merged.items():
        setattr(link, name, value)
    link.updated_by = request.user
    link.save()
    if raw:
        secrets.store(link, raw, request.user, sandbox)
    return Response(_link_data(store, link, _hints(request.tenant, link), True))


@api_view(["POST"])
def remove_key(request, warehouse_id: int):
    if not is_tenant_admin(request.user):
        return _bad("只有管理員可以設定叫貨串接", status.HTTP_403_FORBIDDEN)
    try:
        store = _store(request, warehouse_id)
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    link = _link(request, store)
    if link is not None:
        VendorSecret.objects.filter(link=link).delete()
    return Response(_link_data(store, link, {}, True))


# ── 叫貨 ────────────────────────────────────────────────────────────────────
@api_view(["GET"])
def catalog(request):
    abilities.require(request.user, abilities.VENDOR_ORDER)
    try:
        store = _store(request, request.query_params.get("warehouse"))
        rows = services.live_rows(_link(request, store))
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response({"warehouse": store.id, "rows": [{
        **row,
        "unit_price": _money(row["unit_price"]),
        "pack_price": None if row["unit_price"] is None else _money(row["unit_price"] * row["pack_qty"]),
    } for row in rows]})


@api_view(["GET", "POST"])
def orders(request):
    if request.method == "GET":
        try:
            store = _store(request, request.query_params.get("warehouse"), required=False)
        except services.VendorError as exc:
            return _bad(exc, exc.status)
        return Response({"results": [_order_data(o) for o in _orders(request, store)[:LIST_ROWS]]})

    abilities.require(request.user, abilities.VENDOR_ORDER)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        store = _store(request, data.get("warehouse"))
        link = _link(request, store)
        if link is None:
            raise services.VendorError("這家門市還沒有設定膜總裁的金鑰,請管理員到「系統設定 → 叫貨串接」設定")
        order, created = services.place(
            tenant=request.tenant, user=request.user, link=link, request_key=data.get("request_key"),
            lines=data.get("lines"), payment_method=data.get("payment_method") or None,
            delivery_method=data.get("delivery_method") or None, note=data.get("note") or "",
        )
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    order = _orders(request).get(pk=order.pk)
    return Response(_order_data(order), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["GET"])
def order_detail(request, pk: int):
    order = _orders(request).filter(pk=pk).first()
    if order is None:
        return _bad("找不到這張叫貨單", status.HTTP_404_NOT_FOUND)
    return Response(_order_data(order))


@api_view(["POST"])
def order_resend(request, pk: int):
    abilities.require(request.user, abilities.VENDOR_ORDER)
    order = _orders(request).filter(pk=pk).first()
    if order is None:
        return _bad("找不到這張叫貨單", status.HTTP_404_NOT_FOUND)
    try:
        order = services.resend(order)
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response(_order_data(_orders(request).get(pk=order.pk)))


@api_view(["POST"])
def sync(request):
    """更新這家門市叫貨單的進度,並帶回廠商那邊「不是從 POS 叫的」訂單。"""
    abilities.require(request.user, abilities.VENDOR_ORDER)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        store = _store(request, data.get("warehouse"))
        others = services.sync(request.tenant, _link(request, store))
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response({
        "results": [_order_data(o) for o in _orders(request, store)[:LIST_ROWS]],
        "others": others,
    })


# ── 到貨入庫 ────────────────────────────────────────────────────────────────
def _own_order(request, pk):
    return _orders(request).filter(pk=pk).first()


@api_view(["GET"])
def receiving_plan(request, pk: int):
    """這張叫貨單在廠商那邊現在的每一行:叫幾個、已出、已入庫、這次建議入幾個、對到店裡哪個品號。"""
    abilities.require(request.user, abilities.PURCHASE)
    order = _own_order(request, pk)
    if order is None:
        return _bad("找不到這張叫貨單", status.HTTP_404_NOT_FOUND)
    try:
        return Response(receiving.plan(request.tenant, order))
    except services.VendorError as exc:
        return _bad(exc, exc.status)


@api_view(["POST"])
def receive(request, pk: int):
    abilities.require(request.user, abilities.PURCHASE)
    order = _own_order(request, pk)
    if order is None:
        return _bad("找不到這張叫貨單", status.HTTP_404_NOT_FOUND)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        receipt, created = receiving.receive(
            tenant=request.tenant, user=request.user, order=order, request_key=data.get("request_key"),
            lines=data.get("lines"), manager=is_tenant_admin(request.user),
        )
        if isinstance(data.get("issue_note"), str):
            receiving.set_issue(order, data["issue_note"])
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response({"receipt": receipt.id, "order": _order_data(_orders(request).get(pk=order.pk))},
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["POST"])
def adopt(request):
    """把廠商那邊「不是從這裡叫的」一張單認進來(之後才能到貨入庫)。"""
    abilities.require(request.user, abilities.PURCHASE)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        store = _store(request, data.get("warehouse"))
        link = _link(request, store)
        if link is None:
            raise services.VendorError("這家門市還沒有設定膜總裁的金鑰,請管理員到「系統設定 → 叫貨串接」設定")
        order = receiving.adopt(tenant=request.tenant, user=request.user, link=link, order_no=data.get("order_no"))
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response(_order_data(_orders(request).get(pk=order.pk)))


@api_view(["POST"])
def issue(request, pk: int):
    """到貨問題(送錯、少到…):記一句,老闆在叫貨紀錄上看得到。空的 = 清掉。"""
    abilities.require(request.user, abilities.PURCHASE)
    order = _own_order(request, pk)
    if order is None:
        return _bad("找不到這張叫貨單", status.HTTP_404_NOT_FOUND)
    data = request.data if isinstance(request.data, dict) else {}
    if not isinstance(data.get("note"), str):
        return _bad("要有內容")
    receiving.set_issue(order, data["note"])
    return Response(_order_data(_orders(request).get(pk=order.pk)))
