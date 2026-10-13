"""收到的批發單:下單、接單 / 拒絕、取消、不出。出貨在 `shipping.py`。

**一台中古機同時只會被一張單訂著**:下單時先鎖那一台(序號那一列),鎖到之後才看它還在不在賣;
資料庫另外有一條「一台只有一行訂著」的限制當最後一道。門市要賣這一台時也是先鎖序號(`holds.before_sale`),所以兩邊一次只有一個。

**動一張單的明細之前,一律先鎖那張單那一列**(`_locked`)。
"""
import re
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.inventory.locking import lock_stock_rows
from apps.inventory.models import ProductSerial

from . import listing
from .base import ZERO, TradeError, setting_of
from .models import TradeOrder, TradeOrderLine, TradePartner, TradeProduct, TradeUnit

S = TradeOrder.Status
OPEN_STATES = (S.PENDING, S.ACCEPTED)
MAX_LINES = 100
MAX_QTY = 9999
BUYER_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,100}$")
BUYER_CANCEL = "買家取消"
DELIVERY = ("宅配", "自取")


def status_text(order: TradeOrder, lines=None) -> str:
    """給買賣雙方看的狀態(賣家回什麼買家就顯示什麼)。"""
    if order.status == S.ACCEPTED:
        lines = order.lines.all() if lines is None else lines
        return "部分出貨" if any(line.shipped_qty for line in lines) else "已接單"
    return order.get_status_display()


def unit_label(serial) -> str:
    """一台中古機給買家看的機況(不含序號:出貨之前不露)。"""
    parts = []
    if serial.condition_grade:
        parts.append(f"{serial.condition_grade} 級")
    if serial.battery_health is not None:
        parts.append(f"電池 {serial.battery_health}%")
    if serial.condition_note:
        parts.append(serial.condition_note)
    return " ".join(parts)[:120]


def goods_total(lines) -> Decimal:
    """這張單現在的貨款(不出的那幾個不算)。"""
    return sum((line.unit_price * (line.qty - line.cancelled_qty) for line in lines), ZERO)


def _text(value, limit) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _header(partner: TradePartner, body: dict) -> dict:
    ship = body.get("ship_to") if isinstance(body.get("ship_to"), dict) else {}
    invoice = body.get("invoice") if isinstance(body.get("invoice"), dict) else {}
    # 取貨方式要講清楚(賣家出貨的人照單上寫的寄或等人來拿;紅隊 2026-10-14):沒講 = 自取;宅配要有收件人、電話、地址
    delivery = _text(body.get("delivery_method"), 20) or "自取"
    if delivery not in DELIVERY:
        raise TradeError("取貨方式只能是 宅配 / 自取", "bad_ship")
    if delivery == "宅配" and not all(_text(ship.get(name), 200) for name in ("name", "phone", "address")):
        raise TradeError("宅配要有收件人、電話、地址", "bad_ship")
    return {
        # 付款方式是賣家跟這個同行講好的那一種(賣家在「同行帳」定的);買家送什麼都不看
        "payment_method": partner.terms,
        "delivery_method": delivery,
        "ship_name": _text(ship.get("name"), 60), "ship_phone": _text(ship.get("phone"), 40),
        "ship_address": _text(ship.get("address"), 200),
        "invoice_type": _text(invoice.get("type"), 10), "buyer_tax_id": _text(invoice.get("buyer_tax_id"), 20),
        "buyer_name": _text(invoice.get("buyer_name"), 120), "invoice_email": _text(invoice.get("email"), 200),
        "note": _text(body.get("note"), 200),
    }


def _wanted(items) -> list[tuple[str, object, int]]:
    if not isinstance(items, list) or not items:
        raise TradeError("至少要訂一項", "empty")
    if len(items) > MAX_LINES:
        raise TradeError(f"一張單最多 {MAX_LINES} 項", "too_many")
    out, seen = [], set()
    for row in items:
        sku = row.get("sku") if isinstance(row, dict) else None
        spec = row.get("spec_id") if isinstance(row, dict) else None
        qty = row.get("qty") if isinstance(row, dict) else None
        if not isinstance(sku, str) or not sku.strip():
            raise TradeError("有一項沒有品號", "bad_item")
        if spec is not None and (isinstance(spec, bool) or not isinstance(spec, int)):
            raise TradeError(f"{sku} 的規格不對", "bad_item")
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= MAX_QTY:
            raise TradeError(f"{sku} 的數量要是 1 到 {MAX_QTY} 的整數", "bad_qty")
        if (sku, spec) in seen:
            raise TradeError(f"{sku} 重複了", "duplicate")
        seen.add((sku, spec))
        out.append((sku, spec, qty))
    return out


