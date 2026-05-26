from rest_framework import serializers

from .models import CashAdjustment, PettyExpense, PhoneBillCollection


class PettyExpenseSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(
        source="get_category_display", read_only=True
    )
    warehouse_code = serializers.CharField(
        source="warehouse.code", read_only=True
    )
    warehouse_name = serializers.CharField(
        source="warehouse.name", read_only=True
    )
    payment_method_code = serializers.CharField(
        source="payment_method.code", read_only=True
    )
    payment_method_name = serializers.CharField(
        source="payment_method.name", read_only=True
    )
    payment_method_kind = serializers.CharField(
        source="payment_method.kind", read_only=True
    )
    handled_by_name = serializers.CharField(
        source="handled_by.name", read_only=True, default=""
    )
    handled_by_code = serializers.CharField(
        source="handled_by.code", read_only=True, default=""
    )

    class Meta:
        model = PettyExpense
        fields = [
            "id",
            "no",
            "warehouse",
            "warehouse_code",
            "warehouse_name",
            "doc_date",
            "category",
            "category_label",
            "amount",
            "payment_method",
            "payment_method_code",
            "payment_method_name",
            "payment_method_kind",
            "payee",
            "handled_by",
            "handled_by_name",
            "handled_by_code",
            "note",
            "is_void",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "no",
            "warehouse_code",
            "warehouse_name",
            "category_label",
            "payment_method_code",
            "payment_method_name",
            "payment_method_kind",
            "handled_by_name",
            "handled_by_code",
            "is_void",
            "created_at",
            "updated_at",
        ]


class CashAdjustmentSerializer(serializers.ModelSerializer):
    direction_label = serializers.CharField(
        source="get_direction_display", read_only=True
    )
    reason_label = serializers.CharField(
        source="get_reason_display", read_only=True
    )
    warehouse_code = serializers.CharField(
        source="warehouse.code", read_only=True
    )
    warehouse_name = serializers.CharField(
        source="warehouse.name", read_only=True
    )
    handled_by_name = serializers.CharField(
        source="handled_by.name", read_only=True, default=""
    )
    handled_by_code = serializers.CharField(
        source="handled_by.code", read_only=True, default=""
    )

    class Meta:
        model = CashAdjustment
        fields = [
            "id",
            "no",
            "warehouse",
            "warehouse_code",
            "warehouse_name",
            "doc_date",
            "direction",
            "direction_label",
            "reason",
            "reason_label",
            "amount",
            "handled_by",
            "handled_by_name",
            "handled_by_code",
            "note",
            "is_void",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "no",
            "warehouse_code",
            "warehouse_name",
            "direction_label",
            "reason_label",
            "handled_by_name",
            "handled_by_code",
            "is_void",
            "created_at",
            "updated_at",
        ]


class PhoneBillCollectionSerializer(serializers.ModelSerializer):
    warehouse_code = serializers.CharField(
        source="warehouse.code", read_only=True
    )
    warehouse_name = serializers.CharField(
        source="warehouse.name", read_only=True
    )
    warehouse_address = serializers.CharField(
        source="warehouse.address", read_only=True, default=""
    )
    warehouse_phone = serializers.CharField(
        source="warehouse.phone", read_only=True, default=""
    )
    carrier_code = serializers.CharField(source="carrier.code", read_only=True)
    carrier_name = serializers.CharField(source="carrier.name", read_only=True)
    handled_by_name = serializers.CharField(
        source="handled_by.name", read_only=True, default=""
    )
    handled_by_code = serializers.CharField(
        source="handled_by.code", read_only=True, default=""
    )
    member_name = serializers.CharField(
        source="member.name", read_only=True, default=""
    )
    member_code = serializers.CharField(
        source="member.code", read_only=True, default=""
    )

    class Meta:
        model = PhoneBillCollection
        fields = [
            "id",
            "no",
            "warehouse",
            "warehouse_code",
            "warehouse_name",
            "warehouse_address",
            "warehouse_phone",
            "doc_date",
            "carrier",
            "carrier_code",
            "carrier_name",
            "phone_no",
            "amount",
            "id_no",
            "handled_by",
            "handled_by_name",
            "handled_by_code",
            "member",
            "member_name",
            "member_code",
            "is_void",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "no",
            "warehouse_code",
            "warehouse_name",
            "warehouse_address",
            "warehouse_phone",
            "carrier_code",
            "carrier_name",
            "handled_by_name",
            "handled_by_code",
            "member_name",
            "member_code",
            "is_void",
            "created_at",
            "updated_at",
        ]
