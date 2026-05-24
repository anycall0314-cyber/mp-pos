from datetime import date

from rest_framework import serializers

from apps.inventory.models import ProductSerial

from .models import (
    SalesOrder,
    SalesOrderItem,
    SalesOrderItemSerial,
    SalesOrderPayment,
)


class SalesOrderPaymentSerializer(serializers.ModelSerializer):
    method_label = serializers.SerializerMethodField()
    method_kind = serializers.SerializerMethodField()

    def _method_master(self, obj):
        from apps.tenants.models import PaymentMethod

        cache = self.context.setdefault("_payment_method_cache", {})
        key = (obj.tenant_id, obj.method)
        if key not in cache:
            cache[key] = (
                PaymentMethod.objects.for_tenant(obj.tenant)
                .filter(code=obj.method)
                .first()
            )
        return cache[key]

    def get_method_label(self, obj):
        pm = self._method_master(obj)
        return pm.name if pm else obj.method

    def get_method_kind(self, obj):
        pm = self._method_master(obj)
        return pm.kind if pm else None

    class Meta:
        model = SalesOrderPayment
        fields = [
            "id",
            "method",
            "method_label",
            "method_kind",
            "amount",
            "note",
            "line_no",
        ]
        read_only_fields = ["id", "method_label", "method_kind"]


class SalesOrderItemSerialSerializer(serializers.ModelSerializer):
    serial_no = serializers.CharField(source="serial.serial_no", read_only=True)

    class Meta:
        model = SalesOrderItemSerial
        fields = ["id", "serial", "serial_no", "line_pos"]
        read_only_fields = ["id", "serial_no"]


class SalesOrderItemSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_requires_serial = serializers.BooleanField(
        source="product.requires_serial", read_only=True
    )
    product_allows_telecom_line = serializers.BooleanField(
        source="product.allows_telecom_line", read_only=True
    )
    product_allows_commission = serializers.BooleanField(
        source="product.allows_commission", read_only=True
    )
    product_is_virtual = serializers.BooleanField(
        source="product.is_virtual", read_only=True
    )
    product_counts_cash = serializers.BooleanField(
        source="product.counts_cash", read_only=True
    )
    product_counts_margin = serializers.BooleanField(
        source="product.counts_margin", read_only=True
    )
    # read:序號物件列表;write:接 serial_ids 陣列
    serials = SalesOrderItemSerialSerializer(many=True, read_only=True)
    serial_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        write_only=True,
        required=False,
        queryset=ProductSerial.objects.all(),
    )
    telecom_plan_code = serializers.CharField(
        source="telecom_plan.code", read_only=True
    )
    telecom_plan_kind = serializers.CharField(
        source="telecom_plan.kind", read_only=True
    )
    telecom_plan_display = serializers.SerializerMethodField()
    sim_card_no = serializers.CharField(source="sim_card.card_no", read_only=True)

    def get_telecom_plan_display(self, obj):
        p = obj.telecom_plan
        if not p:
            return ""
        return f"{p.carrier.code} {p.monthly_fee}/{p.contract_months}月 {p.get_kind_display()}"

    class Meta:
        model = SalesOrderItem
        fields = [
            "id",
            "line_no",
            "product",
            "product_sku",
            "product_name",
            "product_requires_serial",
            "product_allows_telecom_line",
            "product_allows_commission",
            "product_is_virtual",
            "product_counts_cash",
            "product_counts_margin",
            "qty",
            "unit_price",
            "amount",
            "serials",
            "serial_ids",
            "cost_at_post",
            "sim_card",
            "sim_card_no",
            "msisdn",
            "telecom_plan",
            "telecom_plan_code",
            "telecom_plan_kind",
            "telecom_plan_display",
            "commission",
            "activation_date",
            "note",
        ]
        read_only_fields = [
            "id",
            "cost_at_post",
            "product_sku",
            "product_name",
            "product_requires_serial",
            "product_allows_telecom_line",
            "product_allows_commission",
            "product_is_virtual",
            "product_counts_cash",
            "product_counts_margin",
        ]


class SalesOrderSerializer(serializers.ModelSerializer):
    items = SalesOrderItemSerializer(many=True, required=False)
    payments = SalesOrderPaymentSerializer(many=True, required=False)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_kind_label = serializers.CharField(
        source="customer.get_kind_display", read_only=True
    )
    member_phone = serializers.CharField(source="member.phone", read_only=True)
    member_name = serializers.CharField(source="member.name", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    sales_person_code = serializers.CharField(
        source="sales_person.code", read_only=True
    )
    sales_person_name = serializers.CharField(
        source="sales_person.name", read_only=True
    )
    tax_method_label = serializers.CharField(
        source="get_tax_method_display", read_only=True
    )

    class Meta:
        model = SalesOrder
        fields = [
            "id",
            "no",
            "customer",
            "customer_phone",
            "customer_name",
            "customer_kind_label",
            "member",
            "member_phone",
            "member_name",
            "warehouse",
            "warehouse_code",
            "warehouse_name",
            "doc_date",
            "sales_type",
            "tax_method",
            "tax_method_label",
            "buyer_tax_id",
            "invoice_form",
            "invoice_no",
            "invoice_date",
            "note",
            "sales_person",
            "sales_person_code",
            "sales_person_name",
            "created_by",
            "is_void",
            "subtotal",
            "tax_amount",
            "total",
            "items",
            "payments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "no",
            "customer_phone",
            "customer_name",
            "customer_kind_label",
            "member_phone",
            "member_name",
            "warehouse_code",
            "warehouse_name",
            "sales_person_code",
            "sales_person_name",
            "is_void",
            "tax_method_label",
            "subtotal",
            "tax_amount",
            "total",
            "created_at",
            "updated_at",
        ]

    def _save_items(self, so, items_data):
        for idx, item_data in enumerate(items_data, start=1):
            serial_objs = item_data.pop("serial_ids", [])
            item_data.setdefault("line_no", idx)
            item = SalesOrderItem.objects.create(so=so, tenant=so.tenant, **item_data)
            for pos, sn in enumerate(serial_objs):
                SalesOrderItemSerial.objects.create(
                    tenant=so.tenant,
                    item=item,
                    serial=sn,
                    line_pos=pos,
                )

    def _save_payments(self, so, payments_data):
        for idx, p in enumerate(payments_data, start=1):
            p.setdefault("line_no", idx)
            SalesOrderPayment.objects.create(so=so, tenant=so.tenant, **p)

    def create(self, validated_data):
        # 單據日期一律強制為系統當天,忽略傳入值以防竄改
        validated_data["doc_date"] = date.today()
        items_data = validated_data.pop("items", [])
        payments_data = validated_data.pop("payments", [])
        so = SalesOrder.objects.create(**validated_data)
        self._save_items(so, items_data)
        self._save_payments(so, payments_data)
        return so
