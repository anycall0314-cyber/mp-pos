"""固定的報表(員工帳號權限第三批,owner 2026-10-10):業績彙總、商品排行、每日彙總。

內容由伺服器定,畫面只選日期與門市;數字全部走 `engine`(指標怎麼算只有 `catalog.py` 那一份),
這裡只決定「哪幾欄、照什麼分、欄名叫什麼」。

三張的數字都是**扣掉銷退之後**的(退的那一天扣回去),所以跟銷貨日報的合計對不起來是正常的 ——
銷貨日報不列銷退(動手前紅隊第 2 條)。「毛利加佣金」= 銷貨單清單上每張單的「業務員毛利」(那裡含門號佣金)加起來、
再扣掉銷退(紅隊第 1 條)。個人收購那種不算毛利的單不算在裡面;整列都是 0 的不列(紅隊第 3 條:
不然沒有業務員的收購單會變成一列「(未指定)」)。
"""
from dataclasses import dataclass
from decimal import Decimal

from apps.tenants import abilities

from . import engine
from .catalog import MANAGERS


@dataclass(frozen=True)
class Col:
    key: str                # catalog 裡的指標
    label: str              # 這張報表上的欄名
    managers: bool = False  # 只給管理員的欄(公司佣金本來就只有管理員拿得到;實際毛利跟銷貨單清單一樣只列給管理員)


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    ability: str
    by: dict                # 網址的 ?by= → 照哪個角度分(第一個是預設)
    cols: tuple
    sort: str = ""
    grain: str = "month"
    keep: int = engine.MAX_ROWS     # 最多列幾列
    max_days: int = 0               # 期間最長幾天(0 = 照引擎的上限)


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
]}


def _nothing(values) -> bool:
    return all(v is None or Decimal(str(v)) == 0 for v in values.values())


def run(report: Report, tenant, user, *, start, end, by="", warehouse=None, only_warehouse=None):
    """warehouse = 畫面選的門市(沒選 = 全公司);only_warehouse = 鎖在門市的帳號那一家(引擎強制)。"""
    role = getattr(getattr(user, "profile", None), "role", None)
    dimension = by or next(iter(report.by))
    if dimension not in report.by:
        raise engine.QueryError("這張報表不能這樣分")
    cols = [c for c in report.cols if not c.managers or role in MANAGERS]
    spec = {
        "measures": [c.key for c in cols],
        "dimensions": [dimension],
        "period": {"from": start, "to": end, "grain": report.grain},
        "sort": report.sort,
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
        "by": [{"key": k, "label": v} for k, v in report.by.items()],
        "columns": {
            "dimensions": [{"key": dimension, "label": report.by[dimension]}],
            "measures": [{**m, "label": labels[m["key"]]} for m in result["columns"]["measures"]],
        },
        "rows": rows[: report.keep],
        "row_count": len(rows),
        "truncated": result["truncated"] or len(rows) > report.keep,
        "totals": result["totals"],
        "applied": result["applied"],
    }
