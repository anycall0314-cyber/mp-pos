from django.db import transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.idempotency import IdempotentCreateMixin
from apps.core.warehouse_scoping import WarehouseScopedMixin
from apps.tenants import abilities

from .models import PurchaseOrder, PurchaseOrderCategory
from .serializers import (
    PurchaseOrderCategorySerializer,
    PurchaseOrderSerializer,
)
from .services import (
    PurchaseOrderError,
    commit_purchase_order,
    transferable_from_purchase,
    void_purchase_order,
)


class PurchaseOrderCategoryViewSet(viewsets.ModelViewSet):
    serializer_class = PurchaseOrderCategorySerializer
    search_fields = ["code", "name"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return PurchaseOrderCategory.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class PurchaseOrderViewSet(
    IdempotentCreateMixin,
    WarehouseScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """進貨單:儲存即生效;不開放 update / delete,要取消請用 void action。"""

    idempotency_scope = "purchase-order"
    serializer_class = PurchaseOrderSerializer
    search_fields = ["no", "supplier__code", "supplier__name", "note", "invoice_no"]
    ordering_fields = ["doc_date", "no", "created_at"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "warehouse": ["exact"],
        "supplier": ["exact"],
        "is_void": ["exact"],
        "category": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return (
            PurchaseOrder.objects.for_tenant(self.request.tenant)
            .select_related("supplier", "warehouse", "category")
            .prefetch_related("items__product")
        )

    def perform_create(self, serializer):
        user = (
            self.request.user
            if getattr(self.request, "user", None) and self.request.user.is_authenticated
            else None
        )
        self.check_create_warehouse(serializer)
        with transaction.atomic():
            serializer.save(tenant=self.request.tenant, created_by=user)
            try:
                commit_purchase_order(serializer.instance)
            except PurchaseOrderError as exc:
                raise serializers.ValidationError({"detail": str(exc)})

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        abilities.require(request.user, abilities.VOID_PURCHASE)
        po = self.get_object()
        try:
            void_purchase_order(po)
        except PurchaseOrderError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        po = self.get_queryset().get(pk=po.pk)
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["get"])
    def transferable(self, request, pk=None):
        """整張調撥用:這張進貨單的東西現在還有哪些留在進貨門市(畫面拿去帶好一張調撥單)。只讀。

        鎖在自己門市的帳號只看得到自己門市的進貨單(跟進貨單清單同一套範圍)。
        """
        po = self.get_object()
        if po.is_void:
            return Response(
                {"detail": "這張進貨單已作廢,沒有東西可以調撥"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            "purchase_order": po.id,
            "no": po.no,
            "warehouse": po.warehouse_id,
            "warehouse_code": po.warehouse.code,
            "warehouse_name": po.warehouse.name,
            "lines": transferable_from_purchase(po),
        })
