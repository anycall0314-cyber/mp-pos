"""中古機的價目表(owner 2026-10-14:「型號成色電池都可能會決定價格」「批次全選,再取消部分勾選獨立定價」「改價紀錄也要」)。

- **一格** = 型號 + 成色(空的 = 不分)+ 電池區間(0–100 = 不限)+ 有沒有備註(空的 = 不分)→ 一個價(`TradePriceRule`)。
  備註 = 特殊狀況(owner:「特殊狀況特殊價」):「沒備註的 A 級 12,000」是一格,有備註的不在這一格裡。
- **全公司符合那一格的每一台都用那個價**(不看畫面上列了哪幾台、哪一間門市):那一格改了它們跟著變,新進貨的自動跟。
  只有被明講**獨立定價**的(`TradeUnit.own_price`)不跟。紅隊:不這樣的話,價目表寫 12,000、庫裡同型號同機況卻新舊價混在一起。
- 兩格都符合同一台 → **比較細的那一格算數**:先比有沒有指定成色,再比有沒有限電池,再比有沒有指定備註(`rank`)。
  一樣細的兩格(同成色、同備註、都有限電池)電池區間不可以重疊(存的時候擋)—— 所以不會有兩格一樣細又都符合。
- 價錢仍然存在 `TradeUnit.price`:改一格的時候把跟著的一起改掉(`reprice`)。下單、對外看到的都讀那一個,不用每次算。
- 每一次動到價錢記一筆(`record`):誰、什麼時候、哪一群、每一台從多少變多少。
"""
from apps.inventory.models import ProductSerial

from .base import TradeError
from .models import TradePriceChange, TradePriceChangeUnit, TradePriceRule, TradeUnit

GRADES = set(ProductSerial.ConditionGrade.values)
NOTED = {"", "no", "yes"}
# 排給人看的順序:S 到 D,不分成色的那一格放最後
GRADE_ORDER = {grade: at for at, grade in enumerate(["S", "A", "B", "C", "D", ""])}


def bounded(rule) -> bool:
    return (rule.battery_min, rule.battery_max) != (0, 100)


def rank(rule) -> tuple:
    return (bool(rule.grade), bounded(rule), bool(rule.noted))


def fits(rule, serial) -> bool:
    if rule.grade and serial.condition_grade != rule.grade:
        return False
    # 沒記電池的那一台不算在任何「有限電池」的格子裡(不知道是幾 %)
    if bounded(rule) and (serial.battery_health is None or not rule.battery_min <= serial.battery_health <= rule.battery_max):
        return False
    if rule.noted and (rule.noted == "yes") != bool((serial.condition_note or "").strip()):
        return False
    return True


def best(rules, serial):
    """符合這一台的格子裡最細的那一格;都不符合回 None。"""
    found = None
    for rule in rules:
        if fits(rule, serial) and (found is None or rank(rule) > rank(found)):
            found = rule
    return found


def cell_text(grade: str, battery_min: int, battery_max: int, noted: str = "") -> str:
    """給人看的一格:「A 級 電池 85 以上 沒備註」「A 級」「電池 79 以下」「全部」。"""
    parts = [f"{grade} 級"] if grade else []
    if (battery_min, battery_max) != (0, 100):
        if battery_max == 100:
            parts.append(f"電池 {battery_min} 以上")
        elif battery_min == 0:
            parts.append(f"電池 {battery_max} 以下")
        else:
            parts.append(f"電池 {battery_min}–{battery_max}")
    if noted:
        parts.append("有備註" if noted == "yes" else "沒備註")
    return " ".join(parts) or "全部"


def text_of(rule) -> str:
    return cell_text(rule.grade, rule.battery_min, rule.battery_max, rule.noted)


def clean_cell(raw) -> tuple[str, int, int, str]:
    """畫面送來的一格 → (成色, 電池最低, 電池最高, 備註)。空的成色 / 備註 = 不分;電池沒給 = 不限。"""
    if not isinstance(raw, dict):
        raise TradeError("價目的內容不對")
    grade = raw.get("grade") or ""
    if not isinstance(grade, str) or (grade and grade not in GRADES):
        raise TradeError("價目的成色不對")
    noted = raw.get("noted") or ""
    if not isinstance(noted, str) or noted not in NOTED:
        raise TradeError("價目的備註不對")
    low, high = raw.get("battery_min"), raw.get("battery_max")
    low = 0 if low is None else low
    high = 100 if high is None else high
    for value in (low, high):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise TradeError("電池要填 0 到 100 的整數")
    if low > high:
        raise TradeError("電池最低不能比最高大")
    return grade, low, high, noted


