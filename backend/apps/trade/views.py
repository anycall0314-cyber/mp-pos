"""批發(賣家那一半)的 API。一律只看自己公司。

- 批發單、刷機找單、接單 / 拒絕、不出、出貨、中古機上架 / 下架 → 要有員工帳號的「批發出貨」。鎖在門市的帳號只能從自己門市出貨。
- 取消出貨(會作廢那張銷貨單)→ 另外要有「作廢銷貨單」。
- 批發設定、往來的同行與代碼、商品開不開放與固定批發價、收款 → 只有管理員(價錢與帳)。
買家那一側不在這裡:平台內走 `vendor_orders` 的串接器、對外走金鑰,兩邊最後都是 `api.handle`。
"""
from datetime import date

from django.db import transaction
from django.db.models import Count, Exists, Max, Min, OuterRef, Q
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

from . import keys, listing, orders, partners, payments, pricing, shipping
from .base import TradeError, setting_of
from .models import (
    TradeInvite, TradeOrder, TradeOrderLine, TradePartner, TradePayment, TradePriceChange, TradePriceChangeUnit, TradePriceRule, TradeProduct,
    TradeSetting, TradeShipment, TradeShipmentLine, TradeUnit,
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
        "id": partner.id, "name": partner.name, "kind": partner.kind, "status": partner.status, "contact": partner.contact,
        # 對外的同行:金鑰的前幾碼(原文只在發的那一次看得到)、最後一次用是什麼時候
        "key_hint": getattr(getattr(partner, "key", None), "hint", ""),
        "key_used_at": _when(partner.key.last_used_at) if getattr(partner, "key", None) and partner.key.last_used_at else "",
        "status_label": partner.get_status_display(), "percent": partner.percent, "terms": partner.terms, "note": partner.note,
        "owed": _money(book["owed"]), "received": _money(book["received"]), "due": _money(book["due"]),
        "credit": _money(book["credit"]),
    }


@api_view(["GET"])
def partner_list(request):
    _admin(request)
    rows = TradePartner.objects.filter(tenant=request.tenant).select_related("key").order_by("status", "id")
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
def external_create(request):
    """建一個對外的同行(不在這套 POS 上的系統)並發金鑰。**金鑰原文只在這一次的回應裡**。"""
    _admin(request)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        partner, raw = keys.create_external(request.tenant, request.user, name=data.get("name"), contact=data.get("contact"),
                                            percent=data.get("percent"), terms=data.get("terms"))
    except TradeError as exc:
        return _bad(exc)
    return Response({"partner": _partner_data(partner), "key": raw, "base": request.build_absolute_uri("/api/trade/v2")},
                    status=status.HTTP_201_CREATED)


@api_view(["POST"])
def partner_key(request, pk: int):
    """換一把金鑰(舊的立刻失效)。新的原文只在這一次的回應裡。"""
    _admin(request)
    partner = TradePartner.objects.filter(tenant=request.tenant, pk=pk).first()
    if partner is None:
        return _bad("找不到這個同行", status.HTTP_404_NOT_FOUND)
    try:
        raw = keys.rotate(partner, request.user)
    except TradeError as exc:
        return _bad(exc)
    partner = TradePartner.objects.select_related("key").get(pk=partner.pk)
    return Response({"partner": _partner_data(partner), "key": raw, "base": request.build_absolute_uri("/api/trade/v2")})


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
# 一個型號的每一台要一次列得出來(同型號在庫幾百台、整群篩、整群定價;owner 2026-10-14)
UNIT_PAGE_MAX = 2000


def _units_in_stock(request):
    """這個人看得到的、在庫的一台一筆商品(中古機 / 已拆封),帶著「有沒有被訂著」「有沒有上架」。鎖門市的人只有自己那一間。"""
    held = TradeOrderLine.objects.filter(unit_id=OuterRef("pk"), holding=True)
    listed = TradeUnit.objects.filter(serial_id=OuterRef("pk"), is_listed=True)
    rows = (ProductSerial.objects.filter(tenant=request.tenant, status=ProductSerial.Status.IN_STOCK, product__requires_serial=True,
                                         product__is_virtual=False)
            .filter(Q(product__is_secondhand=True) | Q(product__condition__tracks_unit_condition=True))
            .annotate(is_held=Exists(held), is_on=Exists(listed)))
    store = locked_warehouse_id(request.user) or _int(request.query_params.get("warehouse"))
    if store:
        rows = rows.filter(warehouse_id=store)
    return rows


