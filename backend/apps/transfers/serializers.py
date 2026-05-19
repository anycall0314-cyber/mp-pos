from rest_framework import serializers

from apps.inventory.models import ProductSerial

from .models import TransferOrder, TransferOrderItem, TransferOrderItemSerial


class TransferOrderItemSerialSerializer(serializers.ModelSerializer):
    serial_no = serializers.CharField(source="serial.serial_no", read_only=True)

    class Meta:
        model = TransferOrderItemSerial
        fields = ["id", "serial", "serial_no", "line_pos"]
        read_only_fields = ["id", "serial_no"]


class TransferOrderItemSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_requires_serial = serializers.BooleanField(
        source="product.requires_serial", read_only=True
    )
    serials = TransferOrderItemSerialSerializer(many=True, read_only=True)
    serial_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        write_only=True,
        required=False,
        queryset=ProductSerial.objects.all(),
    )

    class Meta:
        model = TransferOrderItem
        fields = [
            "id",
            "line_no",
            "product",
            "product_sku",
            "product_name",
            "product_requires_serial",
            "qty",
            "note",
            "serials",
            "serial_ids",
        ]
        read_only_fields = [
            "id",
            "product_sku",
            "product_name",
            "product_requires_serial",
        ]


class TransferOrderSerializer(serializers.ModelSerializer):
    items = TransferOrderItemSerializer(many=True, required=False)
    from_warehouse_code = serializers.CharField(
        source="from_warehouse.code", read_only=True
    )
    from_warehouse_name = serializers.CharField(
        source="from_warehouse.name", read_only=True
    )
    to_warehouse_code = serializers.CharField(
        source="to_warehouse.code", read_only=True
    )
    to_warehouse_name = serializers.CharField(
        source="to_warehouse.name", read_only=True
    )

    class Meta:
        model = TransferOrder
        fields = [
            "id",
            "no",
            "from_warehouse",
            "from_warehouse_code",
            "from_warehouse_name",
            "to_warehouse",
            "to_warehouse_code",
            "to_warehouse_name",
            "doc_date",
            "note",
            "created_by",
            "is_void",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "no",
            "from_warehouse_code",
            "from_warehouse_name",
            "to_warehouse_code",
            "to_warehouse_name",
            "is_void",
            "created_at",
            "updated_at",
        ]

    def _save_items(self, to, items_data):
        for idx, item_data in enumerate(items_data, start=1):
            serial_objs = item_data.pop("serial_ids", [])
            item_data.setdefault("line_no", idx)
            item = TransferOrderItem.objects.create(
                to=to, tenant=to.tenant, **item_data
            )
            for pos, sn in enumerate(serial_objs):
                TransferOrderItemSerial.objects.create(
                    tenant=to.tenant,
                    item=item,
                    serial=sn,
                    line_pos=pos,
                )

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        to = TransferOrder.objects.create(**validated_data)
        self._save_items(to, items_data)
        return to
