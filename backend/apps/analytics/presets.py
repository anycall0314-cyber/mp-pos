"""固定的報表(員工帳號權限第三批,owner 2026-10-10):業績彙總、商品排行、每日彙總;2026-10-12 多客戶排行。

內容由伺服器定,畫面只選日期與門市;數字全部走 `engine`(指標怎麼算只有 `catalog.py` 那一份),
這裡只決定「哪幾欄、照什麼分、欄名叫什麼」。

三張的數字都是**扣掉銷退之後**的(退的那一天扣回去),所以跟銷貨日報的合計對不起來是正常的 ——
銷貨日報不列銷退(動手前紅隊第 2 條)。「毛利加佣金」= 銷貨單清單上每張單的「業務員毛利」(那裡含門號佣金)加起來、
再扣掉銷退(紅隊第 1 條)。個人收購那種不算毛利的單不算在裡面;整列都是 0 的不列(紅隊第 3 條:
不然沒有業務員的收購單會變成一列「(未指定)」)。
"""
from dataclasses import dataclass
from decimal import Decimal

from rest_framework.exceptions import PermissionDenied

from apps.tenants import abilities
from apps.tenants.permissions import is_tenant_admin

from . import engine
from .catalog import MANAGERS, PLAN_KINDS


@dataclass(frozen=True)
class Col:
    key: str                # catalog 裡的指標
    label: str              # 這張報表上的欄名
    managers: bool = False  # 只給管理員的欄(公司佣金本來就只有管理員拿得到;實際毛利跟銷貨單清單一樣只列給管理員)


@dataclass(frozen=True)
class Basis:
    """同一張報表的另一種看法:期間改看別的日期(欄換成那個日期的那一組指標)。"""
    key: str                # 網址的 ?date=
    label: str              # 下拉上的字(同一張報表的幾種字數一樣)
    cols: tuple
    sort: str = ""
    note: str = ""
    pending: object = None  # callable(tenant, 門市編號或 None) -> 一句話或 "":還沒有這個日期、所以哪一段期間都不算的有多少


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    ability: str            # 員工帳號頁的哪一個勾;MANAGERS_ONLY = 沒有勾,只有管理員看得到
    by: dict                # 網址的 ?by= → 照哪個角度分(第一個是預設)
    cols: tuple
    sort: str = ""
    grain: str = "month"
    keep: int = engine.MAX_ROWS     # 最多列幾列
    max_days: int = 0               # 期間最長幾天(0 = 照引擎的上限)
    note: str = "已扣銷退"            # 期間旁邊那幾個字:這張表的數字扣了什麼(畫面不自己寫死)
    # 期間可以改看別的日期(開通統計:上線日)。上面的 cols / sort / note 是預設那一種,它在下拉上叫 date_label
    date_label: str = ""
    dates: tuple = ()


MANAGERS_ONLY = ""


def _lines_without_start(tenant, warehouse_id):
    """門號那一行還沒有填上線日的有幾門(不管哪一天開的單;動手前紅隊第 2 條:要在老闆正在看的那一段就看得到,
    不是掛在開單那個月的表尾)。作廢的單、已經整張退掉的不算(退掉的那一門兩邊都不會算)。"""
    from apps.sales.models import SalesOrderItem, SalesReturn

    lines = SalesOrderItem.objects.filter(
        tenant=tenant, so__is_void=False, telecom_plan__isnull=False, activation_date__isnull=True,
    ).exclude(so__in=SalesReturn.objects.filter(tenant=tenant, is_void=False).values("original_so"))
    if warehouse_id is not None:
        lines = lines.filter(so__warehouse_id=warehouse_id)
    count = lines.count()
    return f"未填上線日 {count} 門" if count else ""

MONEY = (
    Col("net_sales", "淨銷售額"),
    Col("staff_gross_profit", "業務員毛利"),
    Col("net_staff_commission", "門號佣金"),
    Col("staff_total", "毛利加佣金"),
    Col("gross_profit", "實際毛利", managers=True),
    Col("net_company_commission", "公司佣金", managers=True),
)

