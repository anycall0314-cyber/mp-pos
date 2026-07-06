from rest_framework import serializers

from .models import DemandAlert


class DemandAlertSerializer(serializers.ModelSerializer):
    direction_label = serializers.CharField(source="get_direction_display", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = DemandAlert
        fields = [
            "id", "kind", "subject_key", "product", "product_sku", "product_name",
            "direction", "direction_label", "heat_growth", "internal_growth",
            "authorized", "score", "window_end", "note", "status",
            "created_at",
        ]
        read_only_fields = fields
