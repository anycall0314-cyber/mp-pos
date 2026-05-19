from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Carrier, Customer, SalesPerson, SimCard, Supplier, TelecomPlan
from .serializers import (
    CarrierSerializer,
    CustomerSerializer,
    SalesPersonSerializer,
    SimCardSerializer,
    SupplierSerializer,
    TelecomPlanSerializer,
)


class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    search_fields = ["code", "name", "contact", "phone", "tax_id"]
    ordering_fields = ["code", "name", "created_at"]
    ordering = ["code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return Supplier.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    search_fields = ["phone", "name", "tax_id"]
    ordering_fields = ["phone", "name", "created_at"]
    ordering = ["phone"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return Customer.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=["get"], url_path="lookup")
    def lookup(self, request):
        """以電話精準查會員;查無回 404 由前端詢問是否新增。"""
        phone = request.query_params.get("phone", "").strip()
        if not phone:
            return Response(
                {"detail": "phone 為必填參數"}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            obj = self.get_queryset().get(phone=phone)
        except Customer.DoesNotExist:
            return Response(
                {"detail": "未登錄"}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(self.get_serializer(obj).data)


class SalesPersonViewSet(viewsets.ModelViewSet):
    serializer_class = SalesPersonSerializer
    search_fields = ["code", "name", "phone"]
    ordering_fields = ["code", "name", "created_at"]
    ordering = ["code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return SalesPerson.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class CarrierViewSet(viewsets.ModelViewSet):
    serializer_class = CarrierSerializer
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name"]
    ordering = ["code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return Carrier.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class SimCardViewSet(viewsets.ModelViewSet):
    serializer_class = SimCardSerializer
    search_fields = ["card_no", "vendor__code", "vendor__name", "note"]
    ordering_fields = ["card_no", "vendor__code", "status", "created_at"]
    ordering = ["vendor__code", "card_no"]
    filterset_fields = ["vendor", "status", "deposit_refunded"]

    def get_queryset(self):
        return SimCard.objects.for_tenant(self.request.tenant).select_related(
            "vendor"
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class TelecomPlanViewSet(viewsets.ModelViewSet):
    serializer_class = TelecomPlanSerializer
    search_fields = ["name", "code", "carrier__code", "carrier__name", "note"]
    ordering_fields = ["code", "monthly_fee", "contract_months", "commission"]
    ordering = ["carrier__code", "monthly_fee", "contract_months"]
    filterset_fields = ["carrier", "kind", "is_active"]

    def get_queryset(self):
        return TelecomPlan.objects.for_tenant(self.request.tenant).select_related(
            "carrier"
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)
