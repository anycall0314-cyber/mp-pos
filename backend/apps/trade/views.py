"""批發(賣家那一半)的 API。一律只看自己公司。

- 批發單、刷機找單、接單 / 拒絕、不出、出貨、中古機上架 / 下架 → 要有員工帳號的「批發出貨」。鎖在門市的帳號只能從自己門市出貨。
- 取消出貨(會作廢那張銷貨單)→ 另外要有「作廢銷貨單」。
- 批發設定、往來的同行與代碼、商品開不開放與固定批發價、收款 → 只有管理員(價錢與帳)。
買家那一側不在這裡:平台內走 `vendor_orders` 的串接器、對外走金鑰,兩邊最後都是 `api.handle`。
"""
from datetime import date

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.core.warehouse_scoping import locked_warehouse_id
from apps.inventory.identifiers import codes_of
from apps.inventory.models import ProductSerial, Warehouse
from apps.tenants import abilities
from apps.tenants.permissions import is_tenant_admin

from . import listing, orders, partners, payments, shipping
from .base import TradeError, setting_of
from .models import (
    TradeInvite, TradeOrder, TradeOrderLine, TradePartner, TradePayment, TradeProduct, TradeSetting, TradeShipment,
    TradeShipmentLine, TradeUnit,
)

S = TradeOrder.Status
SETTING_FIELDS = ("is_open", "unit_rule", "unit_value", "auto_list_units", "units_to_all", "auto_accept", "show_qty",
                  "default_percent", "default_terms", "pay_note", "contact")
PAGE = 50


def _bad(exc, code=None):
    return Response({"detail": str(exc), **({"code": exc.code} if getattr(exc, "code", "") else {})},
                    status=code or getattr(exc, "status", status.HTTP_400_BAD_REQUEST))


def _seller(request) -> None:
    abilities.require(request.user, abilities.TRADE_SELL)


def _admin(request) -> None:
    if not is_tenant_admin(request.user):
        raise PermissionDenied("只有管理員可以改批發的設定、同行、價錢與收款")


def _money(value):
    return None if value is None else int(value)


def _when(moment) -> str:
    """給畫面看的時間:這裡的時區、到分(畫面直接切字串顯示)。"""
    return timezone.localtime(moment).isoformat(timespec="minutes")


def _int(raw):
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    return int(raw) if isinstance(raw, str) and raw.isdigit() else None


def _store(request, raw, *, required=True):
    """這個請求指的是哪一家門市。鎖在門市的帳號只能是自己那一家。"""
    own = locked_warehouse_id(request.user)
    wanted = _int(raw)
    if own is not None:
        if wanted is not None and wanted != own:
            raise PermissionDenied("不可以用別家門市出貨")
        wanted = own
    if wanted is None:
        if required:
            raise TradeError("要指定門市")
        return None
    store = Warehouse.objects.filter(tenant=request.tenant, pk=wanted).first()
    if store is None:
        raise TradeError("找不到這家門市")
    return store


def _page(request):
    limit = _int(request.query_params.get("limit")) or PAGE
    return min(max(limit, 1), 500), _int(request.query_params.get("offset")) or 0


# ── 設定 ────────────────────────────────────────────────────────────────────
def _setting_data(setting: TradeSetting) -> dict:
    return {
        **{name: getattr(setting, name) for name in SETTING_FIELDS if name != "unit_value"},
        "unit_value": _money(setting.unit_value),
        "rules": [{"key": key, "label": label} for key, label in TradeSetting.Rule.choices],
        "terms": list(partners.TERMS),
    }


