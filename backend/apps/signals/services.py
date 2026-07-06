"""需求感知服務:記錄訊號 + 算熱度成長 + 產需求警示。

核心紀律(對齊 docs/demand-signal-layer.md):
- 外部熱度只用來「示警」;要內部領先訊號(商品:trend_ratio;維修:工單)跟上才「授權」加量。
- 這一層**只產 DemandAlert,不動帳本、不叫貨**。真正下單交給指令助理 + 既有 service。
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from .models import DemandAlert, MarketSignal, SubjectAlias, SubjectKind

UP = Decimal("0.15")     # 預設上升門檻 +15%
DOWN = Decimal("-0.15")  # 預設下降門檻 -15%


def record_signal(tenant, source, subject_key, period_date, value, meta=None):
    """upsert 一筆訊號(同 tenant/source/subject_key/日期覆寫)。"""
    obj, _ = MarketSignal.objects.update_or_create(
        tenant=tenant, source=source, subject_key=subject_key, period_date=period_date,
        defaults={"value": Decimal(str(value)), "meta": meta or {}},
    )
    return obj


def heat_growth(tenant, subject_key, as_of=None, window=7):
    """外部熱度:近 window 天 vs 前 window 天的成長率。無前期資料回 None。"""
    as_of = as_of or date.today()
    recent_lo = as_of - timedelta(days=window - 1)
    prev_hi = recent_lo - timedelta(days=1)
    prev_lo = prev_hi - timedelta(days=window - 1)

    ext = list(MarketSignal.EXTERNAL_SOURCES)
    base = MarketSignal.objects.for_tenant(tenant).filter(
        subject_key=subject_key, source__in=ext
    )
    recent = base.filter(period_date__range=(recent_lo, as_of)).aggregate(s=Sum("value"))["s"] or Decimal("0")
    prev = base.filter(period_date__range=(prev_lo, prev_hi)).aggregate(s=Sum("value"))["s"] or Decimal("0")
    if prev <= 0:
        return None
    return ((recent - prev) / prev).quantize(Decimal("0.0001"))


def _internal_growth_for_product(product):
    """商品內部領先成長:用既有 compute_dynamic_stock 算好的 trend_ratio。
    trend_ratio 1.0 = 穩定;>1 回溫;<1 退燒。轉成成長率 = trend_ratio - 1。
    """
    tr = product.trend_ratio if product.trend_ratio is not None else Decimal("1")
    return (Decimal(tr) - Decimal("1")).quantize(Decimal("0.0001"))


def compute_product_demand_alerts(tenant, as_of=None, up=UP, down=DOWN):
    """對每個有別名對應的商品標的,算熱度 + 內部成長,產 DemandAlert。

    授權閘:
      熱度↑ 且 內部↑  → up,authorized=True(可建議加量)
      熱度↑ 但 內部平 → watch,authorized=False(只觀望)
      熱度↓ 或 內部↓  → down,authorized=True(退燒示警,收手是安全的)
    """
    as_of = as_of or date.today()
    # subject_key → product(取有連 product 的別名)
    mapping = {}
    for a in SubjectAlias.objects.for_tenant(tenant).filter(
        kind=SubjectKind.PRODUCT_SALES, product__isnull=False
    ).select_related("product"):
        mapping.setdefault(a.subject_key, a.product)

    alerts = []
    for subject_key, product in mapping.items():
        hg = heat_growth(tenant, subject_key, as_of=as_of)
        if hg is None:
            continue
        ig = _internal_growth_for_product(product)

        if hg >= up and ig >= up:
            direction, authorized = DemandAlert.Direction.UP, True
            note = "熱度與內部同步上升,可評估上修"
        elif hg >= up and ig < up:
            direction, authorized = DemandAlert.Direction.WATCH, False
            note = "熱度上升但自家銷售 / 詢問尚未跟上,先觀望不加量"
        elif hg <= down or ig <= down:
            direction, authorized = DemandAlert.Direction.DOWN, True
            note = "需求退燒,建議收手 / 控制庫存金額"
        else:
            continue  # 變化不顯著,不吵

        score = (hg + ig) / Decimal("2")
        alert = DemandAlert.objects.create(
            tenant=tenant,
            kind=SubjectKind.PRODUCT_SALES,
            subject_key=subject_key,
            product=product,
            direction=direction,
            heat_growth=hg,
            internal_growth=ig,
            authorized=authorized,
            score=score.quantize(Decimal("0.0001")),
            window_end=as_of,
            note=note,
        )
        alerts.append(alert)
    return alerts
