from rest_framework import serializers

from .models import IntakeBatch, IntakeItem, ProductAlias


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

    class Meta:
        model = IntakeItem
        fields = [
            "id", "line_no", "raw_text", "raw_barcode", "raw_vendor_sku",
            "raw_qty", "raw_unit_price", "raw_serials",
            "matched_product", "matched_product_name", "matched_product_sku",
            "match_status", "match_confidence", "candidates", "note",
        ]


class IntakeBatchSerializer(serializers.ModelSerializer):
    items = IntakeItemSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default="")
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True, default="")

    class Meta:
        model = IntakeBatch
        fields = [
            "id", "source", "supplier", "supplier_name", "warehouse", "warehouse_name",
            "vendor_doc_no", "status", "note", "committed_purchase_order_id",
            "created_at", "items",
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


class NewProductForItemSerializer(serializers.Serializer):
    """從一行建立新商品並對應。"""
    name = serializers.CharField(required=False, allow_blank=True, default="")
    category = serializers.IntegerField()
    capacity = serializers.CharField(required=False, allow_blank=True, default="")
    color = serializers.CharField(required=False, allow_blank=True, default="")
    region_version = serializers.CharField(required=False, allow_blank=True, default="")
    requires_serial = serializers.BooleanField(default=True)
    learn_alias = serializers.BooleanField(default=True)
