from datetime import date

from rest_framework import serializers

from apps.inventory.models import ProductSerial

from .models import (
    LegacyPurchase,
    SalesOrder,
    SalesOrderItem,
    SalesOrderItemSerial,
    SalesOrderPayment,
    SalesReturn,
    SalesReturnItem,
    SalesReturnItemSerial,
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
    product_warehouse_type = serializers.CharField(
        source="product.warehouse_type", read_only=True
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
            "product_warehouse_type",
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
            "product_warehouse_type",
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
            "invoice_voided",
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
            "invoice_voided",
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
            # 佣金一律以方案設定為準,忽略傳入值(防 API 繞過前端鎖)
            plan = item_data.get("telecom_plan")
            if plan is not None:
                item_data["commission"] = plan.commission
            else:
                item_data["commission"] = 0
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
        # 發票日期同理:非免用發票一律 today;免用(none/空)則 null
        invoice_form = validated_data.get("invoice_form", "")
        validated_data["invoice_date"] = (
            None if invoice_form in ("", "none") else date.today()
        )
        items_data = validated_data.pop("items", [])
        payments_data = validated_data.pop("payments", [])
        so = SalesOrder.objects.create(**validated_data)
        self._save_items(so, items_data)
        self._save_payments(so, payments_data)
        return so


class LegacyPurchaseSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.name", read_only=True)
    member_phone = serializers.CharField(source="member.phone", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    amount = serializers.SerializerMethodField()

    def get_amount(self, obj) -> str:
        return str(obj.amount)

    class Meta:
        model = LegacyPurchase
        fields = [
            "id",
            "member",
            "member_name",
            "member_phone",
            "product",
            "product_sku",
            "product_name",
            "qty",
            "unit_price",
            "amount",
            "doc_date",
            "source_no",
            "serial_no",
            "note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "member_name",
            "member_phone",
            "product_sku",
            "product_name",
            "amount",
            "created_at",
            "updated_at",
        ]


class SalesReturnItemSerialSerializer(serializers.ModelSerializer):
    serial_no = serializers.CharField(source="serial.serial_no", read_only=True)

    class Meta:
        model = SalesReturnItemSerial
        fields = ["id", "serial", "serial_no", "line_pos"]
        read_only_fields = ["id", "serial_no"]


class SalesReturnItemSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_requires_serial = serializers.BooleanField(
        source="product.requires_serial", read_only=True
    )
    product_is_virtual = serializers.BooleanField(
        source="product.is_virtual", read_only=True
    )
    serials = SalesReturnItemSerialSerializer(many=True, read_only=True)
    serial_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        write_only=True,
        required=False,
        queryset=ProductSerial.objects.all(),
    )

    class Meta:
        model = SalesReturnItem
        fields = [
            "id",
            "line_no",
            "original_item",
            "product",
            "product_sku",
            "product_name",
            "product_requires_serial",
            "product_is_virtual",
            "qty",
            "unit_price",
            "amount",
            "serials",
            "serial_ids",
        ]
        read_only_fields = [
            "id",
            "amount",
            "product",
            "product_sku",
            "product_name",
            "product_requires_serial",
            "product_is_virtual",
        ]


class SalesReturnSerializer(serializers.ModelSerializer):
    items = SalesReturnItemSerializer(many=True, required=False)
    original_so_no = serializers.CharField(source="original_so.no", read_only=True)
    original_so_doc_date = serializers.DateField(
        source="original_so.doc_date", read_only=True
    )
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    member_name = serializers.CharField(source="member.name", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = SalesReturn
        fields = [
            "id",
            "no",
            "original_so",
            "original_so_no",
            "original_so_doc_date",
            "customer",
            "customer_name",
            "customer_phone",
            "member",
            "member_name",
            "warehouse",
            "warehouse_code",
            "warehouse_name",
            "doc_date",
            "payment_method",
            "void_original_invoice",
            "note",
            "created_by",
            "is_void",
            "subtotal",
            "tax_amount",
            "total",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "no",
            "original_so_no",
            "original_so_doc_date",
            "customer_name",
            "customer_phone",
            "member_name",
            "warehouse_code",
            "warehouse_name",
            "is_void",
            "subtotal",
            "tax_amount",
            "total",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        from datetime import date

        validated_data["doc_date"] = date.today()
        items_data = validated_data.pop("items", [])
        # 由 original_so 自動帶 customer/member/warehouse 預設值,讓前端只送 original_so id 即可
        original_so = validated_data["original_so"]
        validated_data.setdefault("customer", original_so.customer)
        validated_data.setdefault("member", original_so.member)
        validated_data.setdefault("warehouse", original_so.warehouse)

        sr = SalesReturn.objects.create(**validated_data)
        for idx, item_data in enumerate(items_data, start=1):
            serial_ids = item_data.pop("serial_ids", [])
            oi = item_data["original_item"]
            item_data.setdefault("product", oi.product)
            item_data.setdefault("unit_price", oi.unit_price)
            item_data.setdefault("line_no", idx)
            # amount 在 commit 時計算
            item = SalesReturnItem.objects.create(
                sr=sr,
                tenant=sr.tenant,
                amount=0,
                **item_data,
            )
            for pos, s in enumerate(serial_ids, start=1):
                SalesReturnItemSerial.objects.create(
                    item=item,
                    tenant=sr.tenant,
                    serial=s,
                    line_pos=pos,
                )
        return sr
