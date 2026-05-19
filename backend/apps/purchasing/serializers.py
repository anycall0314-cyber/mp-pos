from rest_framework import serializers

from .models import PurchaseOrder, PurchaseOrderCategory, PurchaseOrderItem


class PurchaseOrderCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderCategory
        fields = ["id", "code", "name", "sort_order", "is_active"]


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_list_price = serializers.DecimalField(
        source="product.list_price",
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    product_barcode = serializers.CharField(
        source="product.barcode", read_only=True
    )

    class Meta:
        model = PurchaseOrderItem
        fields = [
            "id",
            "line_no",
            "product",
            "product_sku",
            "product_name",
            "product_list_price",
            "product_barcode",
            "qty",
            "billed_qty",
            "unit_price",
            "amount",
            "serial_numbers",
            "unit_landed_cost",
        ]
        read_only_fields = [
            "id",
            "amount",
            "unit_landed_cost",
            "product_sku",
            "product_name",
            "product_list_price",
            "product_barcode",
        ]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True, required=False)
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    tax_method_label = serializers.CharField(
        source="get_tax_method_display", read_only=True
    )
    invoice_form_label = serializers.CharField(
        source="get_invoice_form_display", read_only=True
    )
    category_code = serializers.CharField(source="category.code", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "no",
            "supplier",
            "supplier_code",
            "supplier_name",
            "warehouse",
            "warehouse_code",
            "warehouse_name",
            "doc_date",
            "category",
            "category_code",
            "category_name",
            "tax_method",
            "tax_method_label",
            "invoice_form",
            "invoice_form_label",
            "invoice_no",
            "invoice_date",
            "note",
            "created_by",
            "is_void",
            "subtotal",
            "tax_amount",
            "total_cost",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "no",
            "supplier_code",
            "supplier_name",
            "warehouse_code",
            "warehouse_name",
            "category_code",
            "category_name",
            "tax_method_label",
            "invoice_form_label",
            "is_void",
            "subtotal",
            "tax_amount",
            "total_cost",
            "created_at",
            "updated_at",
        ]

    def _save_items(self, po, items_data):
        for idx, item_data in enumerate(items_data, start=1):
            item_data.setdefault("line_no", idx)
            PurchaseOrderItem.objects.create(po=po, tenant=po.tenant, **item_data)

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        po = PurchaseOrder.objects.create(**validated_data)
        self._save_items(po, items_data)
        return po