REPORTS = {r.key: r for r in [
    Report("staff", "業績彙總", abilities.REPORT_STAFF, {"sales_person": "業務員"},
           (Col("sales_orders", "銷貨單數"), *MONEY), sort="-staff_total"),
    Report("products", "商品排行", abilities.REPORT_PRODUCTS,
           {"product": "商品", "category": "品類", "brand": "品牌"},
           (Col("net_qty", "淨銷量"), Col("net_sales", "淨銷售額"),
            Col("staff_gross_profit", "業務員毛利"), Col("gross_profit", "實際毛利", managers=True)),
           sort="-net_qty", keep=200),
    Report("daily", "每日彙總", abilities.REPORT_DAILY, {"date": "日期"},
           (Col("sales_orders", "銷貨單數"), *MONEY), grain="day", max_days=366),
    # 取舊歐睿 SA040 毛利彙總表「照客戶 / 照會員」(owner 2026-10-12):誰買得最多。欄位跟商品排行同一套
    # **只有管理員看得到**(owner 同一天:「客戶排行不用給店員看」)
    Report("customers", "來源排行", MANAGERS_ONLY, {"customer": "來源", "member": "會員"},
           (Col("sales_orders", "銷貨單數"), Col("net_sales", "淨銷售額"),
            Col("staff_gross_profit", "業務員毛利"), Col("gross_profit", "實際毛利", managers=True)),
           sort="-net_sales", keep=200),
    # 取舊歐睿 SIM031 開通數量統計(owner 2026-10-12):各家電信、各種方案開了幾門、誰開最多。
    # 逐筆的是佣金明細(sales/commission_views.py);這一張的開通數 = 那一頁的銷貨列數 − 銷退列數,佣金合計一樣
    # 欄(動手前紅隊):新辦 / 續約 / 攜碼各幾門(一列就看得到「哪家電信、哪一種」)、退掉的另外一欄
    # (成交與退掉分開,淨開通是負的時候看得出為什麼);新辦 + 續約 + 攜碼 − 退掉 = 淨開通
    Report("activations", "開通統計", abilities.REPORT_ACTIVATIONS,
           {"carrier": "電信", "plan": "方案", "sales_person": "業務", "warehouse": "門市"},
           (*(Col(f"activations_{code}", label) for code, label in PLAN_KINDS),
            Col("return_activations", "退掉"), Col("net_activations", "淨開通"),
            Col("net_staff_commission", "業務員佣金"), Col("net_company_commission", "公司佣金", managers=True)),
           sort="-net_activations", note="佣金已扣銷退",        # 新辦 / 續約 / 攜碼三欄是成交的數,沒有扣
           # owner 2026-10-12:要能照上線日看(電信商照上線日算佣金與達標)。欄的意思一樣,只是歸到上線的那一天;
           # 退掉的仍然扣在退的那一天(動手前紅隊第 1 條),而且只扣有上線日的那幾門
           date_label="開單日",
           dates=(Basis("start", "上線日",
                        (*(Col(f"started_{code}", label) for code, label in PLAN_KINDS),
                         Col("return_started", "退掉"), Col("started_net", "淨開通"),
                         Col("started_net_staff_commission", "業務員佣金"),
                         Col("started_net_company_commission", "公司佣金", managers=True)),
                        sort="-started_net", note="佣金已扣銷退", pending=_lines_without_start),)),
]}

DEFAULT_DATE = "doc"


def _basis(report: Report, date: str) -> Basis:
    """這次期間看哪一種日期。沒有別種看法的報表不收這個參數(送了別的值就是打錯)。"""
    default = Basis(DEFAULT_DATE, report.date_label, report.cols, report.sort, report.note)
    if date in ("", DEFAULT_DATE):
        return default
    for basis in report.dates:
        if basis.key == date:
            return basis
    raise engine.QueryError("這張報表不能照這個日期看")


def check(report: Report, user) -> None:
    """這個人能不能看這張(不能就丟 403)。只給管理員的看角色,其餘看員工帳號頁的那一個勾。"""
    if report.ability == MANAGERS_ONLY:
        if not is_tenant_admin(user):
            raise PermissionDenied(f"「{report.title}」只有管理員可以看")
        return
    abilities.require(user, report.ability)


def _nothing(values) -> bool:
    return all(v is None or Decimal(str(v)) == 0 for v in values.values())


def run(report: Report, tenant, user, *, start, end, by="", warehouse=None, only_warehouse=None,
        everything=False, date=""):
    """warehouse = 畫面選的門市(沒選 = 全公司);only_warehouse = 鎖在門市的帳號那一家(引擎強制)。
    date = 期間看哪一種日期(空的 = 預設;只有 `Report.dates` 有列的報表可以改)。

    everything = 匯出用:不照這張報表「畫面最多列幾列」(商品排行 200)截,給引擎算得出來的全部
    (引擎自己的上限 `engine.MAX_ROWS` 還是在;超過那個才算 truncated)。合計本來就是全部的。
    """
    role = getattr(getattr(user, "profile", None), "role", None)
    dimension = by or next(iter(report.by))
    if dimension not in report.by:
        raise engine.QueryError("這張報表不能這樣分")
    basis = _basis(report, date)
    cols = [c for c in basis.cols if not c.managers or role in MANAGERS]
    spec = {
        "measures": [c.key for c in cols],
        "dimensions": [dimension],
        "period": {"from": start, "to": end, "grain": report.grain},
        "sort": basis.sort,
        "limit": engine.MAX_ROWS,
    }
    if warehouse is not None:
        spec["filters"] = {"warehouse": [warehouse]}
    q = engine.parse(spec, user)
    if report.max_days and (q.end - q.start).days >= report.max_days:
        raise engine.QueryError(f"「{report.title}」一次最多看一年")
    result = engine.run(tenant, spec, user, only_warehouse=only_warehouse)
    rows = [r for r in result["rows"] if not _nothing(r["values"])]
    labels = {c.key: c.label for c in cols}
    return {
        "key": report.key,
        "title": report.title,
        "note": basis.note,
        # 期間可以看哪幾種日期(只有一種的報表是空的,畫面不出下拉)、這一次看的是哪一種
        "dates": [{"key": b.key, "label": b.label}
                  for b in ((Basis(DEFAULT_DATE, report.date_label, ()), *report.dates) if report.dates else ())],
        "date": basis.key,
        # 還沒有這個日期、所以哪一段期間都沒算到的(一句話;沒有就是空的)。鎖門市的帳號只算自己那一家
        "pending": basis.pending(tenant, only_warehouse if only_warehouse is not None else warehouse)
        if basis.pending else "",
        "by": [{"key": k, "label": v} for k, v in report.by.items()],
        "columns": {
            "dimensions": [{"key": dimension, "label": report.by[dimension]}],
            "measures": [{**m, "label": labels[m["key"]]} for m in result["columns"]["measures"]],
        },
        "rows": rows if everything else rows[: report.keep],
        "row_count": len(rows),
        "truncated": result["truncated"] or (not everything and len(rows) > report.keep),
        "totals": result["totals"],
        "applied": result["applied"],
    }
