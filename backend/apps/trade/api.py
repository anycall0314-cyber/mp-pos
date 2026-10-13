"""賣家對買家講話的那一面:買賣串接規格 v2(`docs/api/買賣串接規格_v2_草稿.md`)。**平台內與對外是同一支**。

`handle(賣家公司, 這個買家(往來對象), 方法, 路徑, 內容)` 回 (HTTP 狀態, 內容):
- 平台內:`vendor_orders` 的串接器直接呼叫(不用金鑰、不走網路)。
- 對外:HTTP 端點驗過金鑰、認出是哪一個往來對象之後呼叫同一支。
所以買家看得到什麼、看不到什麼只有這裡一份:**只回開放給他的商品與他自己的價錢、他自己的單;成本、別人的價錢、別人的單一律不出現**。

金額一律整數元;價錢含稅。中古機一台一筆:商品帶 `per_unit: true`,每一台是 `specs[]` 的一項(`id` = 那一台);出貨之前不露序號。
"""
import re
from datetime import date
from urllib.parse import parse_qsl

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from . import listing, orders, partners, payments, shipping
from .base import TradeError, setting_of
from .models import TradeOrder, TradePartner, TradeShipment, TradeShipmentLine, TradeUnit

ORDER_PATH = re.compile(r"^/orders/([A-Za-z0-9_-]{1,40})(/cancel|/received)?$")
DELIVERY_METHODS = ["宅配", "自取"]


def is_sandbox() -> bool:
    """這個環境下的是不是測試單(測試站 = 是)。"""
    return bool(settings.VENDOR_SANDBOX_ONLY)


def _money(value) -> int:
    return int(value)


def _fail(status: int, message: str, code: str = "") -> tuple[int, dict]:
    body = {"ok": False, "error": message}
    if code:
        body["code"] = code
    return status, body


def _ok(**data) -> tuple[int, dict]:
    return 200, {"ok": True, "sandbox": is_sandbox(), **data}


def handle(seller, partner: TradePartner, method: str, path: str, body=None, *, store: str = "") -> tuple[int, dict]:
    """`partner` 可以是還沒存檔的「平台同行」(只看商品);要下單的時候呼叫的人要先給存檔的那一筆。"""
    path, _, query = path.partition("?")
    # 查詢字串照一般的網址寫法解開(`%3A`、`%2B`…);同一個名字給兩次用最後一個
    params = dict(parse_qsl(query, keep_blank_values=True))
    setting = setting_of(seller)
    visible = any(partners.can_see(setting, partner))
    try:
        if path in ("/capabilities", "/products") or (method == "POST" and path == "/orders"):
            # 新的事(看商品、下單):沒開放、不往來的連這家有沒有在賣都不講。
            # 下面那幾支(自己已經有的單、對帳單、取消)不擋:貨可能已經在路上,買家還是要查得到、入得了庫
            if not visible:
                return _fail(403, "這家沒有開放給你", "forbidden")
            if method == "GET" and path == "/capabilities":
                return _capabilities(seller, setting, partner)
            if method == "GET":
                return _products(seller, setting, partner)
            return _place(seller, partner, body if isinstance(body, dict) else {}, store)
        if method == "GET" and path == "/orders":
            return _orders(partner, params)
        if method == "GET" and path == "/statements":
            return _statement(partner, params)
        found = ORDER_PATH.match(path)
        if found:
            order = (TradeOrder.objects.filter(tenant=seller, partner=partner, no=found.group(1)).first()
                     if partner.pk else None)
            if order is None:
                return _fail(404, "找不到這張單", "not_found")
            if method == "GET" and not found.group(2):
                return _ok(order=order_data(order, partner))
            if method == "POST" and found.group(2) == "/cancel":
                order = orders.cancel_open(order, by_buyer=True)
                return _ok(order_no=order.no, status=orders.status_text(order))
            if method == "POST" and found.group(2) == "/received":
                # 買家回報這張單到現在為止收了多少(賣家照它擋取消出貨與整張銷退)
                order = shipping.report_received(order, (body or {}).get("items") if isinstance(body, dict) else None)
                return _ok(order_no=order.no, status=orders.status_text(order))
    except TradeError as exc:
        return _fail(exc.status, str(exc), exc.code)
    return _fail(404, "沒有這個功能", "not_found")


# ── 會哪些 ──────────────────────────────────────────────────────────────────
def _capabilities(seller, setting, partner):
    caps = ["products", "availability", "orders", "cancel", "shipments", "serials", "receipts", "statements", "units"]
    if not setting.auto_accept:
        caps.append("accept")
    return _ok(
        seller={"name": seller.name, "price_includes_tax": True, "pay_note": setting.pay_note, "contact": setting.contact},
        buyer={"name": partner.name, "status": partner.get_status_display(), "payment_method": partner.terms},
        capabilities=caps, payment_methods=list(partners.TERMS), delivery_methods=DELIVERY_METHODS)