@api_view(["GET", "POST"])
def settings_view(request):
    setting = setting_of(request.tenant)
    if request.method == "GET":
        if not is_tenant_admin(request.user):
            _seller(request)
        return Response(_setting_data(setting))
    _admin(request)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        fields = []
        for name in ("is_open", "auto_list_units", "units_to_all", "auto_accept", "show_qty"):
            if name in data:
                if not isinstance(data[name], bool):
                    raise TradeError("設定的內容不對")
                setattr(setting, name, data[name])
                fields.append(name)
        if "unit_rule" in data:
            if data["unit_rule"] not in TradeSetting.Rule.values:
                raise TradeError("批發價的算法不對")
            setting.unit_rule = data["unit_rule"]
            fields.append("unit_rule")
        if "unit_value" in data:
            value = data["unit_value"]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 9_999_999:
                raise TradeError("金額 / 折數要是 0 以上的整數")
            setting.unit_value = value
            fields.append("unit_value")
        if setting.unit_rule == TradeSetting.Rule.PRICE_PERCENT and not 1 <= setting.unit_value <= 100:
            raise TradeError("打幾折要填 1 到 100(90 = 九折)")
        if "default_percent" in data:
            setting.default_percent = partners.clean_percent(data["default_percent"])
            fields.append("default_percent")
        if "default_terms" in data:
            setting.default_terms = partners.clean_terms(data["default_terms"])
            fields.append("default_terms")
        for name, limit in (("pay_note", 200), ("contact", 120)):
            if name in data:
                setattr(setting, name, data[name].strip()[:limit] if isinstance(data[name], str) else "")
                fields.append(name)
    except TradeError as exc:
        return _bad(exc)
    setting.updated_by = request.user
    setting.save(update_fields=[*fields, "updated_by", "updated_at"])
    # 買家那一側:這家公司在叫貨頁上是一家「平台內」的廠商,開放 / 關掉跟著這裡走
    from apps.vendor_orders import platform

    platform.sync_vendor(request.tenant)
    return Response(_setting_data(setting))


# ── 往來的同行 ──────────────────────────────────────────────────────────────
def _partner_data(partner: TradePartner, book=None) -> dict:
    book = payments.ledger(partner) if book is None else book
    return {
        "id": partner.id, "name": partner.name, "kind": partner.kind, "status": partner.status,
        "status_label": partner.get_status_display(), "percent": partner.percent, "terms": partner.terms, "note": partner.note,
        "owed": _money(book["owed"]), "received": _money(book["received"]), "due": _money(book["due"]),
        "credit": _money(book["credit"]),
    }


@api_view(["GET"])
def partner_list(request):
    _admin(request)
    rows = TradePartner.objects.filter(tenant=request.tenant).order_by("status", "id")
    invites = TradeInvite.objects.filter(tenant=request.tenant, used_at__isnull=True, expires_at__gt=timezone.now())
    return Response({
        "partners": [_partner_data(p) for p in rows],
        "invites": [{"id": i.id, "hint": i.hint, "percent": i.percent, "terms": i.terms,
                     "expires_at": i.expires_at.isoformat()} for i in invites],
    })


@api_view(["POST"])
def partner_change(request, pk: int):
    _admin(request)
    partner = TradePartner.objects.filter(tenant=request.tenant, pk=pk).first()
    if partner is None:
        return _bad("找不到這個同行", status.HTTP_404_NOT_FOUND)
    try:
        partners.change(partner, request.user, request.data if isinstance(request.data, dict) else {})
    except TradeError as exc:
        return _bad(exc)
    return Response(_partner_data(partner))


@api_view(["POST"])
def invite_create(request):
    _admin(request)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        invite, code = partners.invite(request.tenant, request.user, percent=data.get("percent"), terms=data.get("terms"))
    except TradeError as exc:
        return _bad(exc)
    return Response({"id": invite.id, "code": code, "percent": invite.percent, "terms": invite.terms,
                     "expires_at": invite.expires_at.isoformat()}, status=status.HTTP_201_CREATED)


