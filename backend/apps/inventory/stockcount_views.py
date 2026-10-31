"""盤點的端點。規則在 `stockcount.py`;這裡只管誰可以做什麼、回什麼給畫面。

誰可以做什麼(owner 2026-10-12:「盤出來的差異要管理員調整與核准」):
- 開盤點單、輸入數量、刷碼、送出、作廢自己還在盤的:要有「盤點作業」那一項。鎖在門市的帳號只能盤自己門市。
- 退回重盤、核准、找回、作廢已經送出的:**只有管理員**。
- **盲盤**:帳上數量、差異、金額、哪幾台少了 / 多了,只有管理員的回應裡有。盤的人只拿得到自己輸入的數字、
  刷到的是什麼、還有幾樣沒盤,以及每一列「開盤之後出了幾個、進了幾個」(提醒重數用,不是帳上總數)。
"""
from decimal import Decimal

from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import ParseError, PermissionDenied, UnsupportedMediaType
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.backup.models import TenantMaintenance

from apps.catalog.models import Product
from apps.core.warehouse_scoping import locked_warehouse_id
from apps.legacy import units as legacy_units
from apps.legacy.units import group_of
from apps.tenants import abilities
from apps.tenants.permissions import is_tenant_admin

from . import stockcount, stockcount_phone
from .identifiers import find_serial_ids
from .models import ProductSerial, StockBalance, StockCount, StockCountPhone, VendorExchange, Warehouse, book_cost

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


def _lost_cost(m):
    """盤虧那一台的金額:標成盤虧時記下來的(`unit_cost`,之後進貨改了平均也不變);還沒核准的照現在帳上的成本
    (`book_cost`:新機是平均成本,跟賣掉記的同一個數字)。"""
    return m.unit_cost if m.unit_cost is not None else book_cost(m.serial)