@api_view(["GET"])
def unit_models(request):
    """中古機照型號算:每一個型號在庫幾台、其中沒上架 / 上架中 / 被訂走各幾台。上架那一頁先看這個,再點進一個型號。"""
    _seller(request)
    for_sale = Q(is_on=True, is_held=False)
    found = (_units_in_stock(request).values("product_id", "product__name", "product__sku")
             .annotate(total=Count("id"), listed=Count("id", filter=for_sale), held=Count("id", filter=Q(is_held=True)),
                       low=Min("trade_unit__price", filter=for_sale), high=Max("trade_unit__price", filter=for_sale),
                       own=Count("id", filter=for_sale & Q(trade_unit__own_price=True)))
             .order_by("product__name", "product_id"))
    found = list(found)
    rules = pricing.rules_of(request.tenant, [row["product_id"] for row in found])
    return Response({"results": [{
        "product": row["product_id"], "name": row["product__name"], "sku": row["product__sku"], "total": row["total"],
        "unlisted": row["total"] - row["listed"] - row["held"], "listed": row["listed"], "held": row["held"],
        # 上架中的那幾台現在賣多少到多少;其中獨立定價的幾台(價目怎麼改都不動的那幾台,要人自己記得看)
        "price_low": _money(row["low"]), "price_high": _money(row["high"]), "own": row["own"],
        # 這個型號的價目表(行情變了在型號清單上就改得到)
        "rules": _rules_data(request.tenant, row["product_id"], rules[row["product_id"]]) if rules[row["product_id"]] else [],
    } for row in found]})


def _rules_data(tenant, product_id, rules=None) -> list[dict]:
    """這個型號價目表的每一格,與現在用它的有幾台(全公司在庫的;不看畫面上的門市與狀態)。"""
    rules = list(TradePriceRule.objects.filter(tenant=tenant, product_id=product_id)) if rules is None else rules
    counts = pricing.followers(tenant, product_id, rules)
    rules = sorted(rules, key=lambda r: (pricing.GRADE_ORDER.get(r.grade, 9), -r.battery_max, -r.battery_min, r.noted))
    return [{"id": r.id, "product": product_id, "grade": r.grade, "battery_min": r.battery_min, "battery_max": r.battery_max, "noted": r.noted,
             "price": _money(r.price), "text": pricing.text_of(r), "followers": counts[r.id]} for r in rules]


@api_view(["GET"])
def unit_list(request):
    """在庫的一台一筆商品(中古機 / 已拆封)與它們的上架狀況。`state` = unlisted(預設)/ listed / held / all;`product` = 只看一個型號。"""
    _seller(request)
    tenant = request.tenant
    rows = _units_in_stock(request)
    product = _int(request.query_params.get("product"))
    if product:
        rows = rows.filter(product_id=product)
    q = (request.query_params.get("q") or "").strip()
    if q:
        rows = rows.filter(Q(product__name__icontains=q) | Q(serial_no__icontains=q) | Q(identifiers__value__icontains=q)).distinct()
    state = request.query_params.get("state") or "unlisted"
    if state == "unlisted":
        rows = rows.filter(is_on=False, is_held=False)
    elif state == "listed":
        rows = rows.filter(is_on=True, is_held=False)
    elif state == "held":
        rows = rows.filter(is_held=True)
    total = rows.count()
    limit = min(max(_int(request.query_params.get("limit")) or PAGE, 1), UNIT_PAGE_MAX)
    offset = _int(request.query_params.get("offset")) or 0
    page = list(rows.select_related("product__condition", "warehouse").prefetch_related("identifiers")
                .order_by("-id")[offset:offset + limit])
    units = {u.serial_id: u for u in TradeUnit.objects.filter(serial__in=page)}
    holds = {line.unit_id: line for line in TradeOrderLine.objects.filter(unit__in=page, holding=True).select_related("order__partner")}
    setting = setting_of(tenant)
    rules = pricing.rules_of(tenant, {serial.product_id for serial in page})
    out = []
    for serial in page:
        unit, hold = units.get(serial.id), holds.get(serial.id)
        rule = pricing.best(rules.get(serial.product_id, []), serial)
        out.append({
            "serial": serial.id, "serial_no": serial.serial_no, **codes_of(serial),
            "product": serial.product_id, "name": serial.product.name, "sku": serial.product.sku,
            "warehouse": serial.warehouse_id, "warehouse_name": serial.warehouse.name if serial.warehouse_id else "",
            "grade": serial.condition_grade, "battery": serial.battery_health, "note": serial.condition_note,
            # auto_price = 沒有人指定價的時候它會賣多少(價目表上符合它的那一格 → 沒有才是設定的通則)
            "retail_price": _money(listing.retail_price(serial)),
            "auto_price": _money(rule.price if rule is not None else listing.auto_price(setting, serial)),
            "is_listed": bool(unit and unit.is_listed), "price": _money(unit.price) if unit else None,
            # own = 獨立定價(價目怎麼改都不動它);rule = 價目表上符合它的最細的那一格(沒有獨立定價的話用的就是這一格的價)
            "own": bool(unit and unit.own_price), "rule": rule.id if rule is not None else None,
            "held_by": None if hold is None else {"order": hold.order_id, "order_no": hold.order.no, "partner": hold.order.partner.name},
        })
    data = {"total": total, "results": out}
    if product:
        data["rules"] = _rules_data(tenant, product)
    else:
        # 全部型號那個入口也要帶(複審 P1:不帶的話勾回「跟價目」那一台,畫面上還是舊的價,存下去卻是價目的價)。台數只在看一個型號時算
        data["rules"] = [{"id": r.id, "product": pid, "grade": r.grade, "battery_min": r.battery_min, "battery_max": r.battery_max, "noted": r.noted,
                          "price": _money(r.price), "text": pricing.text_of(r), "followers": None}
                         for pid, found in rules.items() for r in found]
    return Response(data)