# ── 中古機上架 ──────────────────────────────────────────────────────────────
@api_view(["GET"])
def unit_list(request):
    """在庫的一台一筆商品(中古機 / 已拆封)與它們的上架狀況。`state` = unlisted(預設)/ listed / held / all。"""
    _seller(request)
    tenant = request.tenant
    held = TradeOrderLine.objects.filter(unit_id=OuterRef("pk"), holding=True)
    rows = (ProductSerial.objects.filter(tenant=tenant, status=ProductSerial.Status.IN_STOCK, product__requires_serial=True,
                                         product__is_virtual=False)
            .filter(Q(product__is_secondhand=True) | Q(product__condition__tracks_unit_condition=True))
            .annotate(is_held=Exists(held)))
    own = locked_warehouse_id(request.user)
    store = own or _int(request.query_params.get("warehouse"))
    if store:
        rows = rows.filter(warehouse_id=store)
    q = (request.query_params.get("q") or "").strip()
    if q:
        rows = rows.filter(Q(product__name__icontains=q) | Q(serial_no__icontains=q) | Q(identifiers__value__icontains=q)).distinct()
    state = request.query_params.get("state") or "unlisted"
    listed = TradeUnit.objects.filter(serial_id=OuterRef("pk"), is_listed=True)
    rows = rows.annotate(is_on=Exists(listed))
    if state == "unlisted":
        rows = rows.filter(is_on=False, is_held=False)
    elif state == "listed":
        rows = rows.filter(is_on=True, is_held=False)
    elif state == "held":
        rows = rows.filter(is_held=True)
    total = rows.count()
    limit, offset = _page(request)
    page = list(rows.select_related("product__condition", "warehouse").prefetch_related("identifiers")
                .order_by("-id")[offset:offset + limit])
    units = {u.serial_id: u for u in TradeUnit.objects.filter(serial__in=page)}
    holds = {line.unit_id: line for line in TradeOrderLine.objects.filter(unit__in=page, holding=True).select_related("order__partner")}
    setting = setting_of(tenant)
    out = []
    for serial in page:
        unit, hold = units.get(serial.id), holds.get(serial.id)
        out.append({
            "serial": serial.id, "serial_no": serial.serial_no, **codes_of(serial),
            "product": serial.product_id, "name": serial.product.name, "sku": serial.product.sku,
            "warehouse": serial.warehouse_id, "warehouse_name": serial.warehouse.name if serial.warehouse_id else "",
            "grade": serial.condition_grade, "battery": serial.battery_health, "note": serial.condition_note,
            "retail_price": _money(listing.retail_price(serial)), "auto_price": _money(listing.auto_price(setting, serial)),
            "is_listed": bool(unit and unit.is_listed), "price": _money(unit.price) if unit else None,
            "held_by": None if hold is None else {"order": hold.order_id, "order_no": hold.order.no, "partner": hold.order.partner.name},
        })
    return Response({"total": total, "results": out})


@api_view(["POST"])
def unit_put_on(request):
    _seller(request)
    try:
        done = listing.put_on(request.tenant, request.user, request.data.get("rows") if isinstance(request.data, dict) else None)
    except TradeError as exc:
        return _bad(exc)
    return Response({"listed": len(done)})


@api_view(["POST"])
def unit_take_off(request):
    _seller(request)
    try:
        done = listing.take_off(request.tenant, request.data.get("serials") if isinstance(request.data, dict) else None)
    except TradeError as exc:
        return _bad(exc)
    return Response({"unlisted": done})