# ── 商品 ────────────────────────────────────────────────────────────────────
def _stock_text(setting, left: int) -> dict:
    out = {"available": "有貨" if left > 0 else "缺貨"}
    if setting.show_qty:
        out["available_qty"] = left
    return out


def _products(seller, setting, partner):
    see_units, see_goods = partners.can_see(setting, partner)
    rows = []
    if see_goods:
        offers = list(listing.products_for_sale(seller).order_by("product__category__sort_order", "product__name", "id"))
        offers = [o for o in offers if not listing.is_unit_product(o.product)]
        left = listing.available_qty(seller, [o.product_id for o in offers])
        for offer in offers:
            price = listing.price_for(offer, partner)
            if price is None:
                continue
            product = offer.product
            rows.append({
                "sku": product.sku, "name": product.name, "kind": product.category.name, "size": product.spec,
                "unit": "台" if product.requires_serial else "個", "pack_qty": 1, "unit_price": _money(price),
                "requires_serial": product.requires_serial, "condition": "全新", "per_unit": False,
                **_stock_text(setting, left.get(product.id, 0)),
            })
    if see_units:
        by_product = {}
        units = listing.units_for_sale(seller).select_related("serial__product__category").order_by(
            "serial__product__name", "serial__product_id", "price", "id")
        for unit in units:
            by_product.setdefault(unit.serial.product_id, []).append(unit)
        for group in by_product.values():
            product = group[0].serial.product
            rows.append({
                "sku": product.sku, "name": product.name, "kind": product.category.name, "size": product.spec,
                "unit": "台", "pack_qty": 1, "unit_price": None, "requires_serial": True,
                "condition": "中古" if product.is_secondhand else "已拆封", "per_unit": True, "available": "有貨",
                "specs": [{
                    "id": unit.id, "code": f"{unit.serial.condition_grade} 級" if unit.serial.condition_grade else "",
                    "name": " ".join(x for x in (
                        f"電池 {unit.serial.battery_health}%" if unit.serial.battery_health is not None else "",
                        unit.serial.condition_note) if x),
                    "unit_price": _money(unit.price),
                } for unit in group],
            })
    return _ok(products=rows)


# ── 單 ──────────────────────────────────────────────────────────────────────
def _place(seller, partner, body, store):
    if not partner.pk:
        return _fail(403, "這家沒有開放給你", "forbidden")
    key = body.get("idempotency_key")
    order, created = orders.place(seller=seller, partner=partner, key=key, body=body, store=store, is_test=is_sandbox())
    lines = list(order.lines.all())
    if not created:
        # v1 的講法:這把鑰匙送過、而且成立了 → 409 與那張單號(不是錯誤)
        return 409, {"ok": False, "sandbox": is_sandbox(), "error": "這張單已經成立過了", "order_no": order.no,
                     "status": orders.status_text(order, lines)}
    return _ok(order_no=order.no, status=orders.status_text(order, lines), payment_method=order.payment_method,
               total_amount=_money(orders.goods_total(lines)), shipping_fee=0)


def _shipments_of(order_ids) -> dict:
    """這幾張單算數的出貨(沒取消、沒被整張銷退),照出貨的先後。"""
    out = {}
    for shipment in payments.live_shipments(TradeShipment.objects.filter(order_id__in=list(order_ids))).order_by("id"):
        out.setdefault(shipment.order_id, []).append(shipment)
    return out


def _summary(order, lines, shipments, paid_text) -> dict:
    last = shipments[-1] if shipments else None
    fee = sum((s.shipping_fee for s in shipments), 0)
    return {
        "order_no": order.no, "ordered_at": timezone.localtime(order.created_at).isoformat(timespec="seconds"),
        "status": orders.status_text(order, lines), "payment_status": paid_text,
        "logistics_status": f"已出 {len(shipments)} 次" if shipments else "",
        "shipping_method": last.shipping_method if last else "", "tracking_no": last.tracking_no if last else "",
        "shipping_fee": _money(fee), "total_amount": _money(orders.goods_total(lines) + fee),
        # 付款方式是賣家跟這個買家講好的那一種(買家那邊的紀錄照這個寫)
        "payment_method": order.payment_method,
    }


