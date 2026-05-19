from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.sales.models import SalesOrder, SalesOrderItemSerial

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
