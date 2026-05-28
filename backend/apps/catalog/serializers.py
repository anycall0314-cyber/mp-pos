from rest_framework import serializers

from .models import Category, Product, ProductRelation


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
            "is_secondhand_default",
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
    # 配件商品的「關聯主機」清單(該配件適用於哪幾支主機)
    # write_only:寫入時帶 host product id 清單,系統用 ProductRelation 同步
    related_host_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
        help_text="關聯主機商品 id 清單(配件 → 主機)",
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
            "safety_stock",
            "lifecycle_status",
            "related_host_ids",
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

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # 讀取時把目前關聯的主機 id 也輸出 + 顯示用的 label
        rels = instance.host_relations.select_related("host_product").all()
        data["related_hosts"] = [
            {
                "id": r.host_product.id,
                "name": r.host_product.name,
                "sku": r.host_product.sku,
                "lifecycle_status": r.host_product.lifecycle_status,
            }
            for r in rels
        ]
        return data

    def create(self, validated_data):
        host_ids = validated_data.pop("related_host_ids", None)
        instance = super().create(validated_data)
        if host_ids is not None:
            self._sync_host_relations(instance, host_ids)
        return instance

    def update(self, instance, validated_data):
        host_ids = validated_data.pop("related_host_ids", None)
        instance = super().update(instance, validated_data)
        if host_ids is not None:
            self._sync_host_relations(instance, host_ids)
        return instance

    def _sync_host_relations(self, accessory, host_ids):
        """同步配件 → 主機關聯;傳入的 list 為唯一真相,缺的刪、多的加。"""
        tenant = accessory.tenant
        # 過濾掉 self-reference,防 user 不小心勾自己
        host_ids = [hid for hid in host_ids if hid != accessory.id]
        existing = {
            r.host_product_id: r
            for r in accessory.host_relations.all()
        }
        target = set(host_ids)
        # 刪掉不在新清單裡的
        for hid, rel in existing.items():
            if hid not in target:
                rel.delete()
        # 加上新的
        for hid in target:
            if hid not in existing:
                ProductRelation.objects.create(
                    tenant=tenant,
                    host_product_id=hid,
                    accessory_product=accessory,
                )
