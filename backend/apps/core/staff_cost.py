"""業務員成本:算獎金看的毛利用的成本(實際成本加上公司定的加成)。規則只有這一份。

owner 2026-10-09:
- 全公司一條(系統設定)+ 個別商品另設;商品自己有設就用商品的,沒有才用全公司的。
- 兩邊都沒設定 = 實際成本(跟以前一樣)。
- 加成的基準:一般商品用商品的平均成本,中古機用那一台自己的成本。
- 實際成本不受影響(`cost_at_post`、加權平均照舊),這裡只是另外算一個數字;
  「業務員毛利 = 未稅金額 − 業務員成本」。

這一支不碰資料庫:給它商品、公司(各有 `staff_cost_mode` / `staff_cost_value`)與成本,它回數字。
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")
ZERO = Decimal("0")

FIXED, PLUS, PERCENT = "fixed", "plus", "percent"
KNOWN = (FIXED, PLUS, PERCENT)
# 選項的字數一樣(owner:同一排的選項等長)
PRODUCT_MODES = [("", "照全公司"), (FIXED, "固定金額"), (PLUS, "加固定額"), (PERCENT, "加百分比")]
COMPANY_MODES = [("", "尚未設定"), (PLUS, "加固定額"), (PERCENT, "加百分比")]


def cents(value) -> Decimal:
    """收到分、四捨五入(這裡的數字都用這一個,設定存檔也是)。"""
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


_cents = cents


@dataclass(frozen=True)
class Rule:
    source: str          # "product" = 商品自己設的;"company" = 全公司的那一條
    mode: str
    value: Decimal

    def one(self, base) -> Decimal:
        """一件的業務員成本。base = 這一件的成本(固定金額不看它)。"""
        if self.mode == FIXED:
            return _cents(self.value)
        if self.mode == PLUS:
            return _cents(Decimal(base) + self.value)
        return _cents(Decimal(base) * (Decimal("100") + self.value) / Decimal("100"))

    @property
    def text(self) -> str:
        """記在銷貨明細上的那一句:當時用的是哪一條。"""
        return f"{self.source}:{self.mode}:{_cents(self.value)}"


# owner 2026-10-10:「目前帶序號的產品先不做業務員成本,先針對一般商品」。
# 帶序號的(手機、中古機…)一律當成沒有規則 = 實際成本,商品上也不存設定。
# 之後要做再把這個開關打開:「一般的手機用平均成本、中古機用那一台自己的成本」那兩段都還在、測試也留著。
SERIAL_GOODS_TOO = False


def rule_for(product, tenant) -> Rule | None:
    """這個商品現在適用哪一條;兩邊都沒設定回 None(= 用實際成本)。"""
    # 中古機存檔時一定會被標成帶序號;這裡兩個都看,繞過存檔直接改資料庫留下的「中古但沒標帶序號」也不加
    if not SERIAL_GOODS_TOO and (getattr(product, "requires_serial", False) or getattr(product, "is_secondhand", False)):
        return None
    # 只認這三種;資料庫裡萬一是別的字(只有直接改資料庫才會),當成沒有設定,不拿去亂算
    mode = getattr(product, "staff_cost_mode", "") or ""
    if mode in KNOWN:
        return Rule("product", mode, Decimal(product.staff_cost_value or 0))
    mode = getattr(tenant, "staff_cost_mode", "") or ""
    if mode in KNOWN:
        return Rule("company", mode, Decimal(tenant.staff_cost_value or 0))
    return None


def shown_unit_cost(product, tenant, own_cost=None) -> Decimal:
    """畫面上看的「一件的業務員成本」(還沒成交;成交時記下來的以 `line_cost` 為準)。

    own_cost 有給 = 中古機的某一台,拿那一台自己的成本當基準。
    """
    if product.is_virtual:
        return ZERO
    base = Decimal(product.weighted_avg_cost or 0)
    if own_cost is not None and product.is_secondhand:
        base = Decimal(own_cost or 0)
    rule = rule_for(product, tenant)
    return _cents(base) if rule is None else rule.one(base)


def line_cost(product, tenant, *, qty, actual_cost, unit_costs=()) -> tuple[Decimal, str]:
    """成交時這一行的業務員成本(整行,不是一件)與當時用的規則。

    actual_cost = 這一行的實際成本(`cost_at_post`);unit_costs = 這一行每一台自己的成本(序號商品)。
    """
    actual_cost = _cents(actual_cost or 0)
    if product.is_virtual:
        return ZERO, ""
    rule = rule_for(product, tenant)
    if rule is None:
        return actual_cost, ""
    qty = Decimal(qty)
    if rule.mode == FIXED:
        return _cents(rule.one(ZERO) * qty), rule.text
    unit_costs = list(unit_costs)
    if product.is_secondhand and unit_costs:
        # 中古機每一台成本不同:各自加成再加總
        return _cents(sum((rule.one(c or 0) for c in unit_costs), ZERO)), rule.text
    average = Decimal(product.weighted_avg_cost or 0)
    if average > 0:
        return _cents(rule.one(average) * qty), rule.text
    # 平均成本沒有記到(0):拿這一次實際的成本當基準,不然業務員成本會是 0、毛利虛高
    if rule.mode == PLUS:
        return _cents(actual_cost + rule.value * qty), rule.text
    return _cents(actual_cost * (Decimal("100") + rule.value) / Decimal("100")), rule.text


def check(mode, value, modes) -> str | None:
    """設定對不對;有問題回一句話,沒問題回 None。"""
    if not isinstance(mode, str) or mode not in {m for m, _ in modes}:
        return "沒有這種算法"
    if value is None:
        # 有選算法就要有數字:只送算法、數字留著原本的 0,「固定金額」會變成業務員成本 0、毛利等於整筆金額
        return "請填數字" if mode else None
    if Decimal(value) < 0:
        return "不能是負的"
    return None
