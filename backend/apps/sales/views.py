from django.db import transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.inventory.models import Warehouse
from apps.inventory.serializers import ProductSerialSerializer
from apps.parties.models import Customer

from .models import SalesOrder
from .serializers import SalesOrderSerializer
from .services import (
    SalesOrderError,
    SecondhandIntakeError,
    acquire_secondhand_from_member,
    commit_sales_order,
    void_sales_order,
)


class SecondhandAcquisitionInputSerializer(serializers.Serializer):
    member = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all())
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    serial_no = serializers.CharField(max_length=80)
    condition_grade = serializers.CharField(max_length=2)
    custom_unit_price = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )
    battery_health = serializers.IntegerField(
        min_value=0, max_value=100, required=False, allow_null=True
    )
    condition_note = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    acquisition_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    payment_method_code = serializers.CharField(max_length=20)
    doc_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )


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
        "member": ["exact"],
        "sales_person": ["exact"],
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

    @action(detail=False, methods=["post"], url_path="secondhand-acquisition")
    def secondhand_acquisition(self, request):
        """個人收購入庫:一個 transaction 內建立中古機序號 + 收購二手銷貨單。"""
        tenant = request.tenant
        in_ser = SecondhandAcquisitionInputSerializer(data=request.data)
        in_ser.is_valid(raise_exception=True)
        data = in_ser.validated_data

        member = data["member"]
        warehouse = data["warehouse"]
        product = data["product"]
        if member.tenant_id != tenant.id:
            return Response(
                {"detail": "會員不屬於此租戶"}, status=status.HTTP_400_BAD_REQUEST
            )
        if warehouse.tenant_id != tenant.id:
            return Response(
                {"detail": "倉庫不屬於此租戶"}, status=status.HTTP_400_BAD_REQUEST
            )
        if product.tenant_id != tenant.id:
            return Response(
                {"detail": "商品不屬於此租戶"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            serial, so = acquire_secondhand_from_member(
                tenant=tenant,
                member=member,
                warehouse=warehouse,
                secondhand_product=product,
                serial_no=data["serial_no"].strip(),
                condition_grade=data["condition_grade"],
                custom_unit_price=data.get("custom_unit_price"),
                acquisition_price=data["acquisition_price"],
                payment_method_code=data["payment_method_code"],
                battery_health=data.get("battery_health"),
                condition_note=data.get("condition_note", ""),
                doc_date=data.get("doc_date"),
                note=data.get("note", ""),
            )
        except SecondhandIntakeError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        so = self.get_queryset().get(pk=so.pk)
        return Response(
            {
                "serial": ProductSerialSerializer(serial).data,
                "sales_order": self.get_serializer(so).data,
            },
            status=status.HTTP_201_CREATED,
        )
