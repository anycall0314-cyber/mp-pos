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

from . import pricing
from .base import ZERO, TradeError, setting_of
from .models import TradeOrder, TradeOrderLine, TradePartner, TradePriceRule, TradeProduct, TradeSetting, TradeUnit

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


def _save_unit(tenant, serial, price, user, listed=True, own=False) -> TradeUnit:
    now = timezone.now()
    unit, _ = TradeUnit.objects.update_or_create(
        tenant=tenant, serial=serial,
        defaults={"price": price, "is_listed": listed, "listed_at": now if listed else None, "listed_by": user if listed else None,
                  "own_price": own})
    return unit


def default_price(setting: TradeSetting, rules, serial):
    """沒有人指定價的時候這一台賣多少:價目表上符合它的那一格 → 沒有才是設定的那一條通則。算不出來回 None。"""
    rule = pricing.best(rules, serial)
    return rule.price if rule is not None else auto_price(setting, serial)


def after_intake(tenant, serials, *, user=None, wanted=None) -> int:
    """進貨 / 收購剛建好的幾台:照設定自動上架(owner:中古機要快速進貨就上架)。回上架了幾台。

    `wanted` = {序號編號: {"list": 要不要上架, "price": 批發價}}:表單上個別指定的(沒指定的照設定)。
    沒有開放批發、沒有開「進貨就上架」→ 沒有個別指定要上架的都不動。算不出批發價的那一台不上架(不擋進貨)。
    價:表單上指定的(= 獨立定價)→ 價目表上符合它的那一格 → 設定的通則。
    讀價目之前先鎖這幾個型號(複審 P0:跟客人收購的那一台剛好碰到有人改價目,會用舊價上架、之後也不會被重算)——
    改價目的人也是先鎖型號,兩邊一次一個。新建的這幾台別人還看不到,所以在這裡才鎖型號不會跟誰卡住。
    """
    setting = setting_of(tenant)
    automatic = setting.is_open and setting.auto_list_units
    rules = None
    done = 0
    for serial in serials:
        if not is_unit_product(serial.product):
            continue
        want = (wanted or {}).get(serial.id) or {}
        if not (want.get("list") if want.get("list") is not None else automatic):
            continue
        if rules is None:
            lock_stock_rows(tenant, products=[s.product for s in serials if is_unit_product(s.product)])
            rules = pricing.rules_of(tenant, {s.product_id for s in serials})
        own = bool(want.get("price"))
        price = want["price"] if own else default_price(setting, rules.get(serial.product_id, []), serial)
        if price is None or price <= 0:
            continue
        _save_unit(tenant, serial, price, user, own=own)
        done += 1
    return done


def _save_units(tenant, priced, user) -> tuple[list[TradeUnit], list[tuple]]:
    """把這幾台(`priced` = [(序號, 批發價, 是不是獨立定價)])記成上架。幾百台一起來也只有幾句查詢。

    回 (那幾台, [(序號, 原本的價, 現在的價)]) —— 原本沒在賣的(沒上過架、下架中)原本的價是 None。
    """
    now = timezone.now()
    have = {u.serial_id: u for u in TradeUnit.objects.filter(tenant=tenant, serial_id__in=[serial.id for serial, _, _ in priced])}
    new, old, entries = [], [], []
    for serial, price, own in priced:
        unit = have.get(serial.id)
        if unit is None:
            new.append(TradeUnit(tenant=tenant, serial=serial, price=price, is_listed=True, listed_at=now, listed_by=user, own_price=own))
            entries.append((serial, None, price))
        else:
            entries.append((serial, unit.price if unit.is_listed else None, price))
            unit.price, unit.is_listed, unit.listed_at, unit.listed_by, unit.updated_at = price, True, now, user, now
            unit.own_price = own
            old.append(unit)
    TradeUnit.objects.bulk_create(new, batch_size=500)
    TradeUnit.objects.bulk_update(old, ["price", "is_listed", "listed_at", "listed_by", "own_price", "updated_at"], batch_size=500)
    return new + old, entries


def _not_what_was_seen(serial, seen):
    """畫面說它看的是哪個型號 / 哪一間門市(`seen`);這一台不是的話回要講的話。

    畫面換門市、換型號的那一下,手上可能還是上一份清單(複審 P0:會把上一間門市的整群改掉)。畫面自己會擋,這裡是伺服器這一側的保險。
    """
    if not seen:
        return None
    if seen.get("product") and serial.product_id != seen["product"]:
        return f"{serial.serial_no} 型號不符,請重新整理"
    if seen.get("warehouse") and serial.warehouse_id != seen["warehouse"]:
        return f"{serial.serial_no} 門市不符,請重新整理"
    return None


