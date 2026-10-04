from rest_framework import serializers

from apps.core.tenant_fields import TenantScopedRelatedFieldsMixin
from rest_framework.exceptions import APIException

from .models import (
    IntakeBatch,
    IntakeDocument,
    IntakeItem,
    IntakeReceivedUnit,
    IntakeUnitIdentifier,
    ProductAlias,
)
from .normalize import alias_key


class IntakeUnitIdentifierSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = IntakeUnitIdentifier
        fields = ["id", "kind", "raw_value", "normalized_value", "is_primary"]


class IntakeReceivedUnitSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    identifiers = IntakeUnitIdentifierSerializer(many=True, read_only=True)

    class Meta:
        model = IntakeReceivedUnit
        fields = ["id", "unit_index", "source", "identifiers"]


class CaptureUnitIdentifierSerializer(TenantScopedRelatedFieldsMixin, serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=IntakeUnitIdentifier.Kind.choices, required=False
    )
    value = serializers.CharField()
    is_primary = serializers.BooleanField(default=False)


class CaptureUnitSerializer(TenantScopedRelatedFieldsMixin, serializers.Serializer):
    identifiers = CaptureUnitIdentifierSerializer(many=True)


class CaptureUnitsSerializer(TenantScopedRelatedFieldsMixin, serializers.Serializer):
    units = CaptureUnitSerializer(many=True)


class IntakeDocumentSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = IntakeDocument
        fields = ["id", "image_url", "original_filename", "ocr_status", "ocr_message", "created_at"]

    def get_image_url(self, obj):
        if not obj.image:
            return ""
        request = self.context.get("request")
        url = obj.image.url
        return request.build_absolute_uri(url) if request else url


class AliasConflict(APIException):
    status_code = 409
    default_detail = "這個叫法已經指到別的商品"
    default_code = "alias_conflict"


class ProductAliasSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default="")
    created_by_name = serializers.CharField(
        source="created_by.username", read_only=True, default=""
    )
    updated_by_name = serializers.CharField(
        source="updated_by.username", read_only=True, default=""
    )

    class Meta:
        model = ProductAlias
        fields = [
            "id", "product", "product_name", "product_sku", "supplier", "supplier_name",
            "kind", "value", "normalized_value", "verified", "source", "note", "is_active",
            "created_by_name", "updated_by_name", "created_at", "updated_at",
        ]
        read_only_fields = ["normalized_value", "created_at", "updated_at"]

    def _own(self, obj, label):
        """外鍵必須是自己公司的。ModelSerializer 預設用 `.objects.all()`,
        不擋的話可以把別名掛到別家的商品 / 廠商上。"""
        request = self.context.get("request")
        if obj is not None and request is not None and obj.tenant_id != request.tenant.id:
            raise serializers.ValidationError(f"找不到指定的{label}")
        return obj

    def validate_product(self, value):
        return self._own(value, "商品")

    def validate_supplier(self, value):
        return self._own(value, "廠商")

    def validate(self, attrs):
        """同一句話已經確認指到別的商品 → 明確回衝突,不靠資料庫噴 500。"""
        inst = self.instance
        get = lambda k, d=None: attrs[k] if k in attrs else (getattr(inst, k) if inst else d)  # noqa: E731
        if not get("is_active", True) or not get("verified", True):
            return attrs
        request = self.context.get("request")
        kind, supplier, product = get("kind"), get("supplier"), get("product")
        key = alias_key(get("value", ""))
        if request is None or not key:
            return attrs
        qs = ProductAlias.objects.for_tenant(request.tenant).filter(
            is_active=True, verified=True, normalized_value=key,
        )
        qs = qs.filter(kind="barcode") if kind == "barcode" else qs.filter(
            kind=kind, supplier=supplier
        )
        if inst is not None:
            qs = qs.exclude(pk=inst.pk)
        other = qs.select_related("product").first()
        if other is not None:
            if other.product_id == product.id:
                raise serializers.ValidationError("這個叫法已經記在這個商品上了")
            raise AliasConflict(
                f"這個叫法已經指到「{other.product.name}」。"
                "要改指請管理員先把那一筆停用"
            )
        return attrs


class IntakeItemSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    matched_product_name = serializers.CharField(source="matched_product.name", read_only=True, default="")
    matched_product_sku = serializers.CharField(source="matched_product.sku", read_only=True, default="")
    # effective_* = 有修正取修正、否則取 raw;前端顯示與過帳都看這組
    effective_name = serializers.CharField(read_only=True)
    effective_qty = serializers.IntegerField(read_only=True)
    effective_unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    effective_serials = serializers.ListField(read_only=True)
    # 條碼與料號現在會被學成別名,前端必須看得到也改得到,
    # 不然店員是看品名選商品,卻順手核准了一個他沒看過的識別碼
    effective_barcode = serializers.CharField(read_only=True)
    effective_vendor_sku = serializers.CharField(read_only=True)
    received_units = IntakeReceivedUnitSerializer(many=True, read_only=True)
    requires_serial = serializers.BooleanField(
        source="matched_product.requires_serial", read_only=True, default=False
    )

    class Meta:
        model = IntakeItem
        fields = [
            "id", "line_no", "raw_text", "raw_barcode", "raw_vendor_sku",
            "raw_qty", "raw_unit_price", "raw_serials",
            "corrected_name", "corrected_qty", "corrected_unit_price",
            "corrected_barcode", "corrected_vendor_sku", "corrected_serials",
            "effective_name", "effective_qty", "effective_unit_price", "effective_serials",
            "effective_barcode", "effective_vendor_sku",
            "matched_product", "matched_product_name", "matched_product_sku",
            "requires_serial", "received_units",
            "match_status", "match_confidence", "candidates", "ocr_confidence", "note",
            "alias_conflicts",
        ]


class IntakeBatchSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    items = IntakeItemSerializer(many=True, read_only=True)
    documents = IntakeDocumentSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default="")
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True, default="")
    committed_purchase_order_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = IntakeBatch
        fields = [
            "id", "source", "supplier", "supplier_name", "warehouse", "warehouse_name",
            "vendor_doc_no", "tax_method", "document_total", "status", "note",
            "committed_purchase_order_id", "created_at", "items", "documents",
        ]


class IntakeCreateSerializer(TenantScopedRelatedFieldsMixin, serializers.Serializer):
    """建立待確認批次:貼一段文字 + 選(選填)廠商 / 倉。"""
    raw_text = serializers.CharField()
    source = serializers.ChoiceField(
        choices=IntakeBatch.Source.choices, default=IntakeBatch.Source.MANUAL_TEXT
    )
    supplier = serializers.IntegerField(required=False, allow_null=True)
    warehouse = serializers.IntegerField(required=False, allow_null=True)
    vendor_doc_no = serializers.CharField(required=False, allow_blank=True, default="")


class MatchItemSerializer(TenantScopedRelatedFieldsMixin, serializers.Serializer):
    """把一行對應到一個既有商品。"""
    product = serializers.IntegerField()
    learn_alias = serializers.BooleanField(default=True)
    # 選到已停用的商品時,要明確帶 restore=true 才會恢復(且限公司管理員)
    restore = serializers.BooleanField(default=False)
    # 這行的叫法已經確認指到別的商品時,要明確帶 repoint=true 才會改指
    # (且限公司管理員);沒帶就記成衝突,不動原本的對應
    repoint = serializers.BooleanField(default=False)


class RememberPhraseSerializer(TenantScopedRelatedFieldsMixin, serializers.Serializer):
    """「記住這個叫法」:把一句話記到一個既有商品上。"""
    product = serializers.IntegerField()
    value = serializers.CharField(max_length=500)
    supplier = serializers.IntegerField(required=False, allow_null=True)
    # 這句話已經確認指到別的商品時,明確要求改指(限公司管理員)
    repoint = serializers.BooleanField(default=False)


class CorrectIntakeItemSerializer(TenantScopedRelatedFieldsMixin, serializers.Serializer):
    """人工修正一行;只帶要改的欄位。"""
    name = serializers.CharField(required=False, allow_blank=True)
    qty = serializers.IntegerField(required=False, min_value=1)
    unit_price = serializers.DecimalField(required=False, max_digits=14, decimal_places=2)
    barcode = serializers.CharField(required=False, allow_blank=True)
    vendor_sku = serializers.CharField(required=False, allow_blank=True)
    serials = serializers.ListField(child=serializers.CharField(), required=False)


class SetHeaderSerializer(TenantScopedRelatedFieldsMixin, serializers.Serializer):
    """修正批次單頭;只帶要改的欄位。"""
    supplier = serializers.IntegerField(required=False, allow_null=True)
    warehouse = serializers.IntegerField(required=False, allow_null=True)
    tax_method = serializers.ChoiceField(
        choices=IntakeBatch.TaxMethod.choices, required=False
    )
    vendor_doc_no = serializers.CharField(required=False, allow_blank=True)
    document_total = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )


class NewProductForItemSerializer(TenantScopedRelatedFieldsMixin, serializers.Serializer):
    """從一行建立新商品並對應。"""
    name = serializers.CharField(required=False, allow_blank=True, default="")
    category = serializers.IntegerField()
    capacity = serializers.CharField(required=False, allow_blank=True, default="")
    color = serializers.CharField(required=False, allow_blank=True, default="")
    region_version = serializers.CharField(required=False, allow_blank=True, default="")
    requires_serial = serializers.BooleanField(default=True)
    learn_alias = serializers.BooleanField(default=True)
    # 系統說可能重複時,要寫下哪裡不同才能建
    distinct_reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=200
    )
