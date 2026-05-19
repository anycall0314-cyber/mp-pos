from django.db import transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import PurchaseOrder, PurchaseOrderCategory
from .serializers import (
    PurchaseOrderCategorySerializer,
    PurchaseOrderSerializer,
)
from .services import (
    PurchaseOrderError,
    commit_purchase_order,
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
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """進貨單:儲存即生效;不開放 update / delete,要取消請用 void action。"""

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
        with transaction.atomic():
            serializer.save(tenant=self.request.tenant, created_by=user)
            try:
                commit_purchase_order(serializer.instance)
            except PurchaseOrderError as exc:
                raise serializers.ValidationError({"detail": str(exc)})

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        po = self.get_object()
        try:
            void_purchase_order(po)
        except PurchaseOrderError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        po = self.get_queryset().get(pk=po.pk)
        return Response(self.get_serializer(po).data)
