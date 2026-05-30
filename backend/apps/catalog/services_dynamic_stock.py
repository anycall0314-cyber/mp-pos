"""動態安全庫存 / 趨勢分析 service。

由 `manage.py compute_dynamic_stock` 每晚排程跑一次。

設計理念:
- 主機(手機)的安全庫存完全跟著實際銷量走 → EWMA(指數加權移動平均)
- 配件(機型專屬)取兩個來源的較大者:
    1) 自己的 EWMA 銷量
    2) 綁定主機的 EWMA 銷量總和 × attach_rate
  任一邊熱起來都會把配件安全庫存推高。舊機甜蜜點賣得好,主機 EWMA 自然
  變大,配件 dynamic_safety_stock 跟著大,系統不需要知道「為什麼」。
- 雙窗趨勢:近 14 日均 / 過去 90 日均 = trend_ratio。
  > 1.2 視為回溫;< 0.5 視為退燒。給首頁推送用,跟 EWMA 互補。
- attach_rate 同樣自動算:過去 90 天「同單買主機 + 此配件」÷「買主機的訂單」。
"""
import math
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.sales.models import SalesOrder, SalesOrderItem

from .models import Product, ProductRelation

EWMA_ALPHA = 0.15
EWMA_WINDOW_DAYS = 60   # EWMA 取近 60 天計算
RECENT_DAYS = 14
BASELINE_DAYS = 90
ATTACH_WINDOW_DAYS = 90

TREND_FLOOR = Decimal("0.10")  # 趨勢比下限(避免極端值)
TREND_CEIL = Decimal("5.00")   # 趨勢比上限


def _daily_sales_map(product, window_days, today):
    """回傳 dict[date → qty],僅含有銷售的日子。"""
    start = today - timedelta(days=window_days - 1)
    rows = (
        SalesOrderItem.objects.filter(
            product=product,
            so__doc_date__gte=start,
            so__doc_date__lte=today,
            so__is_void=False,
        )
        .values("so__doc_date")
        .annotate(q=Sum("qty"))
    )
    return {r["so__doc_date"]: int(r["q"] or 0) for r in rows}


def _compute_ewma(daily_map, today):
    """從 60 天前迭代到今天,缺日視為 0(自然衰減)。"""
    v = 0.0
    start = today - timedelta(days=EWMA_WINDOW_DAYS - 1)
    cur = start
    one_day = timedelta(days=1)
    while cur <= today:
        q = daily_map.get(cur, 0)
        v = EWMA_ALPHA * q + (1 - EWMA_ALPHA) * v
        cur += one_day
    return Decimal(str(round(v, 3)))


def _compute_window_avg(daily_map, today, days):
    """單純窗口日均。"""
    start = today - timedelta(days=days - 1)
    total = sum(q for d, q in daily_map.items() if start <= d <= today)
    return Decimal(str(round(total / days, 3))) if days > 0 else Decimal("0")


def _compute_trend_ratio(recent, baseline):
    """recent / baseline,做 floor / ceil 防爆。基準 0 視為穩定(1)。"""
    if baseline <= 0:
        # 基準 0:若 recent > 0 算回溫(賦予 2.0),否則 1.0
        return Decimal("2.00") if recent > 0 else Decimal("1.00")
    ratio = Decimal(str(round(float(recent) / float(baseline), 2)))
    if ratio < TREND_FLOOR:
        return TREND_FLOOR
    if ratio > TREND_CEIL:
        return TREND_CEIL
    return ratio


def _resolve_host_product_ids(tenant, host_model_keys):
    """phone_model_key 是 computed property,只能用 Python 過濾。

    回傳 set[product_id] of active hosts matching any key in host_model_keys。
    """
    if not host_model_keys:
        return set()
    keys = set(host_model_keys)
    ids = set()
    qs = Product.objects.for_tenant(tenant).filter(
        accessory_type=Product.AccessoryType.NONE,
        is_active=True,
        is_virtual=False,
    )
    for p in qs.only("id", "name", "spec", "brand", "series",
                     "generation", "model_suffix"):
        if p.phone_model_key in keys:
            ids.add(p.id)
    return ids


