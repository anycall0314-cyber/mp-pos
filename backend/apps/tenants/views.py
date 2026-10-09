from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core import staff_cost

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
    profile = getattr(request.user, "profile", None)
    role = profile.role if profile else None
    is_manager = role in ("platform_admin", "tenant_admin")
    # 業務員成本全公司的那一條(績效的基準):只有管理員拿得到、改得動
    staff_rule = {
        "staff_cost_mode": tenant.staff_cost_mode,
        "staff_cost_value": str(tenant.staff_cost_value),
    }
    if request.method == "GET":
        return Response(
            {
                "id": tenant.id,
                "name": tenant.name,
                "code": tenant.code,
                "repair_warranty_days": tenant.repair_warranty_days,
                "contract_remind_months": tenant.contract_remind_months,
                **(staff_rule if is_manager else {}),
            }
        )
    if not is_manager:
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
    months = request.data.get("contract_remind_months")
    if months is not None:
        try:
            months = int(months)
        except (ValueError, TypeError):
            return Response(
                {"detail": "提醒的月數需為整數"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if months < 1 or months > 24:
            return Response(
                {"detail": "提醒的月數需在 1 ~ 24 之間"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    mode = request.data.get("staff_cost_mode")
    value = request.data.get("staff_cost_value")
    if mode is not None or value is not None:
        changing_mode = mode is not None
        mode = tenant.staff_cost_mode if mode is None else mode
        try:
            if value is not None:
                value = Decimal(str(value))
                if not value.is_finite():
                    raise InvalidOperation
                value = staff_cost.cents(value)          # 先收到分(四捨五入),再看放不放得下
            elif not changing_mode:
                value = tenant.staff_cost_value
            # 換算法而沒有送數字:value 留著 None,下面會講「請填數字」(不沿用原本的)
        except (InvalidOperation, ValueError, TypeError):
            return Response({"detail": "業務員成本的數字不對"}, status=status.HTTP_400_BAD_REQUEST)
        problem = staff_cost.check(mode, value, staff_cost.COMPANY_MODES)
        if problem is None and value is not None and value >= Decimal("1000000000000"):
            problem = "數字太大"
        if problem:
            return Response({"detail": f"業務員成本{problem}"}, status=status.HTTP_400_BAD_REQUEST)
        value = Decimal("0") if not mode else value            # 尚未設定:數值不留
    # 全部檢查過才存:其中一個不對就整筆不動(不會回了錯誤、另一個欄位卻已經改掉)
    changed = []
    if days is not None:
        tenant.repair_warranty_days = days
        changed.append("repair_warranty_days")
    if months is not None:
        tenant.contract_remind_months = months
        changed.append("contract_remind_months")
    if mode is not None:
        tenant.staff_cost_mode, tenant.staff_cost_value = mode, value
        changed += ["staff_cost_mode", "staff_cost_value"]
    if changed:
        tenant.save(update_fields=changed)
    return Response(
        {
            "id": tenant.id,
            "repair_warranty_days": tenant.repair_warranty_days,
            "contract_remind_months": tenant.contract_remind_months,
            "staff_cost_mode": tenant.staff_cost_mode,
            "staff_cost_value": str(tenant.staff_cost_value),
        }
    )
