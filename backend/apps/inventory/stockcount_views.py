"""盤點的端點。規則在 `stockcount.py`;這裡只管誰可以做什麼、回什麼給畫面。

誰可以做什麼(owner 2026-10-12:「盤出來的差異要管理員調整與核准」):
- 開盤點單、輸入數量、刷碼、送出、作廢自己還在盤的:要有「盤點作業」那一項。鎖在門市的帳號只能盤自己門市。
- 退回重盤、核准、找回、作廢已經送出的:**只有管理員**。
- **盲盤**:帳上數量、差異、金額、哪幾台少了 / 多了,只有管理員的回應裡有。盤的人只拿得到自己輸入的數字、
  刷到的是什麼、還有幾樣沒盤,以及每一列「開盤之後出了幾個、進了幾個」(提醒重數用,不是帳上總數)。
"""
from decimal import Decimal

from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.core.warehouse_scoping import locked_warehouse_id
from apps.legacy import units as legacy_units
from apps.legacy.units import group_of
from apps.tenants import abilities
from apps.tenants.permissions import is_tenant_admin

from . import stockcount
from .models import ProductSerial, StockBalance, StockCount, Warehouse

S = StockCount.Status
_CENT = Decimal("0.01")
LIST_MAX = 200


def _bad(exc):
    return Response({"detail": str(exc)}, status=400)


def _money(value) -> str:
    return str(Decimal(value or 0).quantize(_CENT))


def _counts(request):
    """這個帳號看得到的盤點單(鎖在門市的只有自己門市)。"""
    qs = StockCount.objects.filter(tenant=request.tenant)
    own = locked_warehouse_id(request.user)
    if own is not None:
        qs = qs.filter(warehouse_id=own)
    return qs


def _get(request, pk):
    return get_object_or_404(_counts(request).select_related("warehouse", "created_by"), pk=pk)


def _managers_only(user):
    if not is_tenant_admin(user):
        raise PermissionDenied("盤點的核准、退回、找回只有管理員可以做")


def _name(user) -> str:
    return user.get_username() if user else ""


def _summary(count, lines=None, scans=None):
    return {
        "id": count.id,
        "no": count.no,
        "warehouse": {"id": count.warehouse_id, "name": count.warehouse.name},
        "categories": [s.category.name for s in count.scope.all()],
        "status": count.status,
        "status_label": count.get_status_display(),
        "note": count.note,
        "phones_done": count.phones_done,
        "created_at": count.created_at,
        "created_by": _name(count.created_by),
        "submitted_at": count.submitted_at,
        "approved_at": count.approved_at,
        "lines": count.lines.count() if lines is None else lines,
        "scans": count.scans.count() if scans is None else scans,
    }


