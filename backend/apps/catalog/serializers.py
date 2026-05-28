from rest_framework import serializers

from .models import (
    Brand,
    Category,
    PartTemplate,
    PartTemplateItem,
    PhoneSeries,
    Product,
    ProductRelation,
)


class BrandSerializer(serializers.ModelSerializer):
    series_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Brand
        fields = [
            "id",
            "code",
            "name",
            "sort_order",
            "is_active",
            "series_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "series_count", "created_at", "updated_at"]


class PhoneSeriesSerializer(serializers.ModelSerializer):
    brand_code = serializers.CharField(source="brand.code", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)

    class Meta:
        model = PhoneSeries
        fields = [
            "id",
            "brand",
            "brand_code",
            "brand_name",
            "code",
            "name",
            "sort_order",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "brand_code",
            "brand_name",
            "created_at",
            "updated_at",
        ]


class PartTemplateItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartTemplateItem
        fields = [
            "id",
            "name",
            "code",
            "sort_order",
            "default_cost",
            "default_safety_stock",
            "shared_across_models",
        ]


class PartTemplateSerializer(serializers.ModelSerializer):
    items = PartTemplateItemSerializer(many=True, read_only=True)
    items_input = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True
    )

    class Meta:
        model = PartTemplate
        fields = [
            "id",
            "name",
            "note",
            "is_active",
            "items",
            "items_input",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "items", "created_at", "updated_at"]

    def create(self, validated_data):
        items = validated_data.pop("items_input", None) or []
        instance = super().create(validated_data)
        self._sync_items(instance, items)
        return instance

    def update(self, instance, validated_data):
        items = validated_data.pop("items_input", None)
        instance = super().update(instance, validated_data)
        if items is not None:
            self._sync_items(instance, items)
        return instance

    def _sync_items(self, template, items):
        existing = {it.id: it for it in template.items.all()}
        seen = set()
        for idx, row in enumerate(items):
            item_id = row.get("id")
            if item_id and item_id in existing:
                it = existing[item_id]
                it.name = row.get("name", it.name)
                it.code = row.get("code", it.code)
                it.sort_order = row.get("sort_order", idx)
                it.default_cost = row.get("default_cost", it.default_cost)
                it.default_safety_stock = row.get(
                    "default_safety_stock", it.default_safety_stock
                )
                it.shared_across_models = bool(
                    row.get("shared_across_models", it.shared_across_models)
                )
                it.save()
                seen.add(item_id)
            else:
                PartTemplateItem.objects.create(
                    tenant=template.tenant,
                    template=template,
                    name=row.get("name", ""),
                    code=row.get("code", ""),
                    sort_order=row.get("sort_order", idx),
                    default_cost=row.get("default_cost", 0),
                    default_safety_stock=row.get("default_safety_stock", 0),
                    shared_across_models=bool(
                        row.get("shared_across_models", False)
                    ),
                )
        for itid, it in existing.items():
            if itid not in seen:
                it.delete()


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
    # Brand / Series 顯示用(read-only label)
    brand_code = serializers.CharField(source="brand.code", read_only=True, default="")
    brand_name = serializers.CharField(source="brand.name", read_only=True, default="")
    series_name = serializers.CharField(source="series.name", read_only=True, default="")
    phone_model_name = serializers.CharField(read_only=True)
    phone_model_key = serializers.CharField(read_only=True)
    last_purchase_price = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, allow_null=True
    )
    # (舊)配件 → 主機 id 清單;保留作向後相容,新前端請改用 related_host_keys
    related_host_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
        help_text="(deprecated)請用 related_host_keys 改以機型 key 為單位",
    )
    # (新)配件 → 機型 key 清單,以機型為單位涵蓋該款所有 SKU 變體
    related_host_keys = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        write_only=True,
        help_text="配件相容的機型 key 清單",
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
            "accessory_type",
            "attach_rate",
            "replenish_days",
            "brand",
            "brand_code",
            "brand_name",
            "series",
            "series_name",
            "generation",
            "model_suffix",
            "phone_model_name",
            "phone_model_key",
            "is_variant",
            "warehouse_type",
            "is_externally_sellable",
            "external_sale_price",
            "min_sale_price",
            "related_host_ids",
            "related_host_keys",
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
        # 把目前關聯的「機型」也輸出(以 host_model_key 為單位 group)
        rels = list(instance.host_relations.select_related("host_product").all())
        seen: dict[str, dict] = {}
        for r in rels:
            key = r.host_model_key or (
                r.host_product.phone_model_key if r.host_product_id else ""
            )
            if not key or key in seen:
                continue
            host = r.host_product
            seen[key] = {
                "model_key": key,
                "model_name": host.phone_model_name if host else key,
                "sample_sku_id": host.id if host else None,
                "sample_sku_name": host.name if host else "",
                "lifecycle_status": host.lifecycle_status if host else "",
            }
        data["related_hosts"] = list(seen.values())
        return data

    def create(self, validated_data):
        host_keys = validated_data.pop("related_host_keys", None)
        host_ids = validated_data.pop("related_host_ids", None)
        instance = super().create(validated_data)
        if host_keys is not None:
            self._sync_host_relations_by_keys(instance, host_keys)
        elif host_ids is not None:
            self._sync_host_relations_by_ids(instance, host_ids)
        return instance

    def update(self, instance, validated_data):
        host_keys = validated_data.pop("related_host_keys", None)
        host_ids = validated_data.pop("related_host_ids", None)
        instance = super().update(instance, validated_data)
        if host_keys is not None:
            self._sync_host_relations_by_keys(instance, host_keys)
        elif host_ids is not None:
            self._sync_host_relations_by_ids(instance, host_ids)
        return instance

    def _sync_host_relations_by_keys(self, accessory, host_keys):
        """同步配件 → 機型關聯(以 model_key 為單位,涵蓋該款所有 SKU 變體)。"""
        tenant = accessory.tenant
        target_keys = {k.strip().lower() for k in host_keys if k and k.strip()}
        existing = {r.host_model_key: r for r in accessory.host_relations.all()}
        for key, rel in existing.items():
            if key not in target_keys:
                rel.delete()
        if not target_keys - set(existing):
            return
        # 為了 host_product FK,撈一遍主機清單找代表 SKU
        candidate_hosts = list(
            Product.objects.for_tenant(tenant).filter(
                accessory_type=Product.AccessoryType.NONE,
                is_active=True,
            )
        )
        for key in target_keys:
            if key in existing:
                continue
            sample = next(
                (p for p in candidate_hosts if p.phone_model_key == key),
                None,
            )
            if sample is None or sample.id == accessory.id:
                continue
            ProductRelation.objects.create(
                tenant=tenant,
                host_product=sample,
                host_model_key=key,
                accessory_product=accessory,
            )

    def _sync_host_relations_by_ids(self, accessory, host_ids):
        """(legacy)接收 host SKU id 清單,內部轉成 model_key 同步。"""
        tenant = accessory.tenant
        ids = [hid for hid in host_ids if hid != accessory.id]
        hosts = list(Product.objects.for_tenant(tenant).filter(id__in=ids))
        keys = [h.phone_model_key for h in hosts if h.phone_model_key]
        self._sync_host_relations_by_keys(accessory, keys)