def compute_attach_rate(product, today=None):
    """計算配件最近 90 天的 attach_rate。

    定義:過去 90 天「同單既有主機也有此配件」÷「過去 90 天有任一綁定主機的訂單」
    回傳 Decimal(0~1),四捨五入到小數第 2 位。
    """
    if today is None:
        today = timezone.localdate()
    if product.accessory_type != Product.AccessoryType.PHONE_SPECIFIC:
        return Decimal("0")
    host_keys = list(
        ProductRelation.objects.filter(
            tenant=product.tenant, accessory_product=product
        )
        .values_list("host_model_key", flat=True)
        .distinct()
    )
    host_ids = _resolve_host_product_ids(product.tenant, host_keys)
    if not host_ids:
        return Decimal("0")
    start = today - timedelta(days=ATTACH_WINDOW_DAYS - 1)
    base = SalesOrder.objects.filter(
        tenant=product.tenant,
        doc_date__gte=start,
        doc_date__lte=today,
        is_void=False,
    )
    # 有主機的訂單(distinct so_id)
    orders_with_host = set(
        SalesOrderItem.objects.filter(
            so__in=base, product_id__in=host_ids
        ).values_list("so_id", flat=True).distinct()
    )
    if not orders_with_host:
        return Decimal("0")
    orders_with_acc = set(
        SalesOrderItem.objects.filter(
            so_id__in=orders_with_host, product=product
        ).values_list("so_id", flat=True).distinct()
    )
    rate = len(orders_with_acc) / len(orders_with_host)
    return Decimal(str(round(rate, 2)))


def _compute_host_velocity_sum(tenant, host_keys):
    """主機 SKU 群的 velocity_ewma 總和(吃已算好的欄位,所以主機要先算過)。"""
    host_ids = _resolve_host_product_ids(tenant, host_keys)
    if not host_ids:
        return Decimal("0")
    agg = (
        Product.objects.filter(id__in=host_ids)
        .aggregate(s=Sum("velocity_ewma"))
    )
    return agg["s"] or Decimal("0")


def compute_dynamic_safety_stock(product):
    """依 lifecycle / accessory_type / velocity / host 帶動需求 算最終建議補貨點。"""
    if product.lifecycle_status in (
        Product.LifecycleStatus.DISCONTINUED,
        Product.LifecycleStatus.CLEARANCE,
    ):
        return 0
    replenish_days = product.replenish_days or 14
    own_demand = float(product.velocity_ewma) * replenish_days
    host_demand = 0.0
    if product.accessory_type == Product.AccessoryType.PHONE_SPECIFIC:
        host_keys = list(
            ProductRelation.objects.filter(
                tenant=product.tenant, accessory_product=product
            )
            .values_list("host_model_key", flat=True)
            .distinct()
        )
        host_velocity_sum = float(
            _compute_host_velocity_sum(product.tenant, host_keys)
        )
        attach = float(product.attach_rate or 0)
        host_demand = host_velocity_sum * attach * replenish_days
    return int(math.ceil(max(own_demand, host_demand)))


def compute_for_product(product, today=None, update_attach_rate=True):
    """單一商品的完整重算。回傳 dict 統計,順便寫回 model。"""
    if today is None:
        today = timezone.localdate()
    # 1) 銷售日 map(取兩窗較大者 = baseline 90 天)
    daily = _daily_sales_map(product, BASELINE_DAYS, today)
    ewma = _compute_ewma(daily, today)
    recent = _compute_window_avg(daily, today, RECENT_DAYS)
    baseline = _compute_window_avg(daily, today, BASELINE_DAYS)
    trend = _compute_trend_ratio(recent, baseline)

    # 2) 機型專屬配件:重算 attach_rate
    if update_attach_rate and product.accessory_type == Product.AccessoryType.PHONE_SPECIFIC:
        product.attach_rate = compute_attach_rate(product, today=today)

    # 3) 套用 velocity 結果(先存,因為 dynamic_safety_stock 算配件時要讀主機的)
    product.velocity_ewma = ewma
    product.velocity_recent_14d = recent
    product.velocity_baseline_90d = baseline
    product.trend_ratio = trend
    product.dynamic_stats_updated_at = timezone.now()

    # 4) 動態安全庫存
    product.dynamic_safety_stock = compute_dynamic_safety_stock(product)

    product.save(
        update_fields=[
            "velocity_ewma",
            "velocity_recent_14d",
            "velocity_baseline_90d",
            "trend_ratio",
            "attach_rate",
            "dynamic_safety_stock",
            "dynamic_stats_updated_at",
        ]
    )
    return {
        "ewma": ewma,
        "recent": recent,
        "baseline": baseline,
        "trend": trend,
        "dynamic_safety_stock": product.dynamic_safety_stock,
        "attach_rate": product.attach_rate,
    }


