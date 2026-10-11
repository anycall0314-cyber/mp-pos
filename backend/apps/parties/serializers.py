from rest_framework import serializers

from apps.core.manager_fields import ManagerOnlyFieldsMixin
from apps.core.tenant_fields import TenantScopedRelatedFieldsMixin

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


class SupplierSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
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
            "is_repair_vendor",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "created_at", "updated_at"]


class CustomerSerializer(TenantScopedRelatedFieldsMixin, _TenantUniqueMixin, serializers.ModelSerializer):
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
            "is_sales_default",
            "tax_id",
            "address",
            "note",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "kind_label", "is_sales_default", "created_at", "updated_at"]


    def validate(self, attrs):
        if self.instance and self.instance.is_sales_default and attrs.get("is_active") is False:
            raise serializers.ValidationError({"is_active": "請先更換銷貨預設來源，再停用此來源"})
        return attrs


class MemberSerializer(TenantScopedRelatedFieldsMixin, _TenantUniqueMixin, serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    default_customer_detail = CustomerSerializer(source="default_customer", read_only=True)

    class Meta:
        model = Member
        fields = [
            "id",
            "code",
            "name",
            "kind",
            "kind_label",
            "tax_id",
            "contact",
            "default_source_mode",
            "default_customer",
            "default_customer_detail",
            "phone",
            "national_id",
            "birthday",
            "address",
            "note",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "kind_label", "default_customer_detail", "created_at", "updated_at"]


    def validate(self, attrs):
        mode = attrs.get("default_source_mode", getattr(self.instance, "default_source_mode", Member.SourceMode.SALES_DEFAULT))
        source = attrs.get("default_customer", getattr(self.instance, "default_customer", None))
        if mode == Member.SourceMode.CUSTOMER:
            if source is None or not source.is_active:
                raise serializers.ValidationError({"default_customer": "請選啟用中的來源客戶"})
        elif "default_customer" in attrs or "default_source_mode" in attrs:
            attrs["default_customer"] = None
        return attrs


class SalesPersonSerializer(TenantScopedRelatedFieldsMixin, _TenantUniqueMixin, serializers.ModelSerializer):
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


class CarrierSerializer(TenantScopedRelatedFieldsMixin, _TenantUniqueMixin, serializers.ModelSerializer):
    class Meta:
        model = Carrier
        fields = ["id", "code", "name", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_code(self, value):
        return self._tenant_unique(Carrier.objects, "code", value)


class SimCardSerializer(TenantScopedRelatedFieldsMixin, _TenantUniqueMixin, serializers.ModelSerializer):
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


class TelecomPlanSerializer(ManagerOnlyFieldsMixin, TenantScopedRelatedFieldsMixin, _TenantUniqueMixin, serializers.ModelSerializer):
    # 公司實際拿的佣金:只有管理員拿得到、填得到(店員的回應裡沒有這一欄)
    manager_only_fields = ("company_commission",)

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
            "company_commission",
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

    def validate_company_commission(self, value):
        # 空的 = 還沒設定(不是 0)
        if value is not None and value < 0:
            raise serializers.ValidationError("公司佣金不能是負的")
        return value