def rules_of(tenant, product_ids) -> dict[int, list[TradePriceRule]]:
    out = {pid: [] for pid in product_ids}
    for rule in TradePriceRule.objects.filter(tenant=tenant, product_id__in=list(out)):
        out[rule.product_id].append(rule)
    return out


def set_rule(tenant, user, product, cell: tuple[str, int, int, str], price) -> TradePriceRule:
    """存一格(有就改價、沒有就建)。跟一樣細的另一格電池區間重疊就擋。不動任何一台 —— 呼叫的人接著 `reprice`。"""
    grade, low, high, noted = cell
    rule = TradePriceRule.objects.filter(tenant=tenant, product=product, grade=grade, battery_min=low, battery_max=high, noted=noted).first()
    if rule is None:
        if (low, high) != (0, 100):
            for other in TradePriceRule.objects.filter(tenant=tenant, product=product, grade=grade, noted=noted):
                if bounded(other) and other.battery_min <= high and low <= other.battery_max:
                    raise TradeError(f"跟「{text_of(other)}」的電池區間重疊")
        return TradePriceRule.objects.create(tenant=tenant, product=product, grade=grade, battery_min=low, battery_max=high, noted=noted,
                                             price=price, updated_by=user)
    if rule.price != price:
        rule.price, rule.updated_by = price, user
        rule.save(update_fields=["price", "updated_by", "updated_at"])
    return rule


def reprice(tenant, product, now) -> list[tuple]:
    """這個型號每一台沒有獨立定價的(在庫、上過架的)照現在的價目重算。回價錢變了的 [(TradeUnit, 原本的價)]。

    沒有任何一格符合的那一台不動(它的價是進貨時照通則算的、或之前那一格留下來的)。下架中的也一起算:再上架的時候價是對的。
    """
    rules = list(TradePriceRule.objects.filter(tenant=tenant, product=product))
    if not rules:
        return []
    changed = []
    for unit in TradeUnit.objects.filter(tenant=tenant, serial__product=product, own_price=False,
                                         serial__status=ProductSerial.Status.IN_STOCK).select_related("serial"):
        rule = best(rules, unit.serial)
        if rule is not None and unit.price != rule.price:
            changed.append((unit, unit.price))
            unit.price, unit.updated_at = rule.price, now
    TradeUnit.objects.bulk_update([unit for unit, _ in changed], ["price", "updated_at"], batch_size=500)
    return changed


def as_entries(changed) -> list[tuple]:
    """`reprice` 動到的 → 改價紀錄的一台一筆。下架中的那幾台也算(畫面上講「全公司用這一格的幾台」,紀錄上的台數要跟它一樣)。"""
    return [(unit.serial, before, unit.price) for unit, before in changed]


def record(tenant, user, product, what, scope: str, entries) -> TradePriceChange | None:
    """記一次改價。`entries` = [(序號, 原本的價或 None, 改成的價或 None)];一台都沒動到就不記。"""
    entries = [e for e in entries if e[1] != e[2]]
    if not entries:
        return None
    old = [e[1] for e in entries if e[1] is not None]
    new = [e[2] for e in entries if e[2] is not None]
    change = TradePriceChange.objects.create(
        tenant=tenant, product=product, what=what, scope=scope[:120], count=len(entries), by=user,
        old_low=min(old) if old else None, old_high=max(old) if old else None,
        new_low=min(new) if new else None, new_high=max(new) if new else None)
    TradePriceChangeUnit.objects.bulk_create(
        [TradePriceChangeUnit(tenant=tenant, change=change, serial=serial, old_price=before, new_price=after) for serial, before, after in entries],
        batch_size=500)
    return change


def followers(tenant, product_id, rules) -> dict[int, int]:
    """每一格現在有幾台跟著(全公司在庫、上過架、沒有獨立定價、而且這一格是符合它的最細的那一格)。"""
    counts = {rule.id: 0 for rule in rules}
    if rules:
        for unit in TradeUnit.objects.filter(tenant=tenant, serial__product_id=product_id, own_price=False,
                                             serial__status=ProductSerial.Status.IN_STOCK).select_related("serial"):
            rule = best(rules, unit.serial)
            if rule is not None:
                counts[rule.id] += 1
    return counts