def recompute_for_tenant(tenant, today=None):
    """對整個 tenant 全部 active 商品重算。

    分兩階段:**先主機後配件**,因為配件需要讀主機已算好的 velocity_ewma。
    """
    if today is None:
        today = timezone.localdate()
    qs = Product.objects.for_tenant(tenant).filter(
        is_active=True,
        is_virtual=False,
    )
    # Phase 1: 主機(none / universal)
    hosts = qs.filter(
        accessory_type__in=[
            Product.AccessoryType.NONE,
            Product.AccessoryType.UNIVERSAL,
        ]
    )
    host_count = 0
    for p in hosts:
        compute_for_product(p, today=today, update_attach_rate=False)
        host_count += 1
    # Phase 2: 機型專屬配件
    accessories = qs.filter(accessory_type=Product.AccessoryType.PHONE_SPECIFIC)
    acc_count = 0
    for p in accessories:
        compute_for_product(p, today=today, update_attach_rate=True)
        acc_count += 1
    return {"hosts": host_count, "accessories": acc_count}


def insights_trending(tenant, limit=10):
    """首頁推送:回溫 / 退燒 / 需補貨 三類清單。

    給 GET /api/v1/insights/trending/ 用。
    """
    from django.db.models import F, IntegerField, OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce

    from apps.inventory.models import ProductSerial, StockBalance

    serial_sq = (
        ProductSerial.objects.filter(
            product=OuterRef("pk"),
            status=ProductSerial.Status.IN_STOCK,
        )
        .order_by()
        .values("product")
        .annotate(c=Count("*"))
        .values("c")[:1]
    )
    balance_sq = (
        StockBalance.objects.filter(product=OuterRef("pk"), tenant=tenant)
        .order_by()
        .values("product")
        .annotate(t=Sum("qty"))
        .values("t")[:1]
    )
    base = (
        Product.objects.for_tenant(tenant)
        .filter(is_active=True, is_virtual=False)
        .annotate(
            _sc=Coalesce(
                Subquery(serial_sq, output_field=IntegerField()), Value(0)
            ),
            _bc=Coalesce(
                Subquery(balance_sq, output_field=IntegerField()), Value(0)
            ),
            stock=F("_sc") + F("_bc"),
        )
    )
    trending_up = list(
        base.filter(
            trend_ratio__gte=Decimal("1.20"),
            velocity_recent_14d__gt=0,
        ).order_by("-trend_ratio", "-velocity_recent_14d")[:limit]
    )
    trending_down = list(
        base.filter(
            trend_ratio__lte=Decimal("0.50"),
            velocity_baseline_90d__gt=0,
            stock__gt=0,
        ).order_by("trend_ratio", "-stock")[:limit]
    )

    def _serialize(p, kind):
        return {
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "stock": int(p.stock),
            "velocity_ewma": str(p.velocity_ewma),
            "velocity_recent_14d": str(p.velocity_recent_14d),
            "velocity_baseline_90d": str(p.velocity_baseline_90d),
            "trend_ratio": str(p.trend_ratio),
            "dynamic_safety_stock": p.dynamic_safety_stock,
            "kind": kind,
        }

    return {
        "trending_up": [_serialize(p, "up") for p in trending_up],
        "trending_down": [_serialize(p, "down") for p in trending_down],
    }
