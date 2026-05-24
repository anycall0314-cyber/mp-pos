from rest_framework import serializers

from .models import PettyExpense


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
            "is_void",
            "created_at",
            "updated_at",
        ]
