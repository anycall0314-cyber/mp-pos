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

# 「最近熱銷」窗口(天數)
_HOT_SELLING_DAYS = 30


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

    依 lifecycle_status + ProductRelation(主機-配件)推論觸發原因:
    - active + qty=0:已斷貨,critical
    - active + qty<safety 無關聯主機:低於安全庫存,warning
    - active + qty<safety 關聯主機是 active 且最近熱銷:主機熱銷帶動,warning
    - active + qty<safety 關聯主機是 replacing/discontinued/clearance:主機已換代,info
    - replacing + qty<safety:換代審查,info
    - clearance + qty>0:出清提醒,info
    """
    tenant = request.tenant
    profile = getattr(request.user, "profile", None)

    # 鎖倉帳號自動限定自己門市(跟 home-summary 同邏輯)
    wid = None
    if profile and profile.is_warehouse_locked and profile.default_warehouse_id:
        wid = profile.default_warehouse_id
    else:
        q_wh = request.query_params.get("warehouse")
        if q_wh and q_wh.isdigit():
            wid = int(q_wh)

    serial_sq, balance_sq = _build_stock_annotation(tenant, wid)

    # 1. active / replacing 商品的庫存查詢
    base_qs = (
        Product.objects.for_tenant(tenant)
        .filter(is_active=True, is_virtual=False)
        .select_related("category")
        .prefetch_related("host_relations__host_product")
    )
    base_qs = _annotate_stock(base_qs, serial_sq, balance_sq)

    # 撈所有可能進警示的:active+低於safety / replacing+低於safety / clearance+在庫
    alert_qs = base_qs.filter(
        Q(
            lifecycle_status__in=[
                Product.LifecycleStatus.ACTIVE,
                Product.LifecycleStatus.REPLACING,
            ],
            safety_stock__gt=0,
            stock__lt=F("safety_stock"),
        )
        | Q(
            lifecycle_status=Product.LifecycleStatus.CLEARANCE,
            stock__gt=0,
        )
    ).order_by("stock", "name")

    products = list(alert_qs[:200])

    # 找出所有 host product 並判斷是否最近熱銷
    host_ids = set()
    for p in products:
        for r in p.host_relations.all():
            host_ids.add(r.host_product_id)
    hot_host_ids: set[int] = set()
    if host_ids:
        since = timezone.now().date() - timedelta(days=_HOT_SELLING_DAYS)
        sold_ids = (
            SalesOrderItem.objects.for_tenant(tenant)
            .filter(
                product_id__in=host_ids,
                so__doc_date__gte=since,
                so__is_void=False,
            )
            .values_list("product_id", flat=True)
            .distinct()
        )
        hot_host_ids = set(sold_ids)

    rows = []
    for p in products:
        hosts = [r.host_product for r in p.host_relations.all()]
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
                "safety_stock": p.safety_stock,
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

    # 依 severity 排:critical → warning → info,同級內依 stock 升冪
    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    rows.sort(key=lambda r: (sev_rank.get(r["severity"], 9), r["current_qty"]))

    counts = {
        "critical": sum(1 for r in rows if r["severity"] == "critical"),
        "warning": sum(1 for r in rows if r["severity"] == "warning"),
        "info": sum(1 for r in rows if r["severity"] == "info"),
        "total": len(rows),
    }

    return Response({"counts": counts, "rows": rows})