# ── 按數量賣的商品 ──────────────────────────────────────────────────────────
@api_view(["GET", "POST"])
def product_list(request):
    """GET:可以開放批發的商品(不是虛擬、不是一台一筆的)與現在開不開放。`state` = listed / all。POST:開放 / 收回 / 改固定批發價。"""
    _admin(request)
    tenant = request.tenant
    if request.method == "POST":
        try:
            done = listing.set_products(tenant, request.user, request.data.get("rows") if isinstance(request.data, dict) else None)
        except TradeError as exc:
            return _bad(exc)
        return Response({"changed": done})
    listed = TradeProduct.objects.filter(product_id=OuterRef("pk"), is_listed=True)
    rows = (Product.objects.filter(tenant=tenant, is_active=True, is_virtual=False)
            .exclude(Q(requires_serial=True) & (Q(is_secondhand=True) | Q(condition__tracks_unit_condition=True)))
            .annotate(is_on=Exists(listed)))
    if (request.query_params.get("state") or "listed") == "listed":
        rows = rows.filter(is_on=True)
    q = (request.query_params.get("q") or "").strip()
    if q:
        rows = rows.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q))
    category = _int(request.query_params.get("category"))
    if category:
        rows = rows.filter(category_id=category)
    total = rows.count()
    limit, offset = _page(request)
    page = list(rows.select_related("category").order_by("category__sort_order", "name", "id")[offset:offset + limit])
    offers = {t.product_id: t for t in TradeProduct.objects.filter(product__in=page)}
    left = listing.available_qty(tenant, [p.id for p in page])
    return Response({"total": total, "results": [{
        "product": p.id, "sku": p.sku, "name": p.name, "category": p.category.name, "list_price": _money(p.list_price),
        "requires_serial": p.requires_serial, "is_listed": bool(offers.get(p.id) and offers[p.id].is_listed),
        "price": _money(offers[p.id].price) if p.id in offers else None, "available": left.get(p.id, 0),
    } for p in page]})


# ── 批發單 ──────────────────────────────────────────────────────────────────
def _order_rows(found) -> list[dict]:
    found = list(found)
    if not found:
        return []
    lines = {}
    for line in (TradeOrderLine.objects.filter(order__in=found).select_related("product", "unit__warehouse")
                 .prefetch_related("unit__identifiers").order_by("line_no", "id")):
        lines.setdefault(line.order_id, []).append(line)
    shipments = {}
    returned = payments.live_shipments(TradeShipment.objects.filter(order__in=found)).values_list("id", flat=True)
    live = set(returned)
    for shipment in TradeShipment.objects.filter(order__in=found).select_related("warehouse", "sales_order").order_by("id"):
        shipments.setdefault(shipment.order_id, []).append(shipment)
    shipped = {}
    for row in (TradeShipmentLine.objects.filter(shipment__order__in=found).prefetch_related("serials").order_by("id")):
        shipped.setdefault(row.shipment_id, []).append(row)
    books = {}
    out = []
    for order in found:
        book = books.setdefault(order.partner_id, {r["order"].id: r for r in payments.ledger(order.partner)["orders"]})
        money = book.get(order.id) or {"owed": 0, "paid": 0, "due": 0}
        mine = lines.get(order.id, [])
        out.append({
            "id": order.id, "no": order.no, "partner": order.partner_id, "partner_name": order.partner.name,
            "buyer_store": order.buyer_store, "status": order.status, "status_text": orders.status_text(order, mine),
            "placed_at": _when(order.created_at), "payment_method": order.payment_method,
            "delivery_method": order.delivery_method, "ship_name": order.ship_name, "ship_phone": order.ship_phone,
            "ship_address": order.ship_address, "invoice_type": order.invoice_type, "buyer_tax_id": order.buyer_tax_id,
            "buyer_name": order.buyer_name, "invoice_email": order.invoice_email, "note": order.note,
            "close_reason": order.close_reason, "closed_by_buyer": order.closed_by_buyer, "is_test": order.is_test,
            "goods_total": _money(orders.goods_total(mine)),
            "owed": _money(money["owed"]), "paid": _money(money["paid"]), "due": _money(money["due"]),
            "payment_status": payments.status_text(money["owed"], money["paid"]),
            "lines": [{
                "id": line.id, "sku": line.sku, "name": line.name, "unit_label": line.unit_label, "product": line.product_id,
                "requires_serial": line.product.requires_serial, "per_unit": bool(line.unit_id), "qty": line.qty,
                "shipped_qty": line.shipped_qty, "cancelled_qty": line.cancelled_qty, "open_qty": line.open_qty,
                "received_qty": line.received_qty,
                "unit_price": _money(line.unit_price),
                # 中古機:單上列完整的序號(機身的標籤就是這支碼),出貨的人才找得到是哪一台
                "unit": None if line.unit_id is None else {
                    "serial": line.unit_id, "serial_no": line.unit.serial_no, **codes_of(line.unit),
                    "status": line.unit.status, "status_label": line.unit.get_status_display(),
                    "warehouse": line.unit.warehouse_id,
                    "warehouse_name": line.unit.warehouse.name if line.unit.warehouse_id else "",
                },
            } for line in mine],
            "shipments": [{
                "id": s.id, "no": s.no, "warehouse_name": s.warehouse.name, "sales_order": s.sales_order_id,
                "sales_order_no": s.sales_order.no, "shipped_at": _when(s.created_at), "goods_amount": _money(s.goods_amount),
                "shipping_fee": _money(s.shipping_fee), "shipping_method": s.shipping_method, "tracking_no": s.tracking_no,
                "is_void": s.is_void, "returned": not s.is_void and s.id not in live,
                "lines": [{"line": row.line_id, "qty": row.qty,
                           "serials": [x.imei or x.sn for x in row.serials.all()]} for row in shipped.get(s.id, [])],
            } for s in shipments.get(order.id, [])],
        })
    return out


