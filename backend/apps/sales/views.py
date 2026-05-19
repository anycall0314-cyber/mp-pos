from django.db import transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import SalesOrder
from .serializers import SalesOrderSerializer
from .services import SalesOrderError, commit_sales_order, void_sales_order


class SalesOrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """銷貨單:儲存即生效;不開放 update / delete,要取消請用 void action。"""

    serializer_class = SalesOrderSerializer
    search_fields = [
        "no",
        "customer__code",
        "customer__name",
        "customer__phone",
        "invoice_no",
        "note",
    ]
    ordering_fields = ["doc_date", "no", "created_at", "total"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "warehouse": ["exact"],
        "customer": ["exact"],
        "sales_type": ["exact"],
        "tax_method": ["exact"],
        "is_void": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return (
            SalesOrder.objects.for_tenant(self.request.tenant)
            .select_related("customer", "warehouse")
            .prefetch_related(
                "items__product",
                "items__sim_card",
                "items__serials__serial",
                "payments",
            )
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
                commit_sales_order(serializer.instance)
            except SalesOrderError as exc:
                raise serializers.ValidationError({"detail": str(exc)})

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        so = self.get_object()
        try:
            void_sales_order(so)
        except SalesOrderError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        so = self.get_queryset().get(pk=so.pk)
        return Response(self.get_serializer(so).data)
