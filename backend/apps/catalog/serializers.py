from rest_framework import serializers

from .models import Category, Product


class _TenantUniqueMixin:
    """檢查 per-tenant 唯一性的小 helper。"""

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


class CategorySerializer(_TenantUniqueMixin, serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = [
            "id",
            "code",
            "name",
            "sort_order",
            "is_active",
            "next_sku_seq",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "next_sku_seq", "created_at", "updated_at"]

    def validate_code(self, value):
        return self._tenant_unique(Category.objects, "code", value)

    def validate_name(self, value):
        return self._tenant_unique(Category.objects, "name", value)


class ProductSerializer(_TenantUniqueMixin, serializers.ModelSerializer):
    stock_qty = serializers.IntegerField(read_only=True)
    category_code = serializers.CharField(source="category.code", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    last_purchase_price = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, allow_null=True
    )

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "spec",
            "barcode",
            "category",
            "category_code",
            "category_name",
            "weighted_avg_cost",
            "list_price",
            "last_purchase_price",
            "requires_serial",
            "allows_telecom_line",
            "allows_commission",
            "is_virtual",
            "is_secondhand",
            "counts_cash",
            "counts_margin",
            "is_active",
            "stock_qty",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "sku",
            "weighted_avg_cost",
            "last_purchase_price",
            "stock_qty",
            "category_code",
            "category_name",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        return self._tenant_unique(Product.objects, "name", value)