def place(*, seller, partner: TradePartner, key, body: dict, store: str = "", is_test: bool = False):
    """成立一張批發單。回 (單, 是不是這一次新成立的)。同一把鑰匙再來回同一張。

    價錢一律這邊算(買家送了也不看)。被擋下來的不佔用鑰匙。
    """
    if not isinstance(key, str) or not BUYER_KEY.match(key):
        raise TradeError("這張單的鑰匙不對", "bad_key")
    existing = TradeOrder.objects.filter(tenant=seller, partner=partner, buyer_key=key).first()
    if existing is not None:
        return existing, False
    setting = setting_of(seller)
    if not setting.is_open:
        raise TradeError("這家現在沒有開放批發", "closed")
    if partner.status == TradePartner.Status.BLOCKED:
        raise TradeError("這家沒有開放給你", "forbidden", 403)
    wanted = _wanted(body.get("items"))
    header = _header(partner, body)
    products = {p.sku: p for p in Product.objects.filter(tenant=seller, sku__in=[w[0] for w in wanted], is_active=True)
                .select_related("condition")}
    gone = TradeError("有一項現在沒有在賣(清單可能更新過),請重新整理再選", "not_available")
    unit_ids, qty_products = [], []
    for sku, spec, qty in wanted:
        product = products.get(sku)
        if product is None:
            raise gone
        if listing.is_unit_product(product):
            if spec is None or qty != 1:
                raise TradeError(f"「{product.name}」是一台一筆賣的,要指定哪一台、數量 1", "bad_item")
            unit_ids.append(spec)
        else:
            if spec is not None:
                raise TradeError(f"「{product.name}」沒有規格", "bad_item")
            qty_products.append(product)
    approved = partner.status == TradePartner.Status.APPROVED
    if qty_products and not approved:
        raise gone                      # 沒有核准的同行看不到按數量賣的商品(也沒有他的價錢)
    if unit_ids and not (approved or setting.units_to_all):
        raise gone
    try:
        with transaction.atomic():
            units = {u.id: u for u in TradeUnit.objects.filter(tenant=seller, pk__in=unit_ids)}
            if len(units) != len(unit_ids):
                raise gone
            lock_stock_rows(seller, products=sorted(qty_products, key=lambda p: p.id),
                            serial_ids=[u.serial_id for u in units.values()])
            # 鎖到之後才看:還在不在賣、還夠不夠
            free = {u.id: u for u in listing.units_for_sale(seller).filter(pk__in=unit_ids).select_related("serial__product")}
            offers = {t.product_id: t for t in listing.products_for_sale(seller).filter(product__in=qty_products)}
            left = listing.available_qty(seller, [p.id for p in qty_products])
            rows = []
            for n, (sku, spec, qty) in enumerate(wanted, start=1):
                product = products[sku]
                if spec is not None:
                    unit = free.get(spec)
                    if unit is None or unit.serial.product_id != product.id:
                        raise TradeError(f"「{product.name}」那一台剛被訂走或已經不賣了,請重新整理再選", "unit_gone")
                    rows.append(TradeOrderLine(
                        tenant=seller, line_no=n, product=product, unit=unit.serial, sku=product.sku, name=product.name[:200],
                        unit_label=unit_label(unit.serial), qty=1, unit_price=unit.price, holding=True))
                    continue
                offer = offers.get(product.id)
                price = listing.price_for(offer, partner) if offer is not None else None
                if price is None:
                    raise gone
                if qty > left.get(product.id, 0):
                    raise TradeError(f"「{product.name}」庫存不夠(最多還能訂 {left.get(product.id, 0)})", "out_of_stock")
                rows.append(TradeOrderLine(
                    tenant=seller, line_no=n, product=product, sku=product.sku, name=product.name[:200],
                    qty=qty, unit_price=price))
            now = timezone.now()
            order = TradeOrder.objects.create(
                tenant=seller, partner=partner, buyer_key=key, buyer_store=_text(store, 120), is_test=is_test,
                status=S.ACCEPTED if setting.auto_accept else S.PENDING,
                accepted_at=now if setting.auto_accept else None, **header)
            for row in rows:
                row.order = order
            TradeOrderLine.objects.bulk_create(rows)
    except IntegrityError:
        # 同一把鑰匙的另一個請求剛好先成立了;不是的話就是那一台同時被別張單訂走(資料庫的最後一道)
        existing = TradeOrder.objects.filter(tenant=seller, partner=partner, buyer_key=key).first()
        if existing is not None:
            return existing, False
        raise TradeError("有一台剛被訂走,請重新整理再選", "unit_gone") from None
    return order, True