def _own(request, pk) -> TradeOrder | None:
    return TradeOrder.objects.filter(tenant=request.tenant, pk=pk).select_related("partner").first()


@api_view(["GET"])
def order_list(request):
    """`state` = open(待接單 + 還有沒出的;預設)/ closed / all。待出貨的由舊到新(先訂的先出),其他由新到舊。"""
    _seller(request)
    found = TradeOrder.objects.filter(tenant=request.tenant).select_related("partner")
    state = request.query_params.get("state") or "open"
    if state == "open":
        found = found.filter(status__in=orders.OPEN_STATES).order_by("id")
    elif state == "closed":
        found = found.exclude(status__in=orders.OPEN_STATES).order_by("-id")
    else:
        found = found.order_by("-id")
    partner = _int(request.query_params.get("partner"))
    if partner:
        found = found.filter(partner_id=partner)
    q = (request.query_params.get("q") or "").strip()
    if q:
        found = found.filter(Q(no__icontains=q) | Q(partner__name__icontains=q) | Q(lines__name__icontains=q)
                             | Q(lines__unit__serial_no__icontains=q)).distinct()
    total = found.count()
    limit, offset = _page(request)
    return Response({"total": total, "results": _order_rows(found[offset:offset + limit])})


@api_view(["GET"])
def summary(request):
    """畫面上方的「待出貨 N」。"""
    _seller(request)
    found = TradeOrder.objects.filter(tenant=request.tenant)
    return Response({"pending": found.filter(status=S.PENDING).count(), "to_ship": found.filter(status=S.ACCEPTED).count()})


def _act(request, pk, work):
    _seller(request)
    order = _own(request, pk)
    if order is None:
        return _bad("找不到這張批發單", status.HTTP_404_NOT_FOUND)
    try:
        work(order, request.data if isinstance(request.data, dict) else {})
    except TradeError as exc:
        return _bad(exc)
    return Response(_order_rows([_own(request, pk)])[0])


@api_view(["GET"])
def order_detail(request, pk: int):
    _seller(request)
    order = _own(request, pk)
    if order is None:
        return _bad("找不到這張批發單", status.HTTP_404_NOT_FOUND)
    return Response(_order_rows([order])[0])


@api_view(["POST"])
def order_accept(request, pk: int):
    return _act(request, pk, lambda order, data: orders.accept(order))


@api_view(["POST"])
def order_reject(request, pk: int):
    return _act(request, pk, lambda order, data: orders.reject(order, data.get("reason")))


@api_view(["POST"])
def order_drop(request, pk: int):
    """這一行的幾個不出(`line`、`qty`;沒給 qty = 這一行還沒出的全部)。`line` 沒給 = 整張還沒出的都不出。"""
    def work(order, data):
        if data.get("line") is None:
            return orders.cancel_open(order, by_buyer=False, reason=data.get("reason") or "")
        line = TradeOrderLine.objects.filter(order=order, pk=_int(data.get("line")) or 0).first()
        if line is None:
            raise TradeError("這張單沒有這一行")
        qty = data.get("qty", line.open_qty)
        return orders.drop(order, line, qty, reason=data.get("reason") or "")
    return _act(request, pk, work)


