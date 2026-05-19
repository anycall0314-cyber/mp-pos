from rest_framework import viewsets

from .models import ProductSerial, StockMovement, Warehouse
from .serializers import (
    ProductSerialSerializer,
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