def _detail(count, user):
    manager = is_tenant_admin(user)
    wh = count.warehouse_id
    lines = list(count.lines.select_related("product").order_by("id"))
    scans = list(count.scans.select_related("serial__product", "product").order_by("id"))
    moved = stockcount.moved_since_start(count, lines)
    out = _summary(count, len(lines), len(scans))
    out["manager"] = manager
    out["left"] = stockcount.left_to_count(count) if count.status == S.COUNTING else 0
    costs = {}
    if manager:
        costs = dict(StockBalance.objects.filter(
            tenant=count.tenant, warehouse_id=wh, product_id__in=[line.product_id for line in lines],
        ).values_list("product_id", "weighted_avg_cost"))
    rows, total = [], Decimal("0")
    for line in lines:
        gone, came = moved.get(line.pk, (0, 0))
        row = {
            "id": line.id,
            "product": {"id": line.product_id, "sku": line.product.sku, "name": line.product.name},
            "counted_qty": line.counted_qty,
            "counted_at": line.counted_at,
            # 開盤之後到輸入那一刻出了幾個、進了幾個(有數字 = 數完到輸入之間有動過,要重數)
            "moved_out": gone,
            "moved_in": came,
        }
        if manager:
            diff = line.counted_qty - line.book_qty
            approved = count.status == S.APPROVED
            cost = line.unit_cost if line.unit_cost is not None else (costs.get(line.product_id) or line.product.weighted_avg_cost or 0)
            qty = (line.adjust_qty or 0) if approved else diff
            row.update({
                "book_qty": line.book_qty, "diff": diff,
                "adjust_qty": line.adjust_qty if approved else None,
                "skipped": line.skipped, "reason": line.reason,
                "unit_cost": _money(cost), "amount": _money(Decimal(cost) * qty),
            })
            total += Decimal(cost) * qty
        rows.append(row)
    out["line_rows"] = rows
    states = dict(ProductSerial.Status.choices)
    out["scan_rows"] = [{
        "id": s.id, "code": s.code, "known": s.serial_id is not None,
        # 系統不認得、舊系統的機器清單對得到的:舊品名(盤的人知道刷到的是哪一台)
        "name": s.serial.product.name if s.serial_id else s.old_name,
        **({"here": s.here, "state": states.get(s.state, "")} if manager else {}),
    } for s in scans]
    if manager:
        missing = list(count.missing.select_related("serial__product").order_by("id"))
        out["missing_rows"] = [{
            "id": m.id, "serial_no": m.serial.serial_no, "name": m.serial.product.name,
            "cost": _money(m.serial.purchase_unit_cost), "skipped": m.skipped, "reason": m.reason,
            "applied": m.applied, "found": m.found_at is not None,
            # 現在帳上還在不在這家門市在庫(送出之後賣掉 / 調走的,核准時不會標成盤虧)
            "still_here": m.serial.status == ProductSerial.Status.IN_STOCK and m.serial.warehouse_id == wh,
        } for m in missing]
        # 多出來的:刷到的那一刻帳上不是這家門市在庫(已售、在別家、系統不認得)。只列出來,不自動處理
        out["extra_rows"] = [{
            "id": s.id, "code": s.code, "name": s.serial.product.name if s.serial_id else "",
            "state": states.get(s.state, "") if s.serial_id else "",
        } for s in scans if not s.here and s.serial_id]
        # 系統不認得的:第一次盤點入庫要指定品號與成本(舊系統的機器清單對得到的先帶出來)
        unknown = [s for s in scans if s.serial_id is None]
        suggested = stockcount.suggested_products(count.tenant, [s.old_code for s in unknown])
        out["new_rows"] = []
        for s in unknown:
            chosen = s.product or (None if count.status == S.APPROVED else suggested.get(s.old_code))
            out["new_rows"].append({
                "id": s.id, "code": s.code, "old_code": s.old_code, "old_name": s.old_name,
                "group": group_of(s.old_name) if s.old_name else "",
                "old_cost": _money(s.old_cost) if s.old_cost is not None else None,
                "old_price": _money(s.old_price) if s.old_price is not None else None,
                "product": ({"id": chosen.id, "sku": chosen.sku, "name": chosen.name,
                             "unit": chosen.tracks_unit_condition} if chosen else None),
                "unit_cost": _money(s.unit_cost) if s.unit_cost is not None else None,
                "unit_price": _money(s.unit_price) if s.unit_price is not None else None,
                "skipped": s.skipped, "reason": s.reason, "added": s.added_id is not None,
            })
        lost = sum((Decimal(m.serial.purchase_unit_cost or 0) for m in missing
                    if (m.applied and m.found_at is None) or (count.status == S.SUBMITTED and not m.skipped)), Decimal("0"))
        # 第一次入庫的:核准之後是入了的那幾台;還沒核准是「照現在的樣子核准」會入的(先帶出品號、有舊成本的)
        added = sum((Decimal(r["unit_cost"] if count.status == S.APPROVED else r["old_cost"] or 0)
                     for r in out["new_rows"]
                     if (r["added"] if count.status == S.APPROVED else (r["product"] and r["old_cost"] is not None))),
                    Decimal("0"))
        phones = added - lost
        out["amounts"] = {"lines": _money(total), "phones": _money(phones), "total": _money(total + phones)}
    return out


@api_view(["GET", "POST"])
def stock_counts(request):
    """GET 盤點單清單(新的在前);POST 開一張 {warehouse, categories: [類別編號], note}。"""
    abilities.require(request.user, abilities.STOCK_COUNT)
    if request.method == "GET":
        qs = (_counts(request).select_related("warehouse", "created_by").prefetch_related("scope__category")
              .annotate(n_lines=Count("lines", distinct=True), n_scans=Count("scans", distinct=True)))
        return Response({"results": [_summary(c, c.n_lines, c.n_scans) for c in qs[:LIST_MAX]]})
    data = request.data if isinstance(request.data, dict) else {}
    own = locked_warehouse_id(request.user)
    warehouse_id = own if own is not None else data.get("warehouse")
    warehouse = Warehouse.objects.filter(tenant=request.tenant, pk=warehouse_id).first() if str(warehouse_id or "").isdigit() else None
    if warehouse is None:
        return _bad("請選門市")
    categories = data.get("categories") or []
    if not isinstance(categories, list) or any(not str(c).isdigit() for c in categories):
        return _bad("類別格式不對")
    try:
        count = stockcount.open_count(request.tenant, warehouse, categories, request.user, str(data.get("note") or ""))
    except stockcount.CountError as exc:
        return _bad(exc)
    return Response(_detail(count, request.user), status=201)


