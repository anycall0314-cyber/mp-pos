from django.db import transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import TransferOrder
from .serializers import TransferOrderSerializer
from .services import (
    TransferOrderError,
    confirm_transfer_order,
    dispatch_transfer_order,
    void_transfer_order,
)


class TransferOrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """調撥單:儲存即生效;不開放 update / delete,要取消請用 void action。"""

    serializer_class = TransferOrderSerializer
    search_fields = [
        "no",
        "from_warehouse__code",
        "to_warehouse__code",
        "note",
    ]
    ordering_fields = ["doc_date", "no", "created_at"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "from_warehouse": ["exact"],
        "to_warehouse": ["exact"],
        "status": ["exact"],
        "is_void": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return (
            TransferOrder.objects.for_tenant(self.request.tenant)
            .select_related("from_warehouse", "to_warehouse")
            .prefetch_related("items__product", "items__serials__serial")
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
                dispatch_transfer_order(serializer.instance)
            except TransferOrderError as exc:
                raise serializers.ValidationError({"detail": str(exc)})

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        to = self.get_object()
        user = (
            request.user
            if getattr(request, "user", None) and request.user.is_authenticated
            else None
        )
        try:
            confirm_transfer_order(to, user=user)
        except TransferOrderError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        to = self.get_queryset().get(pk=to.pk)
        return Response(self.get_serializer(to).data)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        to = self.get_object()
        try:
            void_transfer_order(to)
        except TransferOrderError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        to = self.get_queryset().get(pk=to.pk)
        return Response(self.get_serializer(to).data)