def _price_table_product(tenant, product_id, store):
    """要改價目的那個型號。價目是全公司的(一改每一間門市符合的都變):鎖在一間門市的人不能改。"""
    if store:
        raise TradeError("沒有改價目的權限")
    product = Product.objects.filter(tenant=tenant, pk=product_id or 0).select_related("condition").first()
    if product is None or not is_unit_product(product):
        raise TradeError("要先選型號")
    return product


def put_on(tenant, user, rows, *, store=None, seen=None, cell=None, cell_price=None) -> list[TradeUnit]:
    """上架 / 改價幾台。只有現在在庫的中古機能上架。

    `rows` 的每一台三種講法:
    - `{serial, price}`:**獨立定價**,就是這個價(之後價目怎麼改都不動它)。
    - `{serial, own: true}`:**獨立定價**,價維持現在的(畫面上取消勾選的那一台;要已經有價)。
    - `{serial}`:**不獨立** → 價目表上符合它的那一格 → 沒有符合的就維持它現在的價 → 沒有價就照設定的通則算(算不出來 → 擋,請填價)。
    `cell` + `cell_price`:順便把價目表的這一格(`{grade, battery_min, battery_max, noted}`)設成這個價(要帶 `seen.product`)。
      這一格改了,**這個型號全公司符合它、沒有獨立定價的在庫機器**都重算(不只送來的這幾台、不只畫面上那一間門市)—— 價目表就是這個意思。
    `store` = 這個人被鎖在哪一間門市(沒鎖給 None):鎖門市的人只能動自己那一間的,也不能改價目。
    `seen` = 畫面看的是哪個型號 / 門市(`{product, warehouse}`,沒給的不查):有一台不是就整批不動。

    **整批一起成立**:有一台不行(剛被賣掉、算不出價)就整批都不動,畫面把那一台講出來 —— 幾百台改到一半停住,
    沒有人知道哪幾台改了。鎖的順序:商品 → 序號,跟進貨、銷貨、批發下單同一個順序;鎖到之後才看在不在庫:剛賣掉的那一台不會被上架回去。
    **送來的每一台的型號都先鎖**(不只改價目的時候;複審 P0):價目改了要把用它的整批重算,這時候另一個人替其中一台定獨立價,
    不鎖型號的話兩邊會互相蓋掉(獨立定價的旗子在、價卻是價目的價)。
    每一次有價錢變了就記一筆改價紀錄。
    """
    rows = [] if rows is None and cell is not None else rows
    if not isinstance(rows, list) or (not rows and cell is None):
        raise TradeError("沒有要上架的")
    if len(rows) > MAX_ROWS:
        raise TradeError(f"一次最多上架 {MAX_ROWS} 台")
    wanted = {}
    for row in rows:
        serial_id = row.get("serial") if isinstance(row, dict) else None
        if isinstance(serial_id, bool) or not isinstance(serial_id, int) or serial_id in wanted:
            raise TradeError("上架的內容不對")
        if row.get("own") not in (None, True, False):
            raise TradeError("上架的內容不對")
        wanted[serial_id] = row
    product = None
    if cell is not None:
        cell = pricing.clean_cell(cell)
        new_price = clean_price(cell_price, "價目")
        if new_price is None:
            raise TradeError("價目要填價")
        product = _price_table_product(tenant, (seen or {}).get("product"), store)
    setting = setting_of(tenant)
    now = timezone.now()
    with transaction.atomic():
        models = set(ProductSerial.objects.filter(tenant=tenant, pk__in=wanted).values_list("product_id", flat=True))
        locked = list(Product.objects.filter(tenant=tenant, pk__in=models | ({product.id} if product else set())))
        lock_stock_rows(tenant, products=locked, serial_ids=list(wanted))
        serials = {s.id: s for s in ProductSerial.objects.filter(tenant=tenant, pk__in=wanted).select_related("product__condition")}
        rule = pricing.set_rule(tenant, user, product, cell, new_price) if cell is not None else None
        rules = pricing.rules_of(tenant, {s.product_id for s in serials.values()})
        have = {u.serial_id: u for u in TradeUnit.objects.filter(tenant=tenant, serial_id__in=wanted)}
        priced = []
        for serial_id, row in wanted.items():
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
            unit = have.get(serial_id)
            price = clean_price(row.get("price"), serial.serial_no)
            if price is not None:
                priced.append((serial, price, True))
            elif row.get("own"):
                if unit is None:
                    raise TradeError(f"{serial.serial_no} 要獨立定價,請填價")
                priced.append((serial, unit.price, True))
            else:
                found = pricing.best(rules.get(serial.product_id, []), serial)
                price = found.price if found is not None else unit.price if unit is not None else auto_price(setting, serial)
                if price is None:
                    raise TradeError(f"{serial.serial_no} 算不出批發價,請填")
                priced.append((serial, price, False))
        done, entries = _save_units(tenant, priced, user)
        by_product = {}
        for serial, before, after in entries:
            by_product.setdefault(serial.product_id, []).append((serial, before, after))
        if rule is not None:
            # 這一格改了:這個型號其他符合的(沒有送來的、別間門市的、下架中的)一起重算
            by_product.setdefault(product.id, []).extend(pricing.as_entries(pricing.reprice(tenant, product, now)))
        What = pricing.TradePriceChange.What
        for product_id, found in by_product.items():
            moved = [e for e in found if e[1] != e[2]]
            if rule is not None and product_id == product.id:
                what, scope, of = What.RULE, pricing.text_of(rule), product
            else:
                what, scope, of = (What.LIST if all(e[1] is None for e in moved) else What.PRICE), "", found[0][0].product
            pricing.record(tenant, user, of, what, scope, found)
        return done