# ── 之後的每一步(都先鎖那張單) ──────────────────────────────────────────────
def _locked(order: TradeOrder) -> TradeOrder:
    locked = TradeOrder.objects.select_for_update().filter(pk=order.pk).first()
    if locked is None:
        raise TradeError("這張批發單已經不在了")
    return locked


def _after_change(order: TradeOrder, *, by_buyer=False, reason="") -> None:
    """數量動過之後:沒有還要出的了 → 出過的算「已出貨」、一個都沒出的算「已取消」。"""
    lines = list(order.lines.all())
    fields = ["changed_at", "updated_at"]
    order.changed_at = timezone.now()
    if order.status in OPEN_STATES and not any(line.open_qty for line in lines):
        shipped = any(line.shipped_qty for line in lines)
        order.status = S.SHIPPED if shipped else S.CANCELLED
        order.closed_at = order.changed_at
        fields += ["status", "closed_at"]
        if not shipped:
            order.closed_by_buyer, order.close_reason = by_buyer, reason[:200]
            fields += ["closed_by_buyer", "close_reason"]
    order.save(update_fields=fields)


def _drop(order: TradeOrder, line: TradeOrderLine, qty: int) -> None:
    line.cancelled_qty += qty
    line.holding = bool(line.unit_id) and line.open_qty > 0
    line.save(update_fields=["cancelled_qty", "holding", "updated_at"])


def accept(order: TradeOrder) -> TradeOrder:
    with transaction.atomic():
        order = _locked(order)
        if order.status != S.PENDING:
            raise TradeError(f"這張單現在是「{order.get_status_display()}」,不用接單")
        order.status, order.accepted_at, order.changed_at = S.ACCEPTED, timezone.now(), timezone.now()
        order.save(update_fields=["status", "accepted_at", "changed_at", "updated_at"])
    return order


def reject(order: TradeOrder, reason="") -> TradeOrder:
    with transaction.atomic():
        order = _locked(order)
        if order.status != S.PENDING:
            raise TradeError(f"這張單現在是「{order.get_status_display()}」,不能拒絕(已經接的單用「不出」)")
        for line in order.lines.all():
            if line.open_qty:
                _drop(order, line, line.open_qty)
        now = timezone.now()
        order.status, order.closed_at, order.changed_at = S.REJECTED, now, now
        order.close_reason = _text(reason, 200)
        order.save(update_fields=["status", "closed_at", "changed_at", "close_reason", "updated_at"])
    return order


def drop(order: TradeOrder, line: TradeOrderLine, qty, *, reason="") -> TradeOrder:
    """賣家:這一行的幾個不出(找不到那一台、沒貨了、改賣給現場客人)。其餘的照樣出。"""
    with transaction.atomic():
        order = _locked(order)
        line = TradeOrderLine.objects.filter(pk=line.pk, order=order).first()
        if line is None:
            raise TradeError("這張單沒有這一行")
        if order.status not in OPEN_STATES:
            raise TradeError(f"這張單現在是「{order.get_status_display()}」,不能再改")
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= line.open_qty:
            raise TradeError(f"「{line.name}」還沒出的只有 {line.open_qty} 個")
        _drop(order, line, qty)
        _after_change(order, reason=_text(reason, 200))
    return order


def cancel_open(order: TradeOrder, *, by_buyer: bool, reason="") -> TradeOrder:
    """還沒出的全部取消(買家自己取消 / 賣家整張不出)。出過的那一部分不動。"""
    with transaction.atomic():
        order = _locked(order)
        if order.status not in OPEN_STATES:
            raise TradeError(f"這張單現在是「{order.get_status_display()}」,不能取消;要處理請聯絡賣家", "not_cancellable")
        for line in order.lines.all():
            if line.open_qty:
                _drop(order, line, line.open_qty)
        _after_change(order, by_buyer=by_buyer, reason=_text(reason, 200) or (BUYER_CANCEL if by_buyer else ""))
    return order
