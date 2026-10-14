"""上架:中古機一台一筆(`TradeUnit`)、按數量賣的商品開不開放(`TradeProduct`)。

「在不在賣」不另外存一個狀態,每次都是算的:有上架 + 那一台現在在庫 + 沒有被哪一張批發單訂著。
所以門市賣掉、調撥途中、送修、盤虧,它自己就從批發清單消失,不用誰去下架;調到另一家門市、修好回來又會出現(還是這家公司的貨)。
賣掉的另外會把「上架」關掉(`holds.after_sale`):之後銷退回來不會自己回到清單。
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Sum
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.money import round_money
from apps.inventory.locking import lock_stock_rows
from apps.inventory.models import ProductSerial, StockBalance

from .base import ZERO, TradeError, setting_of
from .models import TradeOrder, TradeOrderLine, TradePartner, TradeProduct, TradeSetting, TradeUnit

OPEN_STATES = (TradeOrder.Status.PENDING, TradeOrder.Status.ACCEPTED)
MAX_PRICE = Decimal("9999999")
# 一次上架 / 改價最多幾台:同一個型號在庫幾百台、整群定同一個價是常態(owner 2026-10-14)
MAX_ROWS = 2000


def is_unit_product(product) -> bool:
    """一台一筆賣的商品:帶序號、而且逐台記機況(中古機、已拆封)。"""
    return bool(product.requires_serial and not product.is_virtual and product.tracks_unit_condition)


def retail_price(serial) -> Decimal:
    """這一台的門市售價:自己有訂價用自己的,沒有用商品的。"""
    return serial.custom_unit_price if serial.custom_unit_price is not None else serial.product.list_price


def auto_price(setting: TradeSetting, serial):
    """照設定的規則算這一台的批發價(整數元)。算出來不是正的 = 算不出來(None),要人填。"""
    value = setting.unit_value or ZERO
    if setting.unit_rule == TradeSetting.Rule.COST_PLUS:
        price = (serial.purchase_unit_cost or ZERO) + value
    elif setting.unit_rule == TradeSetting.Rule.PRICE_PERCENT:
        price = (retail_price(serial) or ZERO) * value / Decimal("100")
    else:
        price = (retail_price(serial) or ZERO) - value
    price = round_money(price)
    return price if price > 0 else None


def clean_price(value, what: str):
    """畫面 / 表單送來的批發價:整數元、要是正的。空的回 None。"""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise TradeError(f"{what}的批發價不對")
    try:
        price = Decimal(str(value))
    except Exception:
        raise TradeError(f"{what}的批發價不對") from None
    if not price.is_finite() or price != price.to_integral_value() or not 0 < price <= MAX_PRICE:
        raise TradeError(f"{what}的批發價要是 1 到 {MAX_PRICE:f} 的整數")
    return price


# ── 中古機 ──────────────────────────────────────────────────────────────────
def _held(outer="serial_id"):
    return Exists(TradeOrderLine.objects.filter(unit_id=OuterRef(outer), holding=True))


def units_for_sale(tenant):
    """現在訂得到的每一台。"""
    return (TradeUnit.objects.filter(
        tenant=tenant, is_listed=True, serial__status=ProductSerial.Status.IN_STOCK,
        serial__warehouse__isnull=False, serial__product__is_active=True)
        .annotate(held=_held()).filter(held=False))


def _save_unit(tenant, serial, price, user, listed=True) -> TradeUnit:
    now = timezone.now()
    unit, _ = TradeUnit.objects.update_or_create(
        tenant=tenant, serial=serial,
        defaults={"price": price, "is_listed": listed, "listed_at": now if listed else None, "listed_by": user if listed else None})
    return unit


def after_intake(tenant, serials, *, user=None, wanted=None) -> int:
    """進貨 / 收購剛建好的幾台:照設定自動上架(owner:中古機要快速進貨就上架)。回上架了幾台。

    `wanted` = {序號編號: {"list": 要不要上架, "price": 批發價}}:表單上個別指定的(沒指定的照設定)。
    沒有開放批發、沒有開「進貨就上架」→ 沒有個別指定要上架的都不動。算不出批發價的那一台不上架(不擋進貨)。
    """
    setting = setting_of(tenant)
    automatic = setting.is_open and setting.auto_list_units
    done = 0
    for serial in serials:
        if not is_unit_product(serial.product):
            continue
        want = (wanted or {}).get(serial.id) or {}
        if not (want.get("list") if want.get("list") is not None else automatic):
            continue
        price = want.get("price") or auto_price(setting, serial)
        if price is None or price <= 0:
            continue
        _save_unit(tenant, serial, price, user)
        done += 1
    return done


def _save_units(tenant, priced, user) -> list[TradeUnit]:
    """把這幾台(`priced` = [(序號, 批發價)])記成上架。幾百台一起來也只有幾句查詢。"""
    now = timezone.now()
    have = {u.serial_id: u for u in TradeUnit.objects.filter(tenant=tenant, serial_id__in=[serial.id for serial, _ in priced])}
    new, old = [], []
    for serial, price in priced:
        unit = have.get(serial.id)
        if unit is None:
            new.append(TradeUnit(tenant=tenant, serial=serial, price=price, is_listed=True, listed_at=now, listed_by=user))
        else:
            unit.price, unit.is_listed, unit.listed_at, unit.listed_by, unit.updated_at = price, True, now, user, now
            old.append(unit)
    TradeUnit.objects.bulk_create(new, batch_size=500)
    TradeUnit.objects.bulk_update(old, ["price", "is_listed", "listed_at", "listed_by", "updated_at"], batch_size=500)
    return new + old


def _not_what_was_seen(serial, seen):
    """畫面說它看的是哪個型號 / 哪一間門市(`seen`);這一台不是的話回要講的話。

    畫面換門市、換型號的那一下,手上可能還是上一份清單(複審 P0:會把上一間門市的整群改掉)。畫面自己會擋,這裡是伺服器這一側的保險。
    """
    if not seen:
        return None
    if seen.get("product") and serial.product_id != seen["product"]:
        return f"{serial.serial_no} 不是畫面上那個型號的,請重新整理"
    if seen.get("warehouse") and serial.warehouse_id != seen["warehouse"]:
        return f"{serial.serial_no} 不在畫面選的那一間門市,請重新整理"
    return None


def put_on(tenant, user, rows, *, store=None, seen=None) -> list[TradeUnit]:
    """上架 / 改價幾台(`rows` = [{serial, price?}];沒給價錢的照規則算)。只有現在在庫的中古機能上架。
    `store` = 這個人被鎖在哪一間門市(沒鎖給 None):鎖門市的人只能動自己那一間的。
    `seen` = 畫面看的是哪個型號 / 門市(`{product, warehouse}`,沒給的不查):有一台不是就整批不動。

    **整批一起成立**:有一台不行(剛被賣掉、算不出價)就整批都不動,畫面把那一台講出來 —— 幾百台改到一半停住,
    沒有人知道哪幾台改了。先鎖序號(跟銷貨、批發下單同一個順序)才看在不在庫:剛賣掉的那一台不會被上架回去。
    """
    if not isinstance(rows, list) or not rows:
        raise TradeError("沒有要上架的")
    if len(rows) > MAX_ROWS:
        raise TradeError(f"一次最多上架 {MAX_ROWS} 台")
    wanted = {}
    for row in rows:
        serial_id = row.get("serial") if isinstance(row, dict) else None
        if isinstance(serial_id, bool) or not isinstance(serial_id, int) or serial_id in wanted:
            raise TradeError("上架的內容不對")
        wanted[serial_id] = row.get("price")
    setting = setting_of(tenant)
    with transaction.atomic():
        lock_stock_rows(tenant, serial_ids=list(wanted))
        serials = {s.id: s for s in ProductSerial.objects.filter(tenant=tenant, pk__in=wanted).select_related("product__condition")}
        priced = []
        for serial_id, raw in wanted.items():
            serial = serials.get(serial_id)
            if serial is None:
                raise TradeError("有一台找不到")
            if not is_unit_product(serial.product):
                raise TradeError(f"{serial.serial_no} 不是一台一筆賣的商品(中古機 / 已拆封)")
            if serial.status != ProductSerial.Status.IN_STOCK:
                raise TradeError(f"{serial.serial_no} 現在是「{serial.get_status_display()}」,不能上架")
            if store and serial.warehouse_id != store:
                raise TradeError(f"{serial.serial_no} 不在你的門市")
            wrong = _not_what_was_seen(serial, seen)
            if wrong:
                raise TradeError(wrong)
            price = clean_price(raw, serial.serial_no) or auto_price(setting, serial)
            if price is None:
                raise TradeError(f"{serial.serial_no} 算不出批發價,請填")
            priced.append((serial, price))
        return _save_units(tenant, priced, user)


def take_off(tenant, serial_ids, *, store=None, seen=None) -> int:
    """下架。已經被訂走的那一台不受影響(那張單還是訂著它)。`store`、`seen` 同 `put_on`。"""
    ids = [x for x in serial_ids if isinstance(x, int) and not isinstance(x, bool)] if isinstance(serial_ids, list) else []
    if not ids:
        raise TradeError("沒有要下架的")
    if len(ids) > MAX_ROWS:
        raise TradeError(f"一次最多下架 {MAX_ROWS} 台")
    if seen:
        for serial in ProductSerial.objects.filter(tenant=tenant, pk__in=ids).only("serial_no", "product_id", "warehouse_id"):
            wrong = _not_what_was_seen(serial, seen)
            if wrong:
                raise TradeError(wrong)
    found = TradeUnit.objects.filter(tenant=tenant, serial_id__in=ids, is_listed=True)
    if store:
        found = found.filter(serial__warehouse_id=store)
    return found.update(is_listed=False, updated_at=timezone.now())


# ── 按數量賣的商品 ──────────────────────────────────────────────────────────
def products_for_sale(tenant):
    return TradeProduct.objects.filter(
        tenant=tenant, is_listed=True, product__is_active=True, product__is_virtual=False).select_related("product__category")


def price_for(trade_product: TradeProduct, partner: TradePartner):
    """這個同行買這個商品的單價(整數元)。固定批發價優先;沒有就是門市售價 × 他的折數。算不出正的 = 不能訂(None)。"""
    if trade_product.price is not None:
        price = trade_product.price
    else:
        price = round_money((trade_product.product.list_price or ZERO) * Decimal(partner.percent) / Decimal("100"))
    return price if price > 0 else None


def set_products(tenant, user, rows) -> int:
    """開放 / 收回幾個商品,或改固定批發價(`rows` = [{product, is_listed?, price?}];price 給 null = 改回照折數算)。"""
    if not isinstance(rows, list) or not rows:
        raise TradeError("沒有要改的")
    if len(rows) > 500:
        raise TradeError("一次最多改 500 個")
    ids = [r.get("product") for r in rows if isinstance(r, dict)]
    if len(ids) != len(rows) or any(isinstance(i, bool) or not isinstance(i, int) for i in ids) or len(set(ids)) != len(ids):
        raise TradeError("要改的內容不對")
    products = {p.id: p for p in Product.objects.filter(tenant=tenant, pk__in=ids).select_related("condition")}
    done = 0
    for row in rows:
        product = products.get(row["product"])
        if product is None:
            raise TradeError("有一個商品找不到")
        if product.is_virtual:
            raise TradeError(f"「{product.name}」是虛擬商品,不能批發")
        if is_unit_product(product):
            raise TradeError(f"「{product.name}」是一台一筆賣的(中古機 / 已拆封),請用上架")
        current = TradeProduct.objects.filter(tenant=tenant, product=product).first()
        fields = {"updated_by": user}
        if "is_listed" in row:
            if not isinstance(row["is_listed"], bool):
                raise TradeError("要改的內容不對")
            fields["is_listed"] = row["is_listed"]
        if "price" in row:
            fields["price"] = clean_price(row["price"], f"「{product.name}」")
        if current is None:
            TradeProduct.objects.create(tenant=tenant, product=product, **{"is_listed": True, **fields})
        else:
            for name, value in fields.items():
                setattr(current, name, value)
            current.save(update_fields=[*fields, "updated_at"])
        done += 1
    return done


def available_qty(tenant, product_ids) -> dict[int, int]:
    """這幾個按數量賣的商品現在還訂得到幾個 = 各門市在庫的合計 − 已經被批發單訂走還沒出的。不會是負的。"""
    product_ids = list(product_ids)
    if not product_ids:
        return {}
    have = {pid: 0 for pid in product_ids}
    for row in StockBalance.objects.filter(tenant=tenant, product_id__in=product_ids, warehouse__is_active=True) \
            .values("product_id").annotate(n=Sum("qty")):
        have[row["product_id"]] += row["n"] or 0
    for row in ProductSerial.objects.filter(
            tenant=tenant, product_id__in=product_ids, status=ProductSerial.Status.IN_STOCK, warehouse__is_active=True) \
            .values("product_id").annotate(n=Count("id")):
        have[row["product_id"]] += row["n"]
    for row in TradeOrderLine.objects.filter(
            tenant=tenant, product_id__in=product_ids, unit__isnull=True, order__status__in=OPEN_STATES) \
            .values("product_id").annotate(n=Sum(F("qty") - F("shipped_qty") - F("cancelled_qty"))):
        have[row["product_id"]] -= row["n"] or 0
    return {pid: max(n, 0) for pid, n in have.items()}
