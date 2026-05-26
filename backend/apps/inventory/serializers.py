from rest_framework import serializers

from .models import ProductSerial, StockBalance, StockMovement, Warehouse


class _TenantUniqueMixin:
    def _tenant_unique(self, queryset, field_name: str, value):
        request = self.context.get("request")
        if request is None:
            return value
        qs = queryset.for_tenant(request.tenant).filter(**{field_name: value})
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("已存在相同值")
        return value


class WarehouseSerializer(_TenantUniqueMixin, serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = [
            "id",
            "code",
            "name",
            "address",
            "phone",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_code(self, value):
        return self._tenant_unique(Warehouse.objects, "code", value)


class ProductSerialSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_is_secondhand = serializers.BooleanField(
        source="product.is_secondhand", read_only=True
    )
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    condition_grade_label = serializers.CharField(
        source="get_condition_grade_display", read_only=True
    )
    acquired_from_member_phone = serializers.CharField(
        source="acquired_from_member.phone", read_only=True, default=""
    )
    acquired_from_member_name = serializers.CharField(
        source="acquired_from_member.name", read_only=True, default=""
    )
    acquired_via_sales_order_no = serializers.CharField(
        source="acquired_via_sales_order.no", read_only=True, default=""
    )

    class Meta:
        model = ProductSerial
        fields = [
            "id",
            "product",
            "product_sku",
            "product_name",
            "product_is_secondhand",
            "serial_no",
            "warehouse",
            "warehouse_code",
            "status",
            "status_label",
            "purchase_unit_cost",
            "condition_grade",
            "condition_grade_label",
            "custom_unit_price",
            "battery_health",
            "condition_note",
            "acquired_from_member",
            "acquired_from_member_phone",
            "acquired_from_member_name",
            "acquired_via_sales_order",
            "acquired_via_sales_order_no",
            "received_at",
            "sold_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "product_sku",
            "product_name",
            "product_is_secondhand",
            "warehouse_code",
            "status_label",
            "purchase_unit_cost",
            "condition_grade_label",
            "acquired_from_member_phone",
            "acquired_from_member_name",
            "acquired_via_sales_order",
            "acquired_via_sales_order_no",
            "created_at",
            "updated_at",
        ]


class StockBalanceSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockBalance
        fields = [
            "id",
            "product",
            "product_sku",
            "product_name",
            "warehouse",
            "warehouse_code",
            "warehouse_name",
            "qty",
            "weighted_avg_cost",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "product_sku",
            "product_name",
            "warehouse_code",
            "warehouse_name",
            "qty",
            "weighted_avg_cost",
            "created_at",
            "updated_at",
        ]


class StockMovementSerializer(serializers.ModelSerializer):
    serial_no = serializers.CharField(source="serial.serial_no", read_only=True)
    type_label = serializers.CharField(source="get_movement_type_display", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "serial",
            "serial_no",
            "movement_type",
            "type_label",
            "from_warehouse",
            "to_warehouse",
            "ref_doc_type",
            "ref_doc_id",
            "note",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "serial_no", "type_label"]
