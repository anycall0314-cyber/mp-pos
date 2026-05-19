from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import InvoiceTrack, InvoiceType, PaymentMethod
from .serializers import (
    InvoiceTrackSerializer,
    InvoiceTypeSerializer,
    PaymentMethodSerializer,
)
from .services import peek_next_invoice_no


class InvoiceTypeViewSet(viewsets.ModelViewSet):
    """發票類型主檔。

    code 不可改;只允許切換 is_active / is_default / 改名稱 / 排序。
    is_default 一次只有一個生效:存的時候若把某筆設為 default,自動清除其他的。
    """

    serializer_class = InvoiceTypeSerializer
    search_fields = ["code", "name"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active"]
    http_method_names = ["get", "patch", "put", "head", "options"]

    def get_queryset(self):
        return InvoiceType.objects.for_tenant(self.request.tenant)

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.is_default:
            InvoiceType.objects.for_tenant(instance.tenant).exclude(
                pk=instance.pk
            ).update(is_default=False)


class InvoiceTrackViewSet(viewsets.ModelViewSet):
    """發票字軌主檔。"""

    serializer_class = InvoiceTrackSerializer
    search_fields = ["prefix", "period_label", "note"]
    ordering = ["-id"]
    filterset_fields = ["invoice_type", "is_active"]

    def get_queryset(self):
        return InvoiceTrack.objects.for_tenant(self.request.tenant).select_related(
            "invoice_type"
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=["get"])
    def peek(self, request):
        """預覽下一張要開的發票號碼(不真正取號)。

        GET /api/v1/invoice-tracks/peek/?invoice_type_code=e_invoice
        """
        code = request.query_params.get("invoice_type_code", "")
        no = peek_next_invoice_no(request.tenant, code)
        if no is None:
            return Response(
                {"next_invoice_no": None, "detail": "無可用字軌"},
                status=status.HTTP_200_OK,
            )
        return Response({"next_invoice_no": no})


class PaymentMethodViewSet(viewsets.ModelViewSet):
    """付款方式主檔。

    code 不可改;is_default 一次只有一個生效。
    刪除允許(使用者自行新增的支付通路可移除)。
    """

    serializer_class = PaymentMethodSerializer
    search_fields = ["code", "name", "note"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active", "kind"]

    def get_queryset(self):
        return PaymentMethod.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.is_default:
            PaymentMethod.objects.for_tenant(instance.tenant).exclude(
                pk=instance.pk
            ).update(is_default=False)
