import math
from datetime import timedelta

from django.db.models import (
    Count,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from apps.catalog.models import Product, ProductRelation
from apps.sales.models import SalesOrder, SalesOrderItem, SalesOrderItemSerial

from .models import ProductSerial, StockBalance, StockMovement, Warehouse
from .serializers import (
    ProductSerialSerializer,
    StockBalanceSerializer,
    StockMovementSerializer,
    WarehouseSerializer,
)


class WarehouseViewSet(viewsets.ModelViewSet):
    serializer_class = WarehouseSerializer
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "created_at"]
    ordering = ["code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return Warehouse.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ProductSerialViewSet(viewsets.ReadOnlyModelViewSet):
    """序號目前只開讀取;新增由進貨過帳產生,狀態改由維護介面（之後做）。"""

    serializer_class = ProductSerialSerializer
    search_fields = ["serial_no", "product__sku", "product__name"]
    ordering_fields = ["created_at", "serial_no", "received_at"]
    ordering = ["-id"]
    filterset_fields = ["status", "warehouse", "product"]

    def get_queryset(self):
        return (
            ProductSerial.objects.for_tenant(self.request.tenant)
            .select_related(
                "product",
                "warehouse",
                "acquired_from_member",
                "acquired_via_sales_order",
            )
        )

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        """序號完整履歷:收購來源 + 異動軌跡 + 銷售紀錄(含作廢)。"""
        serial = self.get_object()

        # 收購來源:廠商進貨單 or 個人收購銷貨單
        acquisition = None
        if serial.acquired_via_sales_order_id:
            so = serial.acquired_via_sales_order
            acquisition = {
                "kind": "trade_in",
                "kind_label": "個人收購",
                "sales_order_id": so.id,
                "sales_order_no": so.no,
                "doc_date": so.doc_date,
                "member_id": (
                    serial.acquired_from_member_id
                    if serial.acquired_from_member_id
                    else None
                ),
                "member_phone": (
                    serial.acquired_from_member.phone
                    if serial.acquired_from_member_id
                    else ""
                ),
                "member_name": (
                    serial.acquired_from_member.name
                    if serial.acquired_from_member_id
                    else ""
                ),
                "amount": str(serial.purchase_unit_cost),
            }
        elif serial.purchase_order_item_id:
            poi = serial.purchase_order_item
            po = poi.po
            acquisition = {
                "kind": "purchase",
                "kind_label": "廠商進貨",
                "purchase_order_id": po.id,
                "purchase_order_no": po.no,
                "doc_date": po.doc_date,
                "supplier_id": po.supplier_id,
                "supplier_name": po.supplier.name if po.supplier_id else "",
                "amount": str(serial.purchase_unit_cost),
            }

        # 異動軌跡
        movements = list(
            StockMovement.objects.for_tenant(serial.tenant)
            .filter(serial=serial)
            .select_related("from_warehouse", "to_warehouse")
            .order_by("created_at", "id")
        )
        movement_data = [
            {
                "id": m.id,
                "movement_type": m.movement_type,
                "type_label": m.get_movement_type_display(),
                "from_warehouse_code": (
                    m.from_warehouse.code if m.from_warehouse_id else ""
                ),
                "to_warehouse_code": (
                    m.to_warehouse.code if m.to_warehouse_id else ""
                ),
                "ref_doc_type": m.ref_doc_type,
                "ref_doc_id": m.ref_doc_id,
                "note": m.note,
                "created_at": m.created_at,
            }
            for m in movements
        ]

        # 所有銷售紀錄(含作廢的)
        sales_events = list(
            SalesOrderItemSerial.objects.for_tenant(serial.tenant)
            .filter(serial=serial)
            .select_related(
                "item__so", "item__so__customer", "item__product"
            )
            .order_by("item__so__doc_date", "id")
        )
        sales_data = [
            {
                "id": s.id,
                "sales_order_id": s.item.so.id,
                "sales_order_no": s.item.so.no,
                "doc_date": s.item.so.doc_date,
                "is_void": s.item.so.is_void,
                "customer_phone": (
                    s.item.so.customer.phone if s.item.so.customer_id else ""
                ),
                "customer_name": (
                    s.item.so.customer.name if s.item.so.customer_id else ""
                ),
                "unit_price": str(s.item.unit_price),
                "amount": str(s.item.amount),
            }
            for s in sales_events
        ]

        return Response(
            {
                "serial": ProductSerialSerializer(serial).data,
                "acquisition": acquisition,
                "movements": movement_data,
                "sales": sales_data,
            }
        )


class StockBalanceViewSet(viewsets.ReadOnlyModelViewSet):
    """配件庫存餘額;按 product / warehouse 篩選。

    給庫存查詢「配件按倉分佈」、調撥單選來源倉、銷貨檢查庫存等場景。
    """

    serializer_class = StockBalanceSerializer
    ordering_fields = ["product__sku", "warehouse__code", "qty"]
    ordering = ["product__sku", "warehouse__code"]
    filterset_fields = ["product", "warehouse"]

    def get_queryset(self):
        return (
            StockBalance.objects.for_tenant(self.request.tenant)
            .filter(qty__gt=0)
            .select_related("product", "warehouse")
        )


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    """庫存異動軌跡:唯讀,由各業務動作自動寫入。"""

    serializer_class = StockMovementSerializer
    search_fields = ["serial__serial_no", "ref_doc_type"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
    filterset_fields = ["movement_type", "from_warehouse", "to_warehouse", "serial"]

    def get_queryset(self):
        return (
            StockMovement.objects.for_tenant(self.request.tenant)
            .select_related("serial")
        )


# ─────────────────────────────────────────────────────────
# 庫存警示 API:依 lifecycle_status + 商品關聯 推論觸發原因
# 嚴重度 severity:critical > warning > info
#   critical: active 已斷貨(qty=0)
#   warning : active 低庫存 + 主機正在熱銷帶動
#   warning : active 低庫存(無關聯主機 / 主機也低庫存)
#   info    : active 低庫存但對應主機已換代 / replacing 商品低庫存(審查) /
#             clearance 還有庫存(出清提醒)
# ─────────────────────────────────────────────────────────

# 「最近熱銷」/ 日均銷量窗口(天數)
_SALES_WINDOW_DAYS = 30
# 清倉壓力警示門檻:預估清倉天數超過此值 → 建議降價
_CLEARANCE_PRESSURE_DAYS = 60


def _daily_avg_sales(tenant, product_ids):
    """回傳 dict {product_id: 過去 N 天日均銷量(float)}。
    用於:
    - 機型專屬配件的動態 safety stock(看主機 product_ids 的日均)
    - 清倉壓力預估天數(看該配件本身 product_ids 的日均)
    """
    if not product_ids:
        return {}
    since = timezone.now().date() - timedelta(days=_SALES_WINDOW_DAYS)
    rows = (
        SalesOrderItem.objects.for_tenant(tenant)
        .filter(
            product_id__in=product_ids,
            so__doc_date__gte=since,
            so__is_void=False,
        )
        .values("product_id")
        .annotate(total=Sum("qty"))
    )
    return {
        r["product_id"]: float(r["total"] or 0) / _SALES_WINDOW_DAYS
        for r in rows
    }


def _compute_safety(product, hosts, host_daily_avg_map):
    """回傳 (effective_safety:int, source:str, formula:str|None)。

    機型專屬配件 + 有關聯主機 → 動態:
        Σ(每主機日均) × attach_rate × replenish_days,任一主機 replacing 折半
    其他 → 用靜態 safety_stock
    """
    if (
        product.accessory_type == Product.AccessoryType.PHONE_SPECIFIC
        and hosts
    ):
        sum_daily = sum(host_daily_avg_map.get(h.id, 0.0) for h in hosts)
        attach = float(product.attach_rate or 0)
        days = int(product.replenish_days or 0)
        base = sum_daily * attach * days
        host_replacing = any(
            h.lifecycle_status == Product.LifecycleStatus.REPLACING for h in hosts
        )
        if host_replacing:
            base *= 0.5
        eff = int(math.ceil(base))
        formula = (
            f"主機日均 {sum_daily:.1f} × 購買率 {attach:.0%}"
            f" × 補貨 {days} 天"
        )
        if host_replacing:
            formula += " × 0.5(主機即將換代,自動折半)"
        formula += f" = {eff} 件"
        return eff, "dynamic", formula
    return int(product.safety_stock or 0), "static", None


def _build_stock_annotation(tenant, warehouse_id=None):
    """回傳:(serial_count_sq, balance_sq) 兩個用 OuterRef 的 Subquery。
    與 catalog/views.py 同模式,確保庫存統計不被 search 的 JOIN 干擾。
    """
    serial_filter = Q(
        product=OuterRef("pk"),
        status=ProductSerial.Status.IN_STOCK,
    )
    balance_filter = Q(product=OuterRef("pk"), tenant=tenant)
    if warehouse_id is not None:
        serial_filter &= Q(warehouse_id=warehouse_id)
        balance_filter &= Q(warehouse_id=warehouse_id)
    serial_sq = (
        ProductSerial.objects.filter(serial_filter)
        .order_by()
        .values("product")
        .annotate(c=Count("*"))
        .values("c")[:1]
    )
    balance_sq = (
        StockBalance.objects.filter(balance_filter)
        .order_by()
        .values("product")
        .annotate(t=Sum("qty"))
        .values("t")[:1]
    )
    return serial_sq, balance_sq


def _annotate_stock(qs, serial_sq, balance_sq):
    return qs.annotate(
        _sc=Coalesce(Subquery(serial_sq, output_field=IntegerField()), Value(0)),
        _bc=Coalesce(Subquery(balance_sq, output_field=IntegerField()), Value(0)),
        stock=F("_sc") + F("_bc"),
    )


@api_view(["GET"])
def inventory_alerts(request):
    """庫存警示 API,回傳當前所有需要關注的商品。

    觸發條件:
    - active/replacing 商品 + qty < effective_safety(可動態 / 靜態)
    - clearance 商品 + qty > 0

    effective_safety 計算:
    - 機型專屬配件 + 有關聯主機 → 動態公式
      (Σ主機日均 × 配件購買率 × 補貨天數;任一主機 replacing 折半)
    - 其他 → 靜態 safety_stock 欄位

    推論 reason:
    - out_of_stock / low_stock / host_hot_selling / host_replaced /
      replacing_review / clearance_remain
    """
    tenant = request.tenant
    profile = getattr(request.user, "profile", None)

    wid = None
    if profile and profile.is_warehouse_locked and profile.default_warehouse_id:
        wid = profile.default_warehouse_id
    else:
        q_wh = request.query_params.get("warehouse")
        if q_wh and q_wh.isdigit():
            wid = int(q_wh)

    serial_sq, balance_sq = _build_stock_annotation(tenant, wid)

    # 1. 撈所有可能進警示的候選商品(active/replacing/clearance)
    # 動態 safety 無法在 SQL 內過濾,先全撈再 Python 過濾
    base_qs = (
        Product.objects.for_tenant(tenant)
        .filter(
            is_active=True,
            is_virtual=False,
            lifecycle_status__in=[
                Product.LifecycleStatus.ACTIVE,
                Product.LifecycleStatus.REPLACING,
                Product.LifecycleStatus.CLEARANCE,
            ],
        )
        .select_related("category")
        .prefetch_related("host_relations__host_product")
    )
    base_qs = _annotate_stock(base_qs, serial_sq, balance_sq)
    candidates = list(base_qs)

    # 2. 算所有主機的日均銷量(動態 safety 用)
    host_ids = set()
    for p in candidates:
        for r in p.host_relations.all():
            host_ids.add(r.host_product_id)
    host_daily_avg = _daily_avg_sales(tenant, host_ids)

    # 「最近熱銷」= 該主機 active 且過去 N 天有銷貨(daily_avg > 0)
    hot_host_ids = {pid for pid, avg in host_daily_avg.items() if avg > 0}

    rows = []
    for p in candidates:
        hosts = [r.host_product for r in p.host_relations.all()]
        effective_safety, safety_source, safety_formula = _compute_safety(
            p, hosts, host_daily_avg
        )

        # 過濾:不符合警示條件的跳過
        is_clearance = p.lifecycle_status == Product.LifecycleStatus.CLEARANCE
        if is_clearance:
            if p.stock <= 0:
                continue
        else:
            if effective_safety <= 0:
                continue  # 沒設 safety / 動態算出 0 → 不追蹤
            if p.stock >= effective_safety:
                continue  # 庫存充足,不警示

        host_replaced = any(
            h.lifecycle_status
            in (
                Product.LifecycleStatus.REPLACING,
                Product.LifecycleStatus.DISCONTINUED,
                Product.LifecycleStatus.CLEARANCE,
            )
            for h in hosts
        )
        host_hot = any(
            h.id in hot_host_ids
            and h.lifecycle_status == Product.LifecycleStatus.ACTIVE
            for h in hosts
        )

        # 推論 reason + severity
        if p.lifecycle_status == Product.LifecycleStatus.CLEARANCE:
            reason_code = "clearance_remain"
            reason_label = f"清倉中還剩 {p.stock} 件,加速出清"
            severity = "info"
        elif p.lifecycle_status == Product.LifecycleStatus.REPLACING:
            reason_code = "replacing_review"
            reason_label = "商品即將換代,審查補貨需求"
            severity = "info"
        elif p.stock == 0:
            reason_code = "out_of_stock"
            reason_label = "已斷貨,優先補貨"
            severity = "critical"
        elif host_replaced and not host_hot:
            reason_code = "host_replaced"
            reason_label = "主機已換代,審查是否續備"
            severity = "info"
        elif host_hot:
            reason_code = "host_hot_selling"
            reason_label = "主機熱銷帶動,建議備貨"
            severity = "warning"
        else:
            reason_code = "low_stock"
            reason_label = "低於安全庫存,建議補貨"
            severity = "warning"

        rows.append(
            {
                "id": p.id,
                "name": p.name,
                "sku": p.sku,
                "category_name": p.category.name if p.category else "",
                "current_qty": int(p.stock),
                "safety_stock": effective_safety,
                "safety_source": safety_source,
                "safety_formula": safety_formula,
                "accessory_type": p.accessory_type,
                "lifecycle_status": p.lifecycle_status,
                "lifecycle_status_label": p.get_lifecycle_status_display(),
                "severity": severity,
                "reason_code": reason_code,
                "reason_label": reason_label,
                "related_hosts": [
                    {
                        "id": h.id,
                        "name": h.name,
                        "lifecycle_status": h.lifecycle_status,
                    }
                    for h in hosts
                ],
            }
        )

    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    rows.sort(key=lambda r: (sev_rank.get(r["severity"], 9), r["current_qty"]))

    counts = {
        "critical": sum(1 for r in rows if r["severity"] == "critical"),
        "warning": sum(1 for r in rows if r["severity"] == "warning"),
        "info": sum(1 for r in rows if r["severity"] == "info"),
        "total": len(rows),
    }
    return Response({"counts": counts, "rows": rows})


@api_view(["GET"])
def clearance_pressure(request):
    """清倉壓力追蹤 API。

    對象:
    - lifecycle_status == clearance 的商品
    - 機型專屬配件 且 所有關聯主機都是 discontinued/clearance(主機已退役)

    每筆計算:
    - 該商品本身過去 30 天日均銷量
    - 預估清倉天數 = current_qty / 日均
    - 超過 60 天 → 標記「建議降價」

    日均 = 0 時用 999 表示「無銷售紀錄」(極端高壓力)。
    """
    tenant = request.tenant
    profile = getattr(request.user, "profile", None)

    wid = None
    if profile and profile.is_warehouse_locked and profile.default_warehouse_id:
        wid = profile.default_warehouse_id
    else:
        q_wh = request.query_params.get("warehouse")
        if q_wh and q_wh.isdigit():
            wid = int(q_wh)

    serial_sq, balance_sq = _build_stock_annotation(tenant, wid)

    base_qs = (
        Product.objects.for_tenant(tenant)
        .filter(is_active=True, is_virtual=False)
        .select_related("category")
        .prefetch_related("host_relations__host_product")
    )
    base_qs = _annotate_stock(base_qs, serial_sq, balance_sq)
    candidates = list(base_qs.filter(stock__gt=0))

    # 過濾出「正在出清」的:清倉狀態 OR 機型專屬+主機全退役
    pressure_products = []
    for p in candidates:
        if p.lifecycle_status == Product.LifecycleStatus.CLEARANCE:
            pressure_products.append((p, "self_clearance"))
            continue
        if p.accessory_type == Product.AccessoryType.PHONE_SPECIFIC:
            hosts = list(r.host_product for r in p.host_relations.all())
            if hosts and all(
                h.lifecycle_status
                in (
                    Product.LifecycleStatus.DISCONTINUED,
                    Product.LifecycleStatus.CLEARANCE,
                )
                for h in hosts
            ):
                pressure_products.append((p, "all_hosts_retired"))

    if not pressure_products:
        return Response({"counts": {"recommend_discount": 0, "total": 0}, "rows": []})

    daily_avg = _daily_avg_sales(
        tenant, [p.id for p, _ in pressure_products]
    )

    rows = []
    recommend_count = 0
    for p, source in pressure_products:
        avg = daily_avg.get(p.id, 0.0)
        if avg <= 0:
            est_days = 999  # 無銷售 → 視為極端壓力
            avg_label = "近 30 天無銷售"
        else:
            est_days = round(int(p.stock) / avg)
            avg_label = f"日均 {avg:.2f} 件"
        recommend = est_days > _CLEARANCE_PRESSURE_DAYS
        if recommend:
            recommend_count += 1
        hosts = list(r.host_product for r in p.host_relations.all())
        rows.append(
            {
                "id": p.id,
                "name": p.name,
                "sku": p.sku,
                "category_name": p.category.name if p.category else "",
                "current_qty": int(p.stock),
                "daily_avg": round(avg, 2),
                "daily_avg_label": avg_label,
                "estimated_days": min(est_days, 999),
                "recommend_discount": recommend,
                "source_label": (
                    "商品已標清倉"
                    if source == "self_clearance"
                    else "關聯主機全部停產 / 清倉"
                ),
                "lifecycle_status": p.lifecycle_status,
                "lifecycle_status_label": p.get_lifecycle_status_display(),
                "accessory_type": p.accessory_type,
                "related_hosts": [
                    {
                        "id": h.id,
                        "name": h.name,
                        "lifecycle_status": h.lifecycle_status,
                    }
                    for h in hosts
                ],
            }
        )

    # 預估天數越長 → 壓力越大,放最上面
    rows.sort(key=lambda r: -r["estimated_days"])

    return Response(
        {
            "counts": {
                "recommend_discount": recommend_count,
                "total": len(rows),
            },
            "threshold_days": _CLEARANCE_PRESSURE_DAYS,
            "rows": rows,
        }
    )
