from rest_framework import serializers

from .models import (
    IntakeBatch,
    IntakeDocument,
    IntakeItem,
    IntakeReceivedUnit,
    IntakeUnitIdentifier,
    ProductAlias,
)


class IntakeUnitIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntakeUnitIdentifier
        fields = ["id", "kind", "raw_value", "normalized_value", "is_primary"]


class IntakeReceivedUnitSerializer(serializers.ModelSerializer):
    identifiers = IntakeUnitIdentifierSerializer(many=True, read_only=True)

    class Meta:
        model = IntakeReceivedUnit
        fields = ["id", "unit_index", "source", "identifiers"]


class CaptureUnitIdentifierSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=IntakeUnitIdentifier.Kind.choices, required=False
    )
    value = serializers.CharField()
    is_primary = serializers.BooleanField(default=False)


class CaptureUnitSerializer(serializers.Serializer):
    identifiers = CaptureUnitIdentifierSerializer(many=True)


class CaptureUnitsSerializer(serializers.Serializer):
    units = CaptureUnitSerializer(many=True)


class IntakeDocumentSerializer(serializers.ModelSerializer):
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


class ProductAliasSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default="")

    class Meta:
        model = ProductAlias
        fields = [
            "id", "product", "product_name", "product_sku", "supplier", "supplier_name",
            "kind", "value", "normalized_value", "verified", "source", "note", "is_active",
        ]
        read_only_fields = ["normalized_value"]


class IntakeItemSerializer(serializers.ModelSerializer):
    matched_product_name = serializers.CharField(source="matched_product.name", read_only=True, default="")
    matched_product_sku = serializers.CharField(source="matched_product.sku", read_only=True, default="")
    # effective_* = 有修正取修正、否則取 raw;前端顯示與過帳都看這組
    effective_name = serializers.CharField(read_only=True)
    effective_qty = serializers.IntegerField(read_only=True)
    effective_unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    effective_serials = serializers.ListField(read_only=True)
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
            "matched_product", "matched_product_name", "matched_product_sku",
            "requires_serial", "received_units",
            "match_status", "match_confidence", "candidates", "ocr_confidence", "note",
        ]


class IntakeBatchSerializer(serializers.ModelSerializer):
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


class IntakeCreateSerializer(serializers.Serializer):
    """建立待確認批次:貼一段文字 + 選(選填)廠商 / 倉。"""
    raw_text = serializers.CharField()
    source = serializers.ChoiceField(
        choices=IntakeBatch.Source.choices, default=IntakeBatch.Source.MANUAL_TEXT
    )
    supplier = serializers.IntegerField(required=False, allow_null=True)
    warehouse = serializers.IntegerField(required=False, allow_null=True)
    vendor_doc_no = serializers.CharField(required=False, allow_blank=True, default="")


class MatchItemSerializer(serializers.Serializer):
    """把一行對應到一個既有商品。"""
    product = serializers.IntegerField()
    learn_alias = serializers.BooleanField(default=True)


class CorrectIntakeItemSerializer(serializers.Serializer):
    """人工修正一行;只帶要改的欄位。"""
    name = serializers.CharField(required=False, allow_blank=True)
    qty = serializers.IntegerField(required=False, min_value=1)
    unit_price = serializers.DecimalField(required=False, max_digits=14, decimal_places=2)
    barcode = serializers.CharField(required=False, allow_blank=True)
    vendor_sku = serializers.CharField(required=False, allow_blank=True)
    serials = serializers.ListField(child=serializers.CharField(), required=False)


class SetHeaderSerializer(serializers.Serializer):
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


class NewProductForItemSerializer(serializers.Serializer):
    """從一行建立新商品並對應。"""
    name = serializers.CharField(required=False, allow_blank=True, default="")
    category = serializers.IntegerField()
    capacity = serializers.CharField(required=False, allow_blank=True, default="")
    color = serializers.CharField(required=False, allow_blank=True, default="")
    region_version = serializers.CharField(required=False, allow_blank=True, default="")
    requires_serial = serializers.BooleanField(default=True)
    learn_alias = serializers.BooleanField(default=True)
