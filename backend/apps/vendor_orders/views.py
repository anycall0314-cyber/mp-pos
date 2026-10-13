"""廠商叫貨的 API。一律只看自己公司;鎖在門市的帳號只能用、只看得到自己門市的。
每一支都要講是哪一家廠商(`vendor` = 平台名單上的代碼);名單上只有一家在合作時可以不講(就是那一家)。

- 叫貨串接(金鑰與預設):看 → 登入的人(自己門市);改 → 只有管理員。**金鑰原文任何回應都沒有**;前幾碼只有管理員看得到。
- 叫貨(看廠商的商品與進價、送出、再送一次)→ 要有員工帳號的「廠商叫貨」。看叫貨單清單照舊。
  另外每家門市 × 每家廠商一格「誰能叫貨」(`clerk_ordering`):關掉的那一家,店員看不到它的商品與進價、不能叫、不能再送(管理員照舊)。
- 到貨入庫(看這張單到了什麼、入庫、把不是從這裡叫的單認進來、記到貨問題)→ 要有「進貨入庫」(它開出來的就是進貨單)。
- 品名連連看(廠商的品項 ↔ 店內商品;看、連、改、解除)→ 有「廠商叫貨」或「進貨入庫」其中一項就可以(owner:店員都可以)。不帶價錢。
- 更新進度(跟廠商要最新狀況,順便列出「不是從 POS 叫的」單)→ 同樣是其中一項就可以(2026-10-10 起;原本只看「廠商叫貨」):
  收貨的人不一定是叫貨的人 —— 用 LINE 叫的、廠商直接出的貨,要先列得出來才能認進來入庫,而認進來與入庫看的本來就是「進貨入庫」。
- **半自動的廠商**(`manual.py`;沒有可以接的系統):開通 = 管理員在串接上按「開通」(沒有金鑰);商品清單 = 平台的價目表;叫貨單 POS 自己成立;
  「已貼給廠商」「取消 / 恢復」→ 要有「廠商叫貨」;「進度備註」→ 兩項有一項;到貨入庫照舊看「進貨入庫」。沒有 再送一次 / 把外面的單認進來;更新進度不問任何系統。
- **送進廠商的下單網站**(`handoff.py`;現在只有 kcimos):發代碼(`…/handoff/`)與把待確認確認掉(`…/handoff/resolve/`)→ 要有「廠商叫貨」;
  小幫手自己用的那幾支不用登入、認代碼,在 `handoff_views.py`。解除帳號綁定 → 只有管理員(串接的 `forget_site_account`)。
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

from . import handoff, manual, mapping, receiving, secrets, services, standard, vendors
from .models import Vendor, VendorCategory, VendorLink, VendorOrder, VendorSecret

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


def _vendor(request, raw, *, active=True, open_now=None) -> Vendor:
    """這個請求指的是哪一家廠商。沒講:這家公司看得到的名單上只有一家在合作就是它,不然要講。
    `active` = 要還在合作中的(看商品、叫貨、貼金鑰);查紀錄、更新進度、到貨入庫不要求。

    **只給指定公司的廠商**(`vendors.open_to`):名單以外的公司一律當成「沒有這一家」—— 講的話跟代碼打錯一模一樣,不透露有這家廠商。
    例外:這家公司以前就設定過它(後來才被收回的)→ 已經叫的單照樣查得到、入得了庫(`active=False` 的那幾條路),新的事不能做。
    `open_now` = 一定要現在還看得到(預設跟 `active` 一樣):會列出廠商**現在**的品項與價目的路(看商品、連品名)都要 —— 被收回的公司不能再看到之後才有的品項與進價。
    **先看這家公司看不看得到,才看廠商有沒有停用**:順序反過來的話「『某某』已經停用」那一句會把名單以外的廠商名字講出去。"""
    if raw in (None, ""):
        only = [v for v in Vendor.objects.filter(is_active=True) if vendors.open_to(v, request.tenant)][:2]
        if len(only) != 1:
            raise services.VendorError("要指定廠商")
        return only[0]
    if not isinstance(raw, str):
        raise services.VendorError("廠商不對")
    vendor = services.vendor_of(raw)             # 只看名單上有沒有;停用留到後面看
    if not vendors.open_to(vendor, request.tenant):
        had = VendorLink.objects.filter(tenant=request.tenant, provider=vendor.code).exists()
        if (active if open_now is None else open_now) or not had:
            raise services.VendorError(f"廠商名單上沒有「{raw}」這一家,請平台管理員處理")
    return services.vendor_of(raw, active=active)


def _link(request, store, vendor):
    return VendorLink.objects.filter(tenant=request.tenant, provider=vendor.code, warehouse=store).first()


def _need_link(request, store, vendor):
    link = _link(request, store, vendor)
    if manual.is_manual(vendor):
        manual.need_open(link, vendor)          # 半自動的沒有金鑰:看的是管理員開通了沒
    elif link is None:
        raise services.VendorError(f"這家門市還沒有設定{vendor.name}的金鑰,請管理員到「系統設定 → 叫貨串接」設定")
    return link


def _may_order(request, link) -> None:
    """這家門市 × 這家廠商設成「只限管理」時,店員不能看它的商品與進價、不能叫、不能再送。"""
    if link is not None and not link.clerk_ordering and not is_tenant_admin(request.user):
        raise PermissionDenied(f"這家門市設定只有管理員可以跟{vendors.name_of(link.provider)}叫貨")


def _needs_either(request) -> None:
    """叫貨的人與收貨的人都用得到的(品名連連看、更新進度):「廠商叫貨」「進貨入庫」有一項就可以。"""
    if not (abilities.can(request.user, abilities.VENDOR_ORDER) or abilities.can(request.user, abilities.PURCHASE)):
        raise PermissionDenied("這個帳號沒有開「廠商叫貨」或「進貨入庫」")


def _money(value):
    return None if value is None else str(value)


def _link_data(store, vendor, link, hints, manager) -> dict:
    """`hints` = {串接編號: (前幾碼, 是不是沙盒)},只列有金鑰的。"""
    data = {
        "warehouse": store.id,
        "warehouse_name": store.name,
        "provider": vendor.code,
        "provider_label": vendor.name,
        # 這家廠商掛在哪些類別(只用來篩廠商);停用的廠商不能叫新的貨,已經叫的單照樣看得到
        "categories": [c.id for c in vendor.categories.all()],
        "vendor_active": vendor.is_active,
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
        # 這家門市的店員能不能跟這家叫貨(管理員一律可以)。大家都看得到:畫面要知道哪幾家對這個人是灰的
        "clerk_ordering": link.clerk_ordering if link else True,
        # 怎麼接:半自動的沒有金鑰,看的是「開通」;`ready` = 這家門市現在可以跟這家往來了(全自動 = 有金鑰,半自動 = 開通了)
        "manual": manual.is_manual(vendor),
        "opened": bool(link and link.opened),
        "ready": bool(link and (link.opened if manual.is_manual(vendor) else link.id in hints)),
        "contact": vendor.contact,
        "has_key": bool(link and link.id in hints),
        # 廠商說這把是測試(沙盒)金鑰:用它叫的是測試單。大家都看得到(叫貨的人要知道現在是不是玩真的)
        "sandbox": hints[link.id][1] if link and link.id in hints else None,
        "choices": {"payment_method": list(standard.PAYMENT_METHODS), "delivery_method": list(standard.DELIVERY_METHODS),
                    "invoice_type": list(standard.INVOICE_TYPES)},
        # 這家廠商有沒有下單網站可以自動送單(`handoff.py`);`bound` = 這家門市已經綁了那個網站的帳號(第一次送單時綁的)
        "site": _site_data(vendor, link),
    }
    if manager:
        data["key_hint"] = hints[link.id][0] if link and link.id in hints else ""
    return data


def _site_data(vendor, link) -> dict:
    site = handoff.site_of(vendor)
    return {"supported": site is not None, "label": site["label"] if site else "",
            "bound": bool(site and link and link.site_account)}


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
        "shipping_paid": _money(receipt.shipping_paid),
        "cash_paid": _money(po.cash_paid),
        "qty": sum(i.qty for i in receipt.items.all()),
        "created_at": receipt.created_at,
        "created_by": receipt.created_by.get_username() if receipt.created_by else "",
    }


def _order_data(order: VendorOrder, names=None, vendor_by_code=None) -> dict:
    """`names` = {廠商代碼: 名稱}、`vendor_by_code` = {廠商代碼: 廠商}(列一整頁時先查好,不要一張單查一次)。"""
    return {
        # 送進廠商的下單網站(有下單網站的半自動廠商,例 kcimos):能不能送、是不是「待確認」、廠商那邊的訂單編號
        "site": handoff.status(order, vendor_by_code),
        "id": order.id,
        "provider": order.provider,
        "provider_label": (names or {}).get(order.provider) or vendors.name_of(order.provider),
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
        # 半自動廠商的單(POS 自己成立的):要傳給廠商的那一段、傳了沒、人記的進度、取消了沒
        "manual": order.manual,
        "message": manual.order_text(order) if order.manual else "",
        "sent_at": order.sent_at,
        "sent_how": order.sent_how,
        "sent_by": order.sent_by.get_username() if order.sent_by else "",
        "progress_note": order.progress_note,
        "cancelled_at": order.cancelled_at,
        "cancelled_by": order.cancelled_by.get_username() if order.cancelled_by else "",
        "items": [{
            "line_no": i.line_no, "sku": i.sku, "spec_id": i.spec_id, "spec_label": i.spec_label, "name": i.name,
            "unit": i.unit, "pack_qty": i.pack_qty, "packs": i.packs, "qty": i.qty, "unit_price": _money(i.unit_price),
            # 叫貨當下連到的店內商品(沒連、或加這幾格之前的舊單 = 空的)
            "product": i.product_id, "product_sku": i.product_sku, "product_name": i.product_name,
        } for i in order.items.all()],
    }


def _orders(request, store=None, vendor=None):
    qs = VendorOrder.objects.filter(tenant=request.tenant) \
        .select_related("warehouse", "created_by", "sent_by", "cancelled_by", "tenant") \
        .prefetch_related("items", "receipts__purchase_order", "receipts__items", "receipts__created_by", "handoffs")
    own = locked_warehouse_id(request.user)
    if own is not None:
        qs = qs.filter(warehouse_id=own)
    if store is not None:
        qs = qs.filter(warehouse=store)
    if vendor is not None:
        qs = qs.filter(provider=vendor.code)
    return qs


def _names() -> dict:
    return dict(Vendor.objects.values_list("code", "name"))


def _page(request, store=None, vendor=None) -> list:
    by_code = {v.code: v for v in Vendor.objects.all()}
    names = {code: v.name for code, v in by_code.items()}
    return [_order_data(o, names, by_code) for o in _orders(request, store, vendor)[:LIST_ROWS]]


# ── 叫貨串接 ────────────────────────────────────────────────────────────────
@api_view(["GET", "POST"])
def links(request):
    manager = is_tenant_admin(request.user)
    if request.method == "GET":
        stores = Warehouse.objects.filter(tenant=request.tenant, is_active=True).order_by("code", "id")
        own = locked_warehouse_id(request.user)
        if own is not None:
            stores = stores.filter(pk=own)
        saved = {(l.warehouse_id, l.provider): l
                 for l in VendorLink.objects.filter(tenant=request.tenant).select_related("supplier")}
        hints = _hints(request.tenant)
        listed = list(Vendor.objects.prefetch_related("categories"))
        rows = []
        for store in stores:
            for vendor in listed:
                link = saved.get((store.id, vendor.code))
                if not vendor.is_active and link is None:
                    continue        # 停用的廠商:這家門市沒設定過就不列(設定過的留著,紀錄還要看)
                if not vendors.open_to(vendor, request.tenant) and link is None:
                    continue        # 只給別家公司的廠商:不列(以前設定過、後來被收回的留著,紀錄還要看)
                rows.append(_link_data(store, vendor, link, hints, manager))
        return Response({
            "results": rows,
            # 叫貨頁上面那一排類別(只用來篩廠商)
            "categories": [{"id": c.id, "name": c.name} for c in VendorCategory.objects.filter(is_active=True)],
        })

    if not manager:
        return _bad("只有管理員可以設定叫貨串接", status.HTTP_403_FORBIDDEN)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        store = _store(request, data.get("warehouse"))
        vendor = _vendor(request, data.get("vendor"), active=False)
        link = _link(request, store, vendor)
        is_manual = manual.is_manual(vendor)
        opening = is_manual and data.get("opened") is True and not (link and link.opened)
        if not vendor.is_active and (link is None or data.get("key") or opening):
            raise services.VendorError(f"「{vendor.name}」已經停用,不能新開通或換金鑰")
        if not vendors.open_to(vendor, request.tenant) and (link is None or data.get("key") or opening):
            raise services.VendorError(f"「{vendor.name}」沒有開放給這家公司,不能新開通或換金鑰")
        if is_manual and data.get("key"):
            raise services.VendorError(f"「{vendor.name}」不用金鑰(按「開通」就可以叫貨)")
        values = {}
        for name in LINK_FIELDS:
            if name in data:
                value = data[name]
                if not isinstance(value, str) or len(value.strip()) > LINK_LIMITS[name]:
                    raise services.VendorError("有一格的內容太長或格式不對")
                values[name] = value.strip()
        current = _link_data(store, vendor, link, {}, False)
        merged = {name: values.get(name, current[name]) for name in LINK_FIELDS}
        if is_manual:       # 半自動的只管付款、取貨、收件(發票那幾格是全自動那一套要的)
            manual.check_header(merged["payment_method"], merged["delivery_method"], merged["ship_name"],
                                merged["ship_phone"], merged["ship_address"])
        else:
            services.check_header(**merged)
        for flag, wrong in (("freight_into_cost", "運費要不要算進成本,只能是「要」或「不要」"),
                            ("clerk_ordering", "誰能叫貨只能是「店員也可」或「只限管理」"),
                            *((("opened", "開通只能是「開」或「關」"),) if is_manual else ())):
            if flag in data:
                if not isinstance(data[flag], bool):
                    raise services.VendorError(wrong)
                merged[flag] = data[flag]
        if "supplier" in data:
            raw_supplier = data["supplier"]
            supplier = None
            if raw_supplier is not None:
                supplier = Supplier.objects.filter(tenant=request.tenant, pk=raw_supplier).first() \
                    if isinstance(raw_supplier, int) and not isinstance(raw_supplier, bool) else None
                if supplier is None:
                    raise services.VendorError("找不到這個供應商")
            merged["supplier"] = supplier
        # 解除下單網站的帳號綁定(綁錯帳號時管理員按的;下一次送單會重新問、重新綁)
        forget = data.get("forget_site_account")
        if forget not in (None, True):
            raise services.VendorError("解除綁定只能是「要」")
        # 會去打這家廠商一次(金鑰只送給它所屬的那一家)
        raw, sandbox = services.check_key(vendor, data["key"]) if data.get("key") else (None, None)
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    if link is None:
        link, _ = VendorLink.objects.get_or_create(
            tenant=request.tenant, provider=vendor.code, warehouse=store,
            defaults={**merged, "updated_by": request.user})
    for name, value in merged.items():
        setattr(link, name, value)
    link.updated_by = request.user
    # 只寫這裡管的那幾格:`site_account` 是送單時綁的(`handoff.submitting`,鎖著這一列寫的),整列重存會把剛綁好的蓋回空的
    link.save(update_fields=[*merged, "updated_by", "updated_at"])
    if forget:
        VendorLink.objects.filter(pk=link.pk).update(site_account="")       # 一句更新:正在綁的那一筆會先做完
        link.site_account = ""
    if raw:
        secrets.store(link, raw, request.user, sandbox)
    return Response(_link_data(store, vendor, link, _hints(request.tenant, link), True))


@api_view(["POST"])
def remove_key(request, warehouse_id: int):
    if not is_tenant_admin(request.user):
        return _bad("只有管理員可以設定叫貨串接", status.HTTP_403_FORBIDDEN)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        store = _store(request, warehouse_id)
        vendor = _vendor(request, data.get("vendor"), active=False)
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    link = _link(request, store, vendor)
    if link is not None:
        VendorSecret.objects.filter(link=link).delete()
    return Response(_link_data(store, vendor, link, {}, True))


# ── 叫貨 ────────────────────────────────────────────────────────────────────
@api_view(["GET"])
def catalog(request):
    abilities.require(request.user, abilities.VENDOR_ORDER)
    try:
        store = _store(request, request.query_params.get("warehouse"))
        vendor = _vendor(request, request.query_params.get("vendor"))
        link = _need_link(request, store, vendor)
        _may_order(request, link)
        rows = manual.catalog_rows(link, vendor)
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    # 每一列連到店裡的哪個商品(跟「對照」分頁、到貨入庫同一套查法):叫貨那一頁用店內品名,廠商的品名拿來核對
    owners = mapping.owners_by_key(request.tenant, link, rows)
    # `manual` = 半自動的廠商:價錢是平台價目表上的參考價,沒有價錢的也可以叫
    return Response({"warehouse": store.id, "vendor": vendor.code, "manual": manual.is_manual(vendor), "rows": [{
        **row,
        "unit_price": _money(row["unit_price"]),
        "pack_price": None if row["unit_price"] is None else _money(row["unit_price"] * row["pack_qty"]),
        "product": mapping.product_data(owners.get(row["key"])),
    } for row in rows]})


@api_view(["GET", "POST"])
def orders(request):
    if request.method == "GET":
        try:
            store = _store(request, request.query_params.get("warehouse"), required=False)
            wanted = request.query_params.get("vendor")
            vendor = _vendor(request, wanted, active=False) if wanted else None       # 沒講 = 每一家的都列
        except services.VendorError as exc:
            return _bad(exc, exc.status)
        return Response({"results": _page(request, store, vendor)})

    abilities.require(request.user, abilities.VENDOR_ORDER)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        store = _store(request, data.get("warehouse"))
        # 停用的廠商在 services.place 擋(同一把鑰匙再來確認先前那一張,廠商停用了也要回得了)
        vendor = _vendor(request, data.get("vendor"), active=False)
        is_manual = manual.is_manual(vendor)
        # 半自動:開通了沒在 manual.place 裡看(同一把鑰匙再來確認先前那一張,之後被關掉了也要回得了)
        link = _link(request, store, vendor) if is_manual else _need_link(request, store, vendor)
        if is_manual and link is None:
            manual.need_open(link, vendor)
        _may_order(request, link)
        common = dict(tenant=request.tenant, user=request.user, link=link, request_key=data.get("request_key"),
                      lines=data.get("lines"), payment_method=data.get("payment_method") or None,
                      delivery_method=data.get("delivery_method") or None, note=data.get("note") or "")
        order, created = manual.place(vendor=vendor, **common) if is_manual else services.place(**common)
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
    _may_order(request, order.link)         # 再送一次可能就是成立的那一次:跟叫貨同一個門檻
    if order.manual:
        return Response(_order_data(order))        # POS 自己成立的單沒有「不確定」,不用再送
    try:
        order = services.resend(order)
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response(_order_data(_orders(request).get(pk=order.pk)))


@api_view(["POST"])
def sync(request):
    """更新這家門市跟這家廠商叫貨單的進度,並帶回廠商那邊「不是從 POS 叫的」訂單。"""
    _needs_either(request)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        store = _store(request, data.get("warehouse"))
        vendor = _vendor(request, data.get("vendor"), active=False)
        link = _need_link(request, store, vendor)
        # 半自動的廠商沒有系統可以問:進度是人記的,也沒有「不是從 POS 叫的單」可以列
        others = [] if manual.is_manual(vendor) else services.sync(request.tenant, link)
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response({"results": _page(request, store, vendor), "others": others})


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
        return Response(manual.plan(request.tenant, order) if order.manual else receiving.plan(request.tenant, order))
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
        if order.manual:        # 半自動:實際單價與這一次的運費是入庫的人填的
            receipt, created = manual.receive(
                tenant=request.tenant, user=request.user, order=order, request_key=data.get("request_key"),
                lines=data.get("lines"), freight=data.get("freight"),
            )
        else:
            receipt, created = receiving.receive(
                tenant=request.tenant, user=request.user, order=order, request_key=data.get("request_key"),
                lines=data.get("lines"), freight=data.get("freight"),
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
        vendor = _vendor(request, data.get("vendor"), active=False)       # 廠商停用了,已經叫的貨照樣要入得了庫
        link = _need_link(request, store, vendor)
        if manual.is_manual(vendor):
            raise services.VendorError(f"「{vendor.name}」沒有系統可以查單;不是從這裡叫的貨請開一般的進貨單入庫")
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


# ── 品名連連看 ──────────────────────────────────────────────────────────────
@api_view(["GET", "POST"])
def mappings(request):
    """GET:這家廠商的每一個品項與對到的店內商品。POST:連 / 改 / 解除一個品項(`product` 給 null = 解除)。"""
    _needs_either(request)
    data = request.query_params if request.method == "GET" else (request.data if isinstance(request.data, dict) else {})
    try:
        store = _store(request, data.get("warehouse"))
        # 廠商停用了,已經叫的貨還要入庫,對照照樣看得到、改得了;但這一頁列的是廠商現在的全部品項 ——
        # 被平台收回的公司不能再看(舊單入庫時在入庫的面板對品號,不經過這裡)
        vendor = _vendor(request, data.get("vendor"), active=False, open_now=True)
        link = _need_link(request, store, vendor)
        if request.method == "GET":
            return Response({"warehouse": store.id, "vendor": vendor.code, **mapping.rows(request.tenant, link, vendor)})
        row = mapping.set_product(tenant=request.tenant, user=request.user, link=link, vendor=vendor,
                                  key=data.get("key"), product_id=data.get("product"))
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response(row)


# ── 送進廠商的下單網站(kcimos)────────────────────────────────────────────────
@api_view(["POST"])
def order_handoff(request, pk: int):
    """叫貨單上按「自動送單」:回要開的網址(後面帶一次性的代碼)。真正送單的是那一頁裡的小幫手,見 `handoff.py`。"""
    abilities.require(request.user, abilities.VENDOR_ORDER)
    order = _own_order(request, pk)
    if order is None:
        return _bad("找不到這張叫貨單", status.HTTP_404_NOT_FOUND)
    try:
        _may_order(request, order.link)
        url, issued = handoff.start(tenant=request.tenant, user=request.user, order=order)
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response({"url": url, "expires_at": issued.expires_at})


@api_view(["POST"])
def order_handoff_resolve(request, pk: int):
    """把「待確認」確認掉:`{"placed": true, "order_no": "…"}` 已成立 / `{"placed": false}` 沒有成立(可以再送)。"""
    abilities.require(request.user, abilities.VENDOR_ORDER)
    order = _own_order(request, pk)
    if order is None:
        return _bad("找不到這張叫貨單", status.HTTP_404_NOT_FOUND)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        _may_order(request, order.link)
        handoff.resolve(tenant=request.tenant, user=request.user, order=order,
                        placed=data.get("placed"), order_no=data.get("order_no") or "")
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response(_order_data(_orders(request).get(pk=order.pk)))


# ── 半自動廠商的叫貨單:傳了沒、進度、取消 ────────────────────────────────────
def _manual_action(request, pk, work):
    order = _own_order(request, pk)
    if order is None:
        return _bad("找不到這張叫貨單", status.HTTP_404_NOT_FOUND)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        work(order, data)
    except services.VendorError as exc:
        return _bad(exc, exc.status)
    return Response(_order_data(_orders(request).get(pk=order.pk)))


@api_view(["POST"])
def order_sent(request, pk: int):
    """店員把叫貨內容貼給廠商之後按「已貼給廠商」(`sent: true`;收回給 false)。"""
    abilities.require(request.user, abilities.VENDOR_ORDER)
    return _manual_action(request, pk, lambda order, data: manual.mark_sent(order, request.user, data.get("sent")))


@api_view(["POST"])
def order_progress(request, pk: int):
    """人記的一句進度(廠商沒有系統可以查)。叫貨的人、收貨的人都可以記;空的 = 清掉。"""
    _needs_either(request)
    return _manual_action(request, pk, lambda order, data: manual.set_progress(order, data.get("note")))


@api_view(["POST"])
def order_cancel(request, pk: int):
    """取消(`cancelled: true`)/ 恢復(false)。只是 POS 這邊的標記,要自己跟廠商講。"""
    abilities.require(request.user, abilities.VENDOR_ORDER)
    return _manual_action(request, pk, lambda order, data: manual.set_cancelled(order, request.user, data.get("cancelled")))
