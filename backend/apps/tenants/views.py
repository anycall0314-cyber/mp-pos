from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
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


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def tenant_settings(request):
    """GET 回租戶層級設定;PATCH 更新(限 tenant_admin / platform_admin)。"""
    tenant = request.tenant
    if request.method == "GET":
        return Response(
            {
                "id": tenant.id,
                "name": tenant.name,
                "code": tenant.code,
                "repair_warranty_days": tenant.repair_warranty_days,
            }
        )
    profile = getattr(request.user, "profile", None)
    role = profile.role if profile else None
    if role not in ("platform_admin", "tenant_admin"):
        return Response({"detail": "權限不足"}, status=status.HTTP_403_FORBIDDEN)
    days = request.data.get("repair_warranty_days")
    if days is not None:
        try:
            days = int(days)
        except (ValueError, TypeError):
            return Response(
                {"detail": "保固天數需為整數"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if days < 1 or days > 3650:
            return Response(
                {"detail": "保固天數需在 1 ~ 3650 之間"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        tenant.repair_warranty_days = days
        tenant.save(update_fields=["repair_warranty_days"])
    return Response(
        {
            "id": tenant.id,
            "repair_warranty_days": tenant.repair_warranty_days,
        }
    )
