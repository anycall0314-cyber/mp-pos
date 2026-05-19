from rest_framework import serializers

from .models import ProductSerial, StockMovement, Warehouse


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
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ProductSerial
        fields = [
            "id",
            "product",
            "product_sku",
            "product_name",
            "serial_no",
            "warehouse",
            "warehouse_code",
            "status",
            "status_label",
            "purchase_unit_cost",
            "received_at",
            "sold_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "product_sku",
            "product_name",
            "warehouse_code",
            "status_label",
            "purchase_unit_cost",
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