@api_view(["GET"])
def stock_count(request, pk):
    abilities.require(request.user, abilities.STOCK_COUNT)
    return Response(_detail(_get(request, pk), request.user))


@api_view(["POST"])
def stock_count_lines(request, pk):
    """配件:這個商品數到幾個 {product, counted_qty}(重新輸入 = 換掉)。"""
    abilities.require(request.user, abilities.STOCK_COUNT)
    count = _get(request, pk)
    data = request.data if isinstance(request.data, dict) else {}
    product = Product.objects.filter(tenant=request.tenant, pk=data.get("product")).first() if str(data.get("product") or "").isdigit() else None
    if product is None:
        return _bad("找不到這個商品")
    try:
        stockcount.set_line(count, product, data.get("counted_qty"), request.user)
    except stockcount.CountError as exc:
        return _bad(exc)
    return Response(_detail(count, request.user))


@api_view(["DELETE"])
def stock_count_line(request, pk, line_id):
    abilities.require(request.user, abilities.STOCK_COUNT)
    count = _get(request, pk)
    try:
        stockcount.remove_line(count, line_id)
    except stockcount.CountError as exc:
        return _bad(exc)
    return Response(_detail(count, request.user))


@api_view(["POST"])
def stock_count_scans(request, pk):
    """手機:刷一個碼 {code}。"""
    abilities.require(request.user, abilities.STOCK_COUNT)
    count = _get(request, pk)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        stockcount.scan(count, data.get("code"), request.user)
    except stockcount.CountError as exc:
        return _bad(exc)
    return Response(_detail(count, request.user))


@api_view(["DELETE"])
def stock_count_scan(request, pk, scan_id):
    abilities.require(request.user, abilities.STOCK_COUNT)
    count = _get(request, pk)
    try:
        stockcount.remove_scan(count, scan_id)
    except stockcount.CountError as exc:
        return _bad(exc)
    return Response(_detail(count, request.user))


@api_view(["POST"])
def stock_count_action(request, pk, action):
    """送出 submit {phones_done} / 作廢 void / 退回 return / 核准 approve {lines, missing, extras}。後兩個與作廢已送出的只有管理員。"""
    abilities.require(request.user, abilities.STOCK_COUNT)
    count = _get(request, pk)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        if action == "submit":
            stockcount.submit(count, request.user, phones_done=data.get("phones_done") is True)
        elif action == "void":
            if count.status != S.COUNTING:
                _managers_only(request.user)
            # 上面那一下是「先講清楚」;真正擋的是 void() 鎖到這張單之後再看一次(同時有人送出的那一瞬間)
            stockcount.void(count, by_manager=is_tenant_admin(request.user))
        elif action == "return":
            _managers_only(request.user)
            stockcount.give_back(count)
        elif action == "approve":
            _managers_only(request.user)
            lines, missing, extras = data.get("lines") or {}, data.get("missing") or {}, data.get("extras") or {}
            if not isinstance(lines, dict) or not isinstance(missing, dict) or not isinstance(extras, dict):
                return _bad("送來的內容格式不對")
            stockcount.approve(count, request.user, lines=lines, missing=missing, extras=extras)
        else:
            return Response({"detail": "沒有這個動作"}, status=404)
    except stockcount.CountError as exc:
        return _bad(exc)
    return Response(_detail(count, request.user))


@api_view(["POST"])
def stock_count_found(request, pk, missing_id):
    """核准之後手機找到了(管理員):那一台回到在庫。"""
    abilities.require(request.user, abilities.STOCK_COUNT)
    _managers_only(request.user)
    count = _get(request, pk)
    try:
        stockcount.found(count, missing_id, request.user)
    except stockcount.CountError as exc:
        return _bad(exc)
    return Response(_detail(count, request.user))


OLD_UNITS_MAX = 2000


@api_view(["GET"])
def stock_count_old_units(request):
    """舊系統的機器清單上有、新系統還沒入庫的(管理員;第一次盤點入庫時看哪幾台還沒刷到)。只有數字與舊系統的字,沒有成本。"""
    abilities.require(request.user, abilities.STOCK_COUNT)
    _managers_only(request.user)
    left = legacy_units.not_in_yet(request.tenant)
    stores: dict[str, int] = {}
    for u in left:
        stores[u.store_raw] = stores.get(u.store_raw, 0) + 1
    return Response({
        "total": len(left),
        "stores": [{"store": k or "(沒寫)", "count": v} for k, v in stores.items()],
        "rows": [{"code": u.code_raw, "old_code": u.product_code_raw, "old_name": u.product_name_raw,
                  "store": u.store_raw, "purchased_on": u.purchased_on} for u in left[:OLD_UNITS_MAX]],
    })