@api_view(["POST"])
def order_ship(request, pk: int):
    def work(order, data):
        store = _store(request, data.get("warehouse"))
        shipping.ship(
            tenant=request.tenant, user=request.user, order=order, request_key=data.get("request_key"), warehouse=store,
            lines=data.get("lines"), shipping_fee=data.get("shipping_fee"), tracking_no=data.get("tracking_no"),
            shipping_method=data.get("shipping_method"))
    return _act(request, pk, work)


@api_view(["POST"])
def shipment_void(request, pk: int):
    _seller(request)
    abilities.require(request.user, abilities.VOID_SALES)
    shipment = TradeShipment.objects.filter(tenant=request.tenant, pk=pk).select_related("order").first()
    if shipment is None:
        return _bad("找不到這一次出貨", status.HTTP_404_NOT_FOUND)
    own = locked_warehouse_id(request.user)
    if own is not None and shipment.warehouse_id != own:
        raise PermissionDenied("不可以取消別家門市的出貨")
    try:
        shipping.void(shipment, request.user)
    except TradeError as exc:
        return _bad(exc)
    return Response(_order_rows([_own(request, shipment.order_id)])[0])


@api_view(["POST"])
def scan(request):
    _seller(request)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        return Response(shipping.scan(request.tenant, _store(request, data.get("warehouse")), data.get("code")))
    except TradeError as exc:
        return _bad(exc)


# ── 收款 ────────────────────────────────────────────────────────────────────
def _ledger_data(partner: TradePartner) -> dict:
    book = payments.ledger(partner)
    return {
        "partner": _partner_data(partner, book),
        "orders": [{"id": r["order"].id, "no": r["order"].no, "placed_at": _when(r["order"].created_at),
                    "owed": _money(r["owed"]), "paid": _money(r["paid"]), "due": _money(r["due"]),
                    "payment_status": payments.status_text(r["owed"], r["paid"])} for r in book["orders"]],
        "payments": [{"id": p.id, "amount": _money(p.amount), "received_on": p.received_on.isoformat(), "method": p.method,
                      "note": p.note, "is_void": p.is_void,
                      "by": p.created_by.get_username() if p.created_by_id else ""}
                     for p in TradePayment.objects.filter(partner=partner).select_related("created_by").order_by("-id")],
    }


@api_view(["GET"])
def partner_ledger(request, pk: int):
    _admin(request)
    partner = TradePartner.objects.filter(tenant=request.tenant, pk=pk).first()
    if partner is None:
        return _bad("找不到這個同行", status.HTTP_404_NOT_FOUND)
    return Response(_ledger_data(partner))


@api_view(["POST"])
def payment_create(request):
    _admin(request)
    data = request.data if isinstance(request.data, dict) else {}
    partner = TradePartner.objects.filter(tenant=request.tenant, pk=_int(data.get("partner")) or 0).first()
    if partner is None:
        return _bad("找不到這個同行", status.HTTP_404_NOT_FOUND)
    day = parse_date(data["received_on"]) if isinstance(data.get("received_on"), str) and data["received_on"] else None
    try:
        if data.get("received_on") and day is None:
            raise TradeError("收款日期不對")
        if day is not None and day > date.today():
            raise TradeError("收款日期不能是未來")
        payments.record(tenant=request.tenant, user=request.user, partner=partner, amount=data.get("amount"),
                        request_key=data.get("request_key"), received_on=day, method=data.get("method"), note=data.get("note"))
    except TradeError as exc:
        return _bad(exc)
    return Response(_ledger_data(partner), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def payment_void(request, pk: int):
    _admin(request)
    payment = TradePayment.objects.filter(tenant=request.tenant, pk=pk).select_related("partner").first()
    if payment is None:
        return _bad("找不到這一筆收款", status.HTTP_404_NOT_FOUND)
    try:
        payments.void(payment)
    except TradeError as exc:
        return _bad(exc)
    return Response(_ledger_data(payment.partner))