def _seen(request):
    """畫面送出時說它看的是哪個型號 / 哪一間門市(沒說的不查)。"""
    data = request.data if isinstance(request.data, dict) else {}
    return {"product": _int(data.get("product")), "warehouse": _int(data.get("warehouse"))}


@api_view(["POST"])
def unit_put_on(request):
    _seller(request)
    try:
        data = request.data if isinstance(request.data, dict) else {}
        done = listing.put_on(request.tenant, request.user, data.get("rows"), store=locked_warehouse_id(request.user), seen=_seen(request),
                              cell=data.get("cell"), cell_price=data.get("cell_price"))
    except TradeError as exc:
        return _bad(exc)
    return Response({"listed": len(done)})


@api_view(["POST"])
def unit_take_off(request):
    _seller(request)
    try:
        done = listing.take_off(request.tenant, request.user, request.data.get("serials") if isinstance(request.data, dict) else None,
                                store=locked_warehouse_id(request.user), seen=_seen(request))
    except TradeError as exc:
        return _bad(exc)
    return Response({"unlisted": done})


@api_view(["POST"])
def unit_rules(request):
    """一次改好幾格價目的價(`cells` = [{id, price}])。符合那幾格、沒有獨立定價的在庫機器跟著變。"""
    _seller(request)
    try:
        changed = listing.set_cells(request.tenant, request.user, request.data.get("cells") if isinstance(request.data, dict) else None,
                                    store=locked_warehouse_id(request.user))
    except TradeError as exc:
        return _bad(exc)
    return Response({"changed": changed})


@api_view(["POST"])
def unit_rule_drop(request, pk: int):
    """刪掉價目表的一格。原本用它的改用下一格的價;沒有下一格的維持現在的價。"""
    _seller(request)
    try:
        changed = listing.drop_cell(request.tenant, request.user, pk, store=locked_warehouse_id(request.user))
    except TradeError as exc:
        return _bad(exc, exc.status)
    return Response({"changed": changed})


@api_view(["GET"])
def unit_changes(request):
    """改價紀錄:一個型號每一次改價(新的在前)。`q` = 序號裡的字 → 只列動到那一台的,並帶出那一台從多少變多少。"""
    _seller(request)
    product = _int(request.query_params.get("product"))
    found = TradePriceChange.objects.filter(tenant=request.tenant).select_related("by", "product")
    if product:
        found = found.filter(product_id=product)
    q = (request.query_params.get("q") or "").strip()
    if q:
        found = found.filter(Q(units__serial__serial_no__icontains=q) | Q(units__serial__identifiers__value__icontains=q)).distinct()
    total = found.count()
    limit, offset = _page(request)
    page = list(found.order_by("-id")[offset:offset + limit])
    hits = {}
    if q and page:
        for row in (TradePriceChangeUnit.objects.filter(change__in=page)
                    .filter(Q(serial__serial_no__icontains=q) | Q(serial__identifiers__value__icontains=q))
                    .select_related("serial").distinct()):
            hits.setdefault(row.change_id, []).append(
                {"serial_no": row.serial.serial_no, "old_price": _money(row.old_price), "new_price": _money(row.new_price)})
    return Response({"total": total, "results": [{
        "id": c.id, "at": _when(c.created_at), "by": (c.by.get_full_name() or c.by.username) if c.by_id else "",
        "product": c.product_id, "name": c.product.name, "what": c.what, "what_label": c.get_what_display(), "scope": c.scope, "count": c.count,
        "old_low": _money(c.old_low), "old_high": _money(c.old_high), "new_low": _money(c.new_low), "new_high": _money(c.new_high),
        "units": hits.get(c.id, []),
    } for c in page]})


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
        if order.partner_id not in books:          # 一個同行算一次(同一頁常常是同一個同行的好幾張單)
            books[order.partner_id] = payments.ledger(order.partner)
        book = books[order.partner_id]
        money = next((r for r in book["orders"] if r["order"].id == order.id), None) or {"owed": 0, "paid": 0, "due": 0}
        mine = lines.get(order.id, [])
        out.append({
            "id": order.id, "no": order.no, "partner": order.partner_id, "partner_name": order.partner.name,
            # 這個同行是誰:平台內 / 對外(紅隊:外面今天才接上的,跟月結的老同行在同一張清單上要分得出來)、怎麼聯絡、
            # 他已經給了、還沒被出過貨的單用掉的錢(先收款再出貨的,出貨的人看這個數)
            "partner_kind": order.partner.kind, "partner_contact": order.partner.contact, "credit": _money(book["credit"]),
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
