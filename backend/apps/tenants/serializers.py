from rest_framework import serializers

from .models import InvoiceTrack, InvoiceType, PaymentMethod


class InvoiceTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceType
        fields = ["id", "code", "name", "sort_order", "is_active", "is_default"]
        read_only_fields = ["id", "code"]


class InvoiceTrackSerializer(serializers.ModelSerializer):
    invoice_type_code = serializers.CharField(
        source="invoice_type.code", read_only=True
    )
    invoice_type_name = serializers.CharField(
        source="invoice_type.name", read_only=True
    )
    is_depleted = serializers.BooleanField(read_only=True)
    next_invoice_no = serializers.SerializerMethodField()
    next_number = serializers.IntegerField(required=False, min_value=0)

    def get_next_invoice_no(self, obj):
        if obj.is_depleted:
            return None
        return obj.format_number(obj.next_number)

    class Meta:
        model = InvoiceTrack
        fields = [
            "id",
            "invoice_type",
            "invoice_type_code",
            "invoice_type_name",
            "period_label",
            "prefix",
            "range_start",
            "range_end",
            "next_number",
            "is_active",
            "is_depleted",
            "next_invoice_no",
            "note",
        ]
        read_only_fields = [
            "id",
            "invoice_type_code",
            "invoice_type_name",
            "is_depleted",
            "next_invoice_no",
        ]

    def validate(self, data):
        start = data.get("range_start") or getattr(self.instance, "range_start", 0)
        end = data.get("range_end") or getattr(self.instance, "range_end", 0)
        if end < start:
            raise serializers.ValidationError({"range_end": "迄號不可小於起號"})
        nxt = data.get("next_number")
        if nxt is not None:
            if nxt < start or nxt > end + 1:
                raise serializers.ValidationError(
                    {"next_number": f"下一張號碼必須介於 {start} ~ {end + 1}"}
                )
        return data

    def create(self, validated_data):
        # 預設 next_number = range_start
        if not validated_data.get("next_number"):
            validated_data["next_number"] = validated_data["range_start"]
        return super().create(validated_data)


class PaymentMethodSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    # 未指定 code → 自動產生(pm_xxxxxx);使用者只認 name
    code = serializers.CharField(max_length=20, required=False, allow_blank=True)

    class Meta:
        model = PaymentMethod
        fields = [
            "id",
            "code",
            "name",
            "kind",
            "kind_label",
            "sort_order",
            "is_active",
            "is_default",
            "note",
        ]
        read_only_fields = ["id", "kind_label"]

    def create(self, validated_data):
        if not validated_data.get("code"):
            import secrets

            tenant = validated_data["tenant"]
            for _ in range(8):
                candidate = f"pm_{secrets.token_hex(3)}"
                if not PaymentMethod.objects.for_tenant(tenant).filter(
                    code=candidate
                ).exists():
                    validated_data["code"] = candidate
                    break
            else:
                raise serializers.ValidationError(
                    {"code": "自動產生代碼衝突,請重試"}
                )
        return super().create(validated_data)