def order_data(order: TradeOrder, partner: TradePartner) -> dict:
    """一張單現在的樣子(買家看的)。`items` 只有還算數的(整行不出的放在 `cancelled_items`);數量已經扣掉不出的。"""
    lines = list(order.lines.select_related("product"))
    shipments = _shipments_of([order.id]).get(order.id, [])
    by_shipment = {}
    for row in (TradeShipmentLine.objects.filter(shipment__in=shipments).select_related("line")
                .prefetch_related("serials").order_by("id")):
        by_shipment.setdefault(row.shipment_id, []).append(row)
    # 中古機那幾行的「規格」= 那一台的上架編號(買家下單時帶的就是它)
    spec_of = dict(TradeUnit.objects.filter(serial_id__in=[line.unit_id for line in lines if line.unit_id])
                   .values_list("serial_id", "id"))
    paid = next((payments.status_text(r["owed"], r["paid"]) for r in payments.ledger(partner)["orders"]
                 if r["order"].id == order.id), "")
    # 「已出」只算現在算數的出貨(取消的、整張銷退掉的不算):買家照這個數入庫
    shipped = {}
    for rows in by_shipment.values():
        for row in rows:
            shipped[row.line_id] = shipped.get(row.line_id, 0) + row.qty

    def item(line):
        qty = line.qty - line.cancelled_qty
        return {
            "sku": line.sku, "spec_id": spec_of.get(line.unit_id), "name": line.name, "spec_code": "",
            "spec_name": line.unit_label, "unit": "台" if line.product.requires_serial else "個", "pack_qty": 1,
            "qty": qty, "unit_price": _money(line.unit_price), "subtotal": _money(line.unit_price * qty),
            "shipped_qty": shipped.get(line.id, 0), "received_qty": line.received_qty,
            "requires_serial": line.product.requires_serial, "per_unit": bool(line.unit_id),
        }

    return {
        **_summary(order, lines, shipments, paid),
        "delivery_method": order.delivery_method, "note": order.note,
        "close_reason": order.close_reason,
        "items": [item(line) for line in lines if line.qty > line.cancelled_qty],
        "cancelled_items": [{"sku": line.sku, "name": line.name, "spec_name": line.unit_label, "qty": line.cancelled_qty}
                            for line in lines if line.cancelled_qty],
        "shipments": [{
            "shipment_no": s.no, "shipped_at": timezone.localtime(s.created_at).isoformat(timespec="seconds"),
            "shipping_method": s.shipping_method, "tracking_no": s.tracking_no, "shipping_fee": _money(s.shipping_fee),
            "items": [{
                "sku": row.line.sku, "spec_id": spec_of.get(row.line.unit_id), "qty": row.qty,
                "serials": [{"imei": x.imei, "sn": x.sn, "grade": x.grade, "battery": x.battery, "note": x.note}
                            for x in row.serials.all()],
            } for row in by_shipment.get(s.id, [])],
        } for s in shipments],
    }


def _moment(text: str):
    try:
        found = parse_datetime(text)
    except ValueError:
        return None
    if found is not None and timezone.is_naive(found):
        found = timezone.make_aware(found)
    return found


def _day(text):
    """對帳單的起訖日(YYYY-MM-DD)。沒給 = 不限;看不懂的要講。"""
    if not text:
        return None
    try:
        found = parse_date(text)
    except ValueError:
        found = None
    if found is None:
        raise TradeError("日期看不懂(例:2026-10-14)", "bad_date")
    return found


def _limit(params, default=100, most=200) -> int:
    raw = params.get("limit", "")
    return min(int(raw), most) if raw.isdigit() and int(raw) > 0 else default


def _orders(partner, params):
    if not partner.pk:
        return _ok(orders=[])
    found = TradeOrder.objects.filter(partner=partner).order_by("-id")
    if params.get("since"):
        # 時區的加號沒有編碼的話會被解成空白:補回去。看不懂的時間要講(默默不篩的話,對方以為拿到的是「之後有變動的全部」)
        since = _moment(params["since"].replace(" ", "+"))
        if since is None:
            raise TradeError("since 的時間看不懂(例:2026-10-14T00:00:00+08:00)", "bad_since")
        found = found.filter(changed_at__gte=since)
    found = list(found.prefetch_related("lines")[:_limit(params)])
    paid = {row["order"].id: payments.status_text(row["owed"], row["paid"]) for row in payments.ledger(partner)["orders"]}
    shipped = _shipments_of(order.id for order in found)
    return _ok(orders=[_summary(order, list(order.lines.all()), shipped.get(order.id, []), paid.get(order.id, ""))
                       for order in found])


def _statement(partner, params):
    """對帳單:這個買家出過貨的每一張單 —— 出了多少錢的貨、收了多少、還欠多少。期間照下單日。"""
    if not partner.pk:
        return _ok(orders=[], totals={"shipped": 0, "paid": 0, "due": 0}, credit=0)
    book = payments.ledger(partner)
    start, end = _day(params.get("from")), _day(params.get("to"))
    rows = []
    for row in book["orders"]:
        day = timezone.localtime(row["order"].created_at).date()
        if (start and day < start) or (end and day > end):
            continue
        rows.append({
            "order_no": row["order"].no, "ordered_at": day.isoformat(), "shipped_amount": _money(row["owed"]),
            "paid_amount": _money(row["paid"]), "due_amount": _money(row["due"]),
            "payment_method": row["order"].payment_method, "payment_status": payments.status_text(row["owed"], row["paid"]),
        })
    return _ok(orders=rows, totals={
        "shipped": sum(r["shipped_amount"] for r in rows), "paid": sum(r["paid_amount"] for r in rows),
        "due": sum(r["due_amount"] for r in rows)}, credit=_money(book["credit"]), as_of=date.today().isoformat())
