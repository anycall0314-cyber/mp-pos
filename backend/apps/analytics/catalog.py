"""報表的唯一定義:有哪些指標、可以用哪些角度切。

新的報表需求 = 組合這裡的「指標 × 角度 × 條件」,不是寫新的報表頁、也不是寫新的查詢。
報表畫面與自然語言查詢都只能送「查詢單」(見 engine.py),由這裡的定義決定怎麼算 ——
同一個問題只會有一種數字。

要加指標:在對應的事實表加一個 Base(或用現有指標組一個 Derived)。
要加角度:在 DIMENSIONS 加一個 Dim,並在支援它的事實表的 paths 寫怎麼取。
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Dim:
    key: str
    label: str
    kind: str                 # date | ref(編號 + 名稱)| choice(代碼)| flag(是 / 否)
    labels: object = None     # choice 一定要有:callable(tenant) -> {代碼: 名稱};條件只接受這裡列得出來的代碼
    flag_labels: tuple = ()   # flag:(是的名稱, 否的名稱)
    model: str = ""           # ref:這個角度是哪一張表(條件的名稱查詢與「只認自己公司」用)
    key_field: str = "code"   # ref:那張表裡不會變的代碼(存報表用;編號在還原備份後會換)


@dataclass(frozen=True)
class Path:
    """某張事實表怎麼取到某個角度。"""
    value: str = ""           # 分組用的欄位(編號 / 代碼 / 是否)
    label: str = ""           # ref:名稱欄位
    const: tuple = ()         # 固定值:(值, 名稱),例如資料來源
    none_label: str = "(未指定)"


@dataclass(frozen=True)
class Base:
    """直接從一張事實表加總出來的指標。"""
    key: str
    label: str
    fact: str
    expr: object              # callable() -> 聚合運算式
    fmt: str = "money"        # money | int
    scale: Decimal = Decimal("1")
    hidden: bool = False      # 只給別的指標用,不出現在選單
    roles: tuple = ()         # 誰看得到;空 = 所有登入的人(目前不鎖)
    group: str = ""           # 選單裡歸在哪一類;空 = 照事實表的名稱


@dataclass(frozen=True)
class Derived:
    """由別的指標算出來的。fn 拿到 {指標: 數字},回傳數字或 None(算不出來)。"""
    key: str
    label: str
    deps: tuple
    fn: object
    fmt: str = "money"        # money | int | pct
    roles: tuple = ()
    group: str = "銷貨"


@dataclass
class Fact:
    key: str
    label: str
    queryset: object          # callable(tenant) -> QuerySet(已限定公司、已排除作廢)
    date: str
    paths: dict = field(default_factory=dict)
    as_of: bool = False       # 不能跨日加總(庫存):只看期間內最後一次
    # as_of 才需要:callable(tenant) -> 「哪幾天有記錄過」的 QuerySet(日期欄位名稱跟 date 一樣)。
    # 最後一次是哪一天要看這張,不能看明細:數量是 0 的不會有明細,只看明細會退回去拿到舊的數量。
    days: object = None


def _payment_labels(tenant):
    """現在的付款方式,加上「單據上用過、但主檔已經刪掉」的代碼。

    付款方式可以刪,但收款 / 退款的單據上還留著當時的代碼。只看主檔的話,刪掉之後那些錢在報表裡
    篩不到、存好的報表也打不開。名稱跟著主檔一起沒了,所以只能顯示代碼。
    """
    from apps.sales.models import SalesOrderPayment, SalesReturn
    from apps.tenants.models import PaymentMethod

    names = dict(PaymentMethod.objects.filter(tenant=tenant).values_list("code", "name"))
    used = set(SalesOrderPayment.objects.filter(tenant=tenant)
               .order_by().values_list("method", flat=True).distinct())
    used |= set(SalesReturn.objects.filter(tenant=tenant)
                .order_by().values_list("payment_method", flat=True).distinct())
    for code in sorted(used - set(names) - {""}):
        names[code] = f"{code}(已刪除)"
    return names


def _tax_labels():
    from apps.sales.models import SalesOrder

    return dict(SalesOrder.TaxMethod.choices)


def _legacy_type_labels():
    """舊 POS 的單別。匯入時不認得的單別會被擋下,所以清單就是這幾個;
    舊系統沒有留單別的中文名稱,只標它對淨額是加還是減。"""
    from apps.legacy.models import NET_SIGN

    return {code: f"{code}({'加項' if sign > 0 else '減項'})" for code, sign in NET_SIGN.items()}


def _state_labels():
    from apps.ledger.models import StockSnapshot

    return dict(StockSnapshot.State.choices)


def _plan_kind_labels():
    from apps.parties.models import TelecomPlan

    return dict(TelecomPlan.Kind.choices)


def _contract_state_labels():
    from apps.sales.contracts import STATE_LABELS

    return dict(STATE_LABELS)


DIMENSIONS = {d.key: d for d in [
    Dim("date", "日期", "date"),
    Dim("warehouse", "門市", "ref", model="inventory.Warehouse"),
    Dim("category", "品類", "ref", model="catalog.Category"),
    Dim("brand", "品牌", "ref", model="catalog.Brand"),
    Dim("product", "商品", "ref", model="catalog.Product", key_field="sku"),
    Dim("condition", "新機 / 中古", "flag", flag_labels=("中古", "新品")),
    Dim("item_kind", "商品 / 帳務項目", "flag", flag_labels=("帳務 / 服務項目", "商品")),
    Dim("product_kind", "商品 / 零件", "choice", labels=lambda tenant: {"product": "商品", "parts": "零件"}),
    Dim("sales_person", "業務員", "ref", model="parties.SalesPerson"),
    Dim("supplier", "供應商", "ref", model="parties.Supplier"),
    Dim("payment_method", "付款方式", "choice", labels=_payment_labels),
    Dim("tax_method", "課稅別", "choice", labels=lambda tenant: _tax_labels()),
    Dim("stock_state", "庫存狀態", "choice", labels=lambda tenant: _state_labels()),
    Dim("legacy_doc_type", "舊單別", "choice", labels=lambda tenant: _legacy_type_labels()),
    Dim("source", "資料來源", "choice", labels=lambda tenant: {"mp": "新系統", "legacy": "舊 POS"}),
    # 門號合約(只有「門號合約」那一組指標用得到)
    Dim("carrier", "電信業者", "ref", model="parties.Carrier"),
    Dim("plan_kind", "方案種類", "choice", labels=lambda tenant: _plan_kind_labels()),
    Dim("contract_state", "合約處理狀況", "choice", labels=lambda tenant: _contract_state_labels()),
]}

GRAINS = {"day": "日", "week": "週", "month": "月", "quarter": "季", "year": "年"}


def _product_paths(prefix="", none_label="(未指定)"):
    """商品相關的角度(商品 / 品類 / 品牌 / 新舊 / 商品或帳務項目)。prefix = 怎麼走到商品那一列。"""
    p = f"{prefix}__" if prefix else ""
    return {
        "product": Path(f"{p}product_id", f"{p}product__name", none_label=none_label),
        "category": Path(f"{p}product__category_id", f"{p}product__category__name",
                         none_label=none_label),
        "brand": Path(f"{p}product__brand_id", f"{p}product__brand__name", none_label=none_label),
        "condition": Path(f"{p}product__is_secondhand", none_label=none_label),
        "item_kind": Path(f"{p}product__is_virtual", none_label=none_label),
        "product_kind": Path(f"{p}product__warehouse_type", none_label=none_label),
    }


def _sales(tenant):
    from apps.sales.models import SalesOrderItem

    return SalesOrderItem.objects.filter(tenant=tenant, so__is_void=False)


def _contracts(tenant):
    # 門號合約:哪些算數(作廢、被退掉的不算)、哪一筆已經續約,規則只有 apps/sales/contracts.py 那一份
    from apps.sales.contracts import contracts

    return contracts(tenant)


def _returns(tenant):
    from apps.sales.models import SalesReturnItem

    return SalesReturnItem.objects.filter(tenant=tenant, sr__is_void=False)


def _purchases(tenant):
    from apps.purchasing.models import PurchaseOrderItem

    return PurchaseOrderItem.objects.filter(tenant=tenant, po__is_void=False)


def _payments(tenant):
    from apps.sales.models import SalesOrderPayment

    return SalesOrderPayment.objects.filter(tenant=tenant, so__is_void=False)


def _refunds(tenant):
    from apps.sales.models import SalesReturn

    return SalesReturn.objects.filter(tenant=tenant, is_void=False)


def _stock(tenant):
    from apps.ledger.models import StockSnapshot

    return StockSnapshot.objects.filter(tenant=tenant)


def _stock_days(tenant):
    from apps.ledger.models import StockSnapshotDay

    return StockSnapshotDay.objects.filter(tenant=tenant)


def _legacy(tenant):
    from apps.legacy.models import LegacyItem

    return LegacyItem.objects.filter(tenant=tenant)


NEW = Path(const=("mp", "新系統"))

FACTS = {f.key: f for f in [
    Fact("sales", "銷貨", _sales, "so__doc_date", {
        "warehouse": Path("so__warehouse_id", "so__warehouse__name"),
        "sales_person": Path("so__sales_person_id", "so__sales_person__name"),
        "tax_method": Path("so__tax_method"),
        "source": NEW,
        **_product_paths(),
    }),
    Fact("returns", "銷退", _returns, "sr__doc_date", {
        "warehouse": Path("sr__warehouse_id", "sr__warehouse__name"),
        "sales_person": Path("sr__original_so__sales_person_id", "sr__original_so__sales_person__name"),
        "tax_method": Path("sr__original_so__tax_method"),
        "source": NEW,
        **_product_paths(),
    }),
    Fact("purchases", "進貨", _purchases, "po__doc_date", {
        "warehouse": Path("po__warehouse_id", "po__warehouse__name"),
        "supplier": Path("po__supplier_id", "po__supplier__name"),
        "source": NEW,
        **_product_paths(),
    }),
    Fact("payments", "收款", _payments, "so__doc_date", {
        "warehouse": Path("so__warehouse_id", "so__warehouse__name"),
        "sales_person": Path("so__sales_person_id", "so__sales_person__name"),
        "payment_method": Path("method"),
        "source": NEW,
    }),
    Fact("refunds", "退款", _refunds, "doc_date", {
        "warehouse": Path("warehouse_id", "warehouse__name"),
        "sales_person": Path("original_so__sales_person_id", "original_so__sales_person__name"),
        "payment_method": Path("payment_method"),
        "source": NEW,
    }),
    Fact("stock", "庫存", _stock, "business_date", {
        "warehouse": Path("warehouse_id", "warehouse__name", none_label="調撥中(未指定門市)"),
        "stock_state": Path("state"),
        "source": NEW,
        **_product_paths(),
    }, as_of=True, days=_stock_days),
    # 門號合約:日期是「合約到期日」(不是賣出去那一天)—— 看的是哪個月有幾筆要到期
    Fact("contracts", "門號合約", _contracts, "contract_end", {
        "warehouse": Path("so__warehouse_id", "so__warehouse__name"),
        "sales_person": Path("so__sales_person_id", "so__sales_person__name"),
        "carrier": Path("telecom_plan__carrier_id", "telecom_plan__carrier__name"),
        "plan_kind": Path("telecom_plan__kind"),
        "contract_state": Path("state"),
        "source": NEW,
    }),
    # 舊 POS:門市 / 商品 / 業務員走對照表(人確認過才有值),沒對到的歸「未對照」
    Fact("legacy", "舊 POS", _legacy, "document__document_date", {
        "warehouse": Path("document__store_map__warehouse_id",
                          "document__store_map__warehouse__name", none_label="未對照"),
        "sales_person": Path("salesperson_map__sales_person_id",
                             "salesperson_map__sales_person__name", none_label="未對照"),
        "legacy_doc_type": Path("document__document_type_raw"),
        "source": Path(const=("legacy", "舊 POS")),
        **_product_paths("product_map", none_label="未對照"),
    }),
]}


# 「銷售」只算計入毛利的明細:收購二手那一類(只算現金、不算毛利)不是營收,另外一欄看。
# 這樣 銷售額 − 成本 = 毛利,三個數字是同一批明細。
COUNTED = Q(product__counts_margin=True)
# 只有管理員看得到的指標(公司實際拿的佣金、之後的實際成本)
MANAGERS = ("tenant_admin", "platform_admin")

BASES = [
    Base("sales_untaxed", "銷售額(未稅)", "sales", lambda: Sum("untaxed_amount", filter=COUNTED)),
    Base("sales_gross", "銷售額(含稅)", "sales",
         lambda: Sum(F("untaxed_amount") + F("tax_amount"), filter=COUNTED)),
    Base("sales_qty", "銷量", "sales", lambda: Sum("qty", filter=COUNTED), "int"),
    Base("sales_cost", "銷貨成本", "sales", lambda: Sum("cost_at_post", filter=COUNTED), group="毛利"),
    # 業務員成本(owner 2026-10-09;算獎金看的毛利用的):成交當下記在明細上的數字,不是現在的規則。
    # 沒有記的舊單 = 實際成本(owner:沒設定就用實際成本算),所以沒設定規則時 業務員毛利 = 毛利
    Base("sales_staff_cost", "業務員成本", "sales",
         lambda: Sum(Coalesce("staff_cost", "cost_at_post"), filter=COUNTED), group="毛利"),
    Base("sales_orders", "銷貨單數", "sales",
         lambda: Count("so_id", distinct=True, filter=COUNTED), "int"),
    Base("non_margin_amount", "不計毛利金額(收購等)", "sales",
         lambda: Sum("untaxed_amount", filter=~COUNTED), group="毛利"),
    # 門號的兩個佣金(owner 2026-10-09):成交當下記在明細上的數字,不是方案現在的設定。
    # 公司佣金只有管理員選得到;開單當時方案沒設定的那幾筆是空的,不算進合計(不當成 0 元的佣金,但加總看不出差別)
    Base("staff_commission", "門號業務員佣金", "sales", lambda: Sum("commission"), group="佣金"),
    Base("company_commission", "門號公司佣金", "sales", lambda: Sum("company_commission"),
         roles=MANAGERS, group="佣金"),

    Base("return_untaxed", "銷退額(未稅)", "returns", lambda: Sum("untaxed_amount", filter=COUNTED)),
    Base("return_qty", "銷退量", "returns", lambda: Sum("qty", filter=COUNTED), "int"),
    Base("return_cost", "沖回成本", "returns", lambda: Sum("cost_at_post", filter=COUNTED)),
    Base("return_staff_cost", "沖回業務員成本", "returns",
         lambda: Sum(Coalesce("staff_cost", "cost_at_post"), filter=COUNTED)),
    Base("return_orders", "銷退單數", "returns",
         lambda: Count("sr_id", distinct=True, filter=COUNTED), "int"),

    # 進貨金額 = 記進庫存的成本(未稅單位成本 × 數量),跟庫存金額、加權平均成本是同一個數字。
    # 單位成本存到分,有贈品或除不盡時,跟進貨單頭的未稅小計可能差幾分錢(進貨明細沒有存死每行未稅)。
    Base("purchase_untaxed", "進貨金額(未稅)", "purchases",
         lambda: Sum(F("unit_landed_cost") * F("qty"))),
    Base("purchase_qty", "進貨數量", "purchases", lambda: Sum("qty"), "int"),

    Base("received", "收款", "payments", lambda: Sum("amount")),
    Base("refunded", "退款", "refunds", lambda: Sum("total"), group="收款"),

    Base("stock_qty", "庫存數量", "stock", lambda: Sum("qty"), "int"),
    Base("stock_value", "庫存金額", "stock", lambda: Sum("cost_value")),

    # 期間 = 合約到期日落在哪一段。已經續約 / 不續約的也算在裡面,要分開看就用「合約處理狀況」分組
    Base("contracts_due", "到期門號數", "contracts", lambda: Count("id"), "int"),

    Base("legacy_raw", "舊 POS 原始額", "legacy", lambda: Sum("amount_minor"), scale=CENT),
    Base("legacy_net", "舊 POS 淨額", "legacy",
         lambda: Sum(F("amount_minor") * F("net_sign")), scale=CENT),
    # 舊系統的「未稅額」欄位不用:多數明細等於金額、約 7% 是金額 / 1.05,而且退貨類單據的未稅額
    # 已經自帶負號(金額沒有),語意不一致。只用跟封存核對過的金額(原始額 / 淨額)。
    Base("legacy_lines", "舊 POS 筆數", "legacy", lambda: Count("id"), "int"),
]


def _ratio(num, den):
    return None if not den else num / den


DERIVED = [
    Derived("net_sales", "淨銷售額(未稅)", ("sales_untaxed", "return_untaxed"),
            lambda v: v["sales_untaxed"] - v["return_untaxed"]),
    Derived("net_qty", "淨銷量", ("sales_qty", "return_qty"),
            lambda v: v["sales_qty"] - v["return_qty"], "int"),
    Derived("sales_profit", "銷貨毛利(未扣銷退)", ("sales_untaxed", "sales_cost"),
            lambda v: v["sales_untaxed"] - v["sales_cost"], group="毛利"),
    Derived("gross_profit", "毛利(扣銷退)",
            ("sales_untaxed", "sales_cost", "return_untaxed", "return_cost"),
            lambda v: (v["sales_untaxed"] - v["sales_cost"])
            - (v["return_untaxed"] - v["return_cost"]), group="毛利"),
    Derived("margin_rate", "毛利率",
            ("sales_untaxed", "sales_cost", "return_untaxed", "return_cost"),
            lambda v: _ratio(
                (v["sales_untaxed"] - v["sales_cost"]) - (v["return_untaxed"] - v["return_cost"]),
                v["sales_untaxed"] - v["return_untaxed"],
            ), "pct", group="毛利"),
    # 業務員毛利 = 未稅金額 − 業務員成本(跟上面的毛利同一批明細,只是成本換成加權過的那一個)
    Derived("staff_profit", "業務員毛利(未扣銷退)", ("sales_untaxed", "sales_staff_cost"),
            lambda v: v["sales_untaxed"] - v["sales_staff_cost"], group="毛利"),
    Derived("staff_gross_profit", "業務員毛利(扣銷退)",
            ("sales_untaxed", "sales_staff_cost", "return_untaxed", "return_staff_cost"),
            lambda v: (v["sales_untaxed"] - v["sales_staff_cost"])
            - (v["return_untaxed"] - v["return_staff_cost"]), group="毛利"),
    Derived("avg_ticket", "客單價", ("sales_gross", "sales_orders"),
            lambda v: _ratio(v["sales_gross"], v["sales_orders"])),
    Derived("net_received", "實收", ("received", "refunded"),
            lambda v: v["received"] - v["refunded"], group="收款"),
    # 新舊系統放在同一條時間軸:新系統的未稅淨銷售額 + 舊 POS 的淨額(舊系統報表值)
    Derived("all_sales", "全期銷售額(新系統 + 舊 POS)",
            ("sales_untaxed", "return_untaxed", "legacy_net"),
            lambda v: v["sales_untaxed"] - v["return_untaxed"] + v["legacy_net"]),
]

MEASURES = {m.key: m for m in [*BASES, *DERIVED]}
GROUPS = ["銷貨", "毛利", "佣金", "銷退", "進貨", "收款", "庫存", "門號合約", "舊 POS"]


def group_of(measure):
    return measure.group or FACTS[measure.fact].label


def base_keys(measure_key):
    """這個指標最後要從哪些基本指標算。"""
    m = MEASURES[measure_key]
    if isinstance(m, Base):
        return [m.key]
    out = []
    for dep in m.deps:
        out += base_keys(dep)
    return out


def may_see(measure_key, role) -> bool:
    """這個角色看不看得到這個指標。**算它要用到的每一個基本指標也都要看得到**:
    不然另外定一個「由公司佣金算出來的」指標、忘了寫 roles,店員就看得到了。"""
    m = MEASURES[measure_key]
    if m.roles and role not in m.roles:
        return False
    return all(
        not MEASURES[k].roles or role in MEASURES[k].roles for k in base_keys(measure_key)
    )


def supported_dims(measure_key):
    """這個指標可以用哪些角度切(用到的每一張事實表都要支援)。"""
    facts = {MEASURES[k].fact for k in base_keys(measure_key)}
    dims = None
    for fact in facts:
        keys = set(FACTS[fact].paths) | {"date"}
        dims = keys if dims is None else dims & keys
    return dims or set()
