from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.warehouse_scoping import WarehouseScopedMixin

from .models import RepairItem, RepairOrder
from .serializers import RepairItemSerializer, RepairOrderSerializer
from .services import (
    complete_repair_order,
    compute_in_house_quote,
    compute_margin,
    parts_with_insufficient_stock,
)


class RepairItemViewSet(viewsets.ModelViewSet):
    """維修項目模板 CRUD。"""

    serializer_class = RepairItemSerializer
    search_fields = ["name"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return (
            RepairItem.objects.for_tenant(self.request.tenant)
            .prefetch_related("parts__part_product", "model_bindings")
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=["get"], url_path="by-model")
    def by_model(self, request):
        """依機型 key 列出可用維修項目(維修單建單頁用)。"""
        key = request.query_params.get("model_key", "").strip().lower()
        if not key:
            return Response([])
        qs = (
            RepairItem.objects.for_tenant(request.tenant)
            .filter(is_active=True, model_bindings__host_model_key=key)
            .prefetch_related("parts__part_product")
            .distinct()
        )
        return Response(RepairItemSerializer(qs, many=True).data)


class RepairOrderViewSet(WarehouseScopedMixin, viewsets.ModelViewSet):
    """維修單 CRUD + 狀態切換 action。"""

    serializer_class = RepairOrderSerializer
    search_fields = ["no", "customer__name", "customer__phone", "device_serial"]
    filterset_fields = {
        "mode": ["exact"],
        "status": ["exact"],
        "warehouse": ["exact"],
        "is_void": ["exact"],
        "received_date": ["exact", "gte", "lte"],
    }
    ordering_fields = ["received_date", "completed_at", "created_at"]
    ordering = ["-received_date", "-id"]

    def get_queryset(self):
        return (
            RepairOrder.objects.for_tenant(self.request.tenant)
            .select_related(
                "customer",
                "warehouse",
                "sales_person",
                "repair_item",
                "external_vendor",
            )
            .prefetch_related("parts__part_product")
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        """切換狀態(pending/quoting/in_repair/sent_external/ready_pickup)。
        狀態 completed 走 /complete/ action。"""
        order = self.get_object()
        new_status = request.data.get("status")
        valid = {s for s, _ in RepairOrder.Status.choices if s != "completed"}
        if new_status not in valid:
            return Response(
                {"detail": f"狀態 {new_status} 不在允許範圍"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = new_status
        order.save(update_fields=["status"])
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        """轉「完成」狀態:扣零件倉庫存 + 寫異動。"""
        order = self.get_object()
        complete_repair_order(order)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["get"], url_path="quote-preview")
    def quote_preview(self, request, pk=None):
        """自修建議報價預覽(零件成本 + 工資)+ 缺料檢查。"""
        order = self.get_object()
        suggested = compute_in_house_quote(order)
        shortages = parts_with_insufficient_stock(order)
        return Response(
            {
                "suggested_quote": str(suggested),
                "shortages": shortages,
                "margin": str(compute_margin(order)),
            }
        )

    @action(detail=True, methods=["post"], url_path="void")
    def void(self, request, pk=None):
        order = self.get_object()
        order.is_void = True
        order.save(update_fields=["is_void"])
        return Response(self.get_serializer(order).data)