def set_cells(tenant, user, cells, *, store=None) -> int:
    """一次改好幾格價目的價(型號清單那一頁:行情變了,數字當場改、一次存)。`cells` = [{id, price}]。回價錢跟著變的台數。"""
    if not isinstance(cells, list) or not cells:
        raise TradeError("沒有要改的價目")
    if len(cells) > 500:
        raise TradeError("一次最多改 500 格")
    wanted = {}
    for row in cells:
        rule_id = row.get("id") if isinstance(row, dict) else None
        if isinstance(rule_id, bool) or not isinstance(rule_id, int) or rule_id in wanted:
            raise TradeError("價目的內容不對")
        price = clean_price(row.get("price"), "價目")
        if price is None:
            raise TradeError("價目要填價")
        wanted[rule_id] = price
    if store:
        raise TradeError("沒有改價目的權限")
    now = timezone.now()
    total = 0
    with transaction.atomic():
        products = {r.product_id: r.product for r in TradePriceRule.objects.filter(tenant=tenant, pk__in=wanted).select_related("product")}
        lock_stock_rows(tenant, products=list(products.values()))
        rules = {r.id: r for r in TradePriceRule.objects.filter(tenant=tenant, pk__in=wanted).select_related("product")}
        if len(rules) != len(wanted):
            raise TradeError("有一格價目找不到,請重新整理")
        for rule_id in sorted(wanted):
            rule = rules[rule_id]
            if rule.price == wanted[rule_id]:
                continue
            rule.price, rule.updated_by = wanted[rule_id], user
            rule.save(update_fields=["price", "updated_by", "updated_at"])
            entries = pricing.as_entries(pricing.reprice(tenant, rule.product, now))
            pricing.record(tenant, user, rule.product, pricing.TradePriceChange.What.RULE, pricing.text_of(rule), entries)
            total += len(entries)
    return total


def drop_cell(tenant, user, rule_id, *, store=None) -> int:
    """刪掉價目表的一格。原本用它的那幾台改用下一格的價(沒有下一格就維持現在的價)。回價錢變了的台數。"""
    if store:
        raise TradeError("沒有改價目的權限")
    found = TradePriceRule.objects.filter(tenant=tenant, pk=rule_id).select_related("product").first()
    if found is None:
        raise TradeError("找不到這一格價目", status=404)
    now = timezone.now()
    with transaction.atomic():
        lock_stock_rows(tenant, products=[found.product])
        rule = TradePriceRule.objects.filter(tenant=tenant, pk=rule_id).first()
        if rule is None:
            raise TradeError("找不到這一格價目", status=404)
        scope = pricing.text_of(rule)
        rule.delete()
        entries = pricing.as_entries(pricing.reprice(tenant, found.product, now))
        pricing.record(tenant, user, found.product, pricing.TradePriceChange.What.DROP, scope, entries)
    return len(entries)


def take_off(tenant, user, serial_ids, *, store=None, seen=None) -> int:
    """下架。已經被訂走的那一台不受影響(那張單還是訂著它)。`store`、`seen` 同 `put_on`。價與跟不跟價目都留著(之後再上架用得到)。"""
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
    with transaction.atomic():
        found = TradeUnit.objects.filter(tenant=tenant, serial_id__in=ids, is_listed=True)
        if store:
            found = found.filter(serial__warehouse_id=store)
        units = list(found.select_related("serial__product"))
        by_product = {}
        for unit in units:
            by_product.setdefault(unit.serial.product_id, []).append((unit.serial, unit.price, None))
        done = TradeUnit.objects.filter(pk__in=[u.pk for u in units], is_listed=True).update(is_listed=False, updated_at=timezone.now())
        for entries in by_product.values():
            pricing.record(tenant, user, entries[0][0].product, pricing.TradePriceChange.What.UNLIST, "", entries)
        return done


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
