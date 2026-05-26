from rest_framework import serializers

from .models import Carrier, Customer, Member, SalesPerson, SimCard, Supplier, TelecomPlan


class _TenantUniqueMixin:
    def _tenant_unique(self, queryset, field_name: str, value):
        request = self.context.get("request")
        if request is None:
            return value
        qs = queryset.for_tenant(request.tenant).filter(**{field_name: value})
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("已存在相同值")
        return value


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            "id",
            "code",
            "name",
            "contact",
            "phone",
            "tax_id",
            "address",
            "note",
            "sort_order",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "created_at", "updated_at"]


class CustomerSerializer(_TenantUniqueMixin, serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Customer
        fields = [
            "id",
            "code",
            "phone",
            "name",
            "kind",
            "kind_label",
            "tax_id",
            "address",
            "note",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "kind_label", "created_at", "updated_at"]


class MemberSerializer(_TenantUniqueMixin, serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = [
            "id",
            "code",
            "name",
            "phone",
            "national_id",
            "birthday",
            "address",
            "note",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "created_at", "updated_at"]


class SalesPersonSerializer(_TenantUniqueMixin, serializers.ModelSerializer):
    class Meta:
        model = SalesPerson
        fields = [
            "id",
            "code",
            "name",
            "phone",
            "note",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_code(self, value):
        return self._tenant_unique(SalesPerson.objects, "code", value)


class CarrierSerializer(_TenantUniqueMixin, serializers.ModelSerializer):
    class Meta:
        model = Carrier
        fields = ["id", "code", "name", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_code(self, value):
        return self._tenant_unique(Carrier.objects, "code", value)


class SimCardSerializer(_TenantUniqueMixin, serializers.ModelSerializer):
    vendor_code = serializers.CharField(source="vendor.code", read_only=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SimCard
        fields = [
            "id",
            "card_no",
            "vendor",
            "vendor_code",
            "vendor_name",
            "deposit",
            "deposit_refunded",
            "status",
            "status_label",
            "issued_at",
            "activated_at",
            "returned_at",
            "note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "vendor_code",
            "vendor_name",
            "status_label",
            "issued_at",
            "activated_at",
            "returned_at",
            "created_at",
            "updated_at",
        ]

    def validate_card_no(self, value):
        return self._tenant_unique(SimCard.objects, "card_no", value)


class TelecomPlanSerializer(_TenantUniqueMixin, serializers.ModelSerializer):
    carrier_code = serializers.CharField(source="carrier.code", read_only=True)
    carrier_name = serializers.CharField(source="carrier.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = TelecomPlan
        fields = [
            "id",
            "code",
            "name",
            "carrier",
            "carrier_code",
            "carrier_name",
            "monthly_fee",
            "contract_months",
            "kind",
            "kind_label",
            "commission",
            "note",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "code",
            "carrier_code",
            "carrier_name",
            "kind_label",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        return self._tenant_unique(TelecomPlan.objects, "name", value)