def _detail(count, user):
    manager = is_tenant_admin(user)
    wh = count.warehouse_id
    lines = list(count.lines.select_related("product").order_by("id"))
    scans = list(count.scans.select_related("serial__product", "product").order_by("id"))
    moved = stockcount.moved_since_start(count, lines)
    out = _summary(count, len(lines), len(scans))
    out["manager"] = manager
    out["left"] = stockcount.left_to_count(count) if count.status == S.COUNTING else 0
    # 帳上有、這張單沒盤到的配件:只有管理員(盲盤)、只在待核准(紅隊:盤的時候看得到清單,會照清單找、照帳打);只列出來、不自動調
    if manager and count.status == S.SUBMITTED:
        out["uncounted_rows"] = stockcount.uncounted(count)
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
    # 手機走動盤點:發出去的 QR Code 與手機(還沒結束的),以及手機刷到、系統不認得的碼(要處理好才能送出)
    now = stockcount_phone.timezone.now()
    out["phones"] = [{"id": ph.id, "label": ph.label, "status": stockcount_phone.status_of(ph, now)}
                     for ph in count.phones.filter(ended_at__isnull=True).select_related("count")]
    out["unknown_rows"] = [{
        "id": u.id, "code": u.code, "times": u.times, "label": u.last_label,
        "product": {"id": u.product_id, "sku": u.product.sku, "name": u.product.name} if u.product_id else None,
        "skipped": u.skipped, "reason": u.reason, "resolved": u.resolved_at is not None,
    } for u in count.unknowns.select_related("product").order_by("id")]
    # 送廠商換貨、還沒換回來的(紅隊:盤點不用刷,但不能從表上消失):盤的人也看得到,才知道那幾台不在店裡是對的
    at_vendor = VendorExchange.objects.filter(
        tenant=count.tenant, warehouse_id=wh, status=VendorExchange.Status.PENDING,
        serial__status=ProductSerial.Status.RMA, serial__warehouse_id=wh,
    ).select_related("serial__product", "supplier").order_by("created_at", "id")
    scope = stockcount.scope_ids(count)
    if scope:
        at_vendor = at_vendor.filter(serial__product__category_id__in=scope)
    today = stockcount_phone.timezone.localdate()
    out["vendor_rows"] = [{
        "id": x.id, "serial_no": x.serial.serial_no, "name": x.serial.product.name,
        "supplier": x.supplier.name if x.supplier_id else "",
        "days": (today - stockcount_phone.timezone.localdate(x.created_at)).days,
    } for x in at_vendor]
    # 送去整理、還沒整理完的(repairs/stock.py):跟廠商換貨一樣不用刷、另外列出來
    from apps.repairs.models import RepairOrder

    refurbing = ProductSerial.objects.filter(
        tenant=count.tenant, warehouse_id=wh, status=ProductSerial.Status.REFURB,
    ).select_related("product").order_by("id")
    if scope:
        refurbing = refurbing.filter(product__category_id__in=scope)
    refurbing = list(refurbing)
    orders = {}
    for o in (RepairOrder.objects.filter(tenant=count.tenant, stock_serial__in=refurbing, is_void=False)
              .exclude(status=RepairOrder.Status.COMPLETED).order_by("id")):
        orders[o.stock_serial_id] = o
    out["refurb_rows"] = [{
        "id": u.id, "serial_no": u.serial_no, "name": u.product.name,
        "repair_no": orders[u.id].no if u.id in orders else "",
        "days": (today - orders[u.id].received_date).days if u.id in orders else None,
    } for u in refurbing]
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
            "cost": _money(_lost_cost(m)), "skipped": m.skipped, "reason": m.reason,
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
        lost = sum((Decimal(_lost_cost(m)) for m in missing
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
    # 畫面輸入前看到的數字(手機在加的時候,電腦按下去不能默默蓋掉手機剛加的);沒帶 = 不核對
    seen = data["seen"] if "seen" in data else stockcount.NOT_SEEN
    if seen is not stockcount.NOT_SEEN and seen is not None and (not isinstance(seen, int) or isinstance(seen, bool)):
        return _bad("送來的內容格式不對")
    try:
        stockcount.set_line(count, product, data.get("counted_qty"), request.user, seen=seen)
    except stockcount.CountError as exc:
        return _bad(exc)
    return Response(_detail(count, request.user))


@api_view(["POST"])
def stock_count_phones(request, pk):
    """手機盤點:產生一張 QR Code {label}。回憑證(只在這一刻看得到)與這張單的內容。"""
    abilities.require(request.user, abilities.STOCK_COUNT)
    count = _get(request, pk)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        phone, token = stockcount_phone.start(count, request.user, data.get("label"))
    except stockcount_phone.PhoneError as exc:
        return _bad(exc)
    out = _detail(count, request.user)
    out["pair"] = {"id": phone.id, "label": phone.label, "token": token, "expires_at": phone.pair_expires_at}
    return Response(out, status=201)


@api_view(["DELETE"])
def stock_count_phone(request, pk, phone_id):
    """電腦按「結束」:那支手機不能再刷。"""
    abilities.require(request.user, abilities.STOCK_COUNT)
    count = _get(request, pk)
    stockcount_phone.end(count, phone_id)
    return Response(_detail(count, request.user))


@api_view(["POST"])
def stock_count_unknowns(request, pk):
    """電腦:刷到系統還沒有的配件、這個帳號不能建商品 → 先記成沒對到的碼 {code, qty}(全站檢視 B3;紅隊:不讓現場店員建主檔,
    也不讓那個碼卡住整張單)。有商品建檔權限的人之後在「沒對到碼」指定 / 建立;還沒處理的照舊不能送出。"""
    abilities.require(request.user, abilities.STOCK_COUNT)
    count = _get(request, pk)
    data = request.data if isinstance(request.data, dict) else {}
    code = str(data.get("code") or "").strip()
    # 系統裡已經有的碼不用先記:直接選它(配件)、或到手機那一格刷(設備)
    hit = Product.objects.filter(tenant=request.tenant).filter(Q(barcode__iexact=code) | Q(sku__iexact=code)).first() if code else None
    if hit is not None:
        return _bad(f"這個碼是「{hit.name}」,直接選它")
    if code and find_serial_ids(request.tenant, code):
        return _bad("這是手機的碼,請在手機那一格刷")
    try:
        stockcount.tally_unknown(count, code, _name(request.user), n=data.get("qty"))
    except stockcount.CountError as exc:
        return _bad(exc)
    return Response(_detail(count, request.user))


@api_view(["POST"])
def stock_count_unknown(request, pk, unknown_id):
    """處理一個沒對到的碼:{product} 指定成這個配件(刷了幾次就加幾個),或 {skip: true, reason} 不入。"""
    abilities.require(request.user, abilities.STOCK_COUNT)
    count = _get(request, pk)
    data = request.data if isinstance(request.data, dict) else {}
    product = None
    if data.get("skip") is not True:
        product = Product.objects.filter(tenant=request.tenant, pk=data.get("product")).first() if str(data.get("product") or "").isdigit() else None
        if product is None:
            return _bad("找不到這個商品")
    try:
        stockcount.resolve_unknown(count, unknown_id, request.user, product=product, reason=data.get("reason") or "")
    except stockcount.CountError as exc:
        return _bad(exc)
    return Response(_detail(count, request.user))


# ── 手機:只認 QR Code 的憑證(不登入)───────────────────────
def _refuse(exc):
    code = getattr(exc, "code", "refused")
    return Response({"detail": str(exc), "code": code}, status=410 if code in ("gone", "expired", "taken") else 400)


def _target(data):
    """手機按「收回 / 這一堆幾個」時看到的最後一下(編號);不是整數就當沒帶。"""
    t = data.get("target")
    return t if isinstance(t, int) and not isinstance(t, bool) else None


def _phone_session(request, claim=False):
    phone = stockcount_phone.session(request.headers.get("X-Pair-Token", ""), request.headers.get("X-Pair-Device", ""), claim=claim)
    # 公司資料還原中:手機這條路也要擋(它不經過登入那一層的維護鎖)
    if TenantMaintenance.objects.filter(tenant_id=phone.tenant_id, active=True).exists():
        raise stockcount_phone.PhoneError("公司資料還原中,暫時不能刷,請稍後再試")
    return phone


@never_cache
@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def count_phone(request, action):
    """claim 掃碼連上 / state 看最近刷了什麼 / tap 刷一個碼 {code, mode} / pile 這一堆幾個 {n} / undo 收回這一下 / finish 結束。"""
    device = request.headers.get("X-Pair-Device", "")
    try:
        data = request.data if isinstance(request.data, dict) else {}
    except (ParseError, UnsupportedMediaType):
        data = {}                        # 手機送來的「連上 / 收回 / 結束」本來就沒有內容
    try:
        if action == "claim" and request.method == "POST":
            phone = _phone_session(request, claim=True)
        elif action == "state" and request.method == "GET":
            phone = _phone_session(request)
        elif action == "tap" and request.method == "POST":
            phone = _phone_session(request)
            stockcount_phone.tap(phone, device, data.get("code"), str(data.get("mode") or ""), data.get("op"))
        elif action == "pile" and request.method == "POST":
            phone = _phone_session(request)
            stockcount_phone.pile(phone, device, data.get("n"), data.get("op"), _target(data))
        elif action == "undo" and request.method == "POST":
            phone = _phone_session(request)
            stockcount_phone.undo(phone, device, data.get("op"), _target(data))
        elif action == "finish" and request.method == "POST":
            phone = _phone_session(request)
            stockcount_phone.finish(phone, device)
            return Response({"detail": "已結束"})
        else:
            raise Http404
        phone = StockCountPhone.objects.select_related("count", "count__warehouse").get(pk=phone.pk)
        # 做事的這段時間電腦按了結束、單子送出了:這張單的內容不回給它
        if phone.ended_at or phone.count.status != S.COUNTING:
            raise stockcount_phone.PhoneError("這支手機的盤點已經結束", "gone")
        return Response(stockcount_phone.phone_view(phone))
    except stockcount_phone.PhoneError as exc:
        return _refuse(exc)


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
