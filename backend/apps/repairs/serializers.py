from rest_framework import serializers

from apps.catalog.models import Product

from .models import (
    RepairItem,
    RepairItemModel,
    RepairItemPart,
    RepairOrder,
    RepairOrderPart,
)


class RepairItemPartSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source="part_product.name", read_only=True)
    part_sku = serializers.CharField(source="part_product.sku", read_only=True)

    class Meta:
        model = RepairItemPart
        fields = ["id", "part_product", "part_name", "part_sku", "default_qty"]


class RepairItemSerializer(serializers.ModelSerializer):
    parts = RepairItemPartSerializer(many=True, read_only=True)
    model_keys = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        write_only=True,
    )
    bound_model_keys = serializers.SerializerMethodField()
    # 寫入時送一份完整的零件清單(替換 model)
    parts_input = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        write_only=True,
    )

    class Meta:
        model = RepairItem
        fields = [
            "id",
            "name",
            "default_labor_fee",
            "is_active",
            "parts",
            "model_keys",
            "bound_model_keys",
            "parts_input",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "parts", "bound_model_keys", "created_at", "updated_at"]

    def get_bound_model_keys(self, obj):
        return list(
            obj.model_bindings.values_list("host_model_key", flat=True)
        )

    def create(self, validated_data):
        model_keys = validated_data.pop("model_keys", None)
        parts_input = validated_data.pop("parts_input", None)
        instance = super().create(validated_data)
        if model_keys is not None:
            self._sync_models(instance, model_keys)
        if parts_input is not None:
            self._sync_parts(instance, parts_input)
        return instance

    def update(self, instance, validated_data):
        model_keys = validated_data.pop("model_keys", None)
        parts_input = validated_data.pop("parts_input", None)
        instance = super().update(instance, validated_data)
        if model_keys is not None:
            self._sync_models(instance, model_keys)
        if parts_input is not None:
            self._sync_parts(instance, parts_input)
        return instance

    def _sync_models(self, item, keys):
        tenant = item.tenant
        target = {k.strip().lower() for k in keys if k and k.strip()}
        existing = {b.host_model_key: b for b in item.model_bindings.all()}
        for k, b in existing.items():
            if k not in target:
                b.delete()
        for k in target:
            if k not in existing:
                RepairItemModel.objects.create(
                    tenant=tenant, repair_item=item, host_model_key=k
                )

    def _sync_parts(self, item, parts_input):
        tenant = item.tenant
        # parts_input: [{"part_product": id, "default_qty": n}, ...]
        wanted = {
            int(r["part_product"]): int(r.get("default_qty") or 1)
            for r in parts_input
            if r.get("part_product")
        }
        existing = {p.part_product_id: p for p in item.parts.all()}
        for pid, row in existing.items():
            if pid not in wanted:
                row.delete()
            elif row.default_qty != wanted[pid]:
                row.default_qty = wanted[pid]
                row.save(update_fields=["default_qty"])
        for pid, qty in wanted.items():
            if pid not in existing:
                RepairItemPart.objects.create(
                    tenant=tenant,
                    repair_item=item,
                    part_product_id=pid,
                    default_qty=qty,
                )


class RepairOrderPartSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source="part_product.name", read_only=True)
    part_sku = serializers.CharField(source="part_product.sku", read_only=True)

    class Meta:
        model = RepairOrderPart
        fields = [
            "id",
            "part_product",
            "part_name",
            "part_sku",
            "qty",
            "unit_cost",
        ]
        read_only_fields = ["id", "part_name", "part_sku", "unit_cost"]


class RepairOrderSerializer(serializers.ModelSerializer):
    parts = RepairOrderPartSerializer(many=True, read_only=True)
    parts_input = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        write_only=True,
    )
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    warehouse_address = serializers.CharField(
        source="warehouse.address", read_only=True, default=""
    )
    warehouse_phone = serializers.CharField(
        source="warehouse.phone", read_only=True, default=""
    )
    repair_item_name = serializers.CharField(source="repair_item.name", read_only=True, default="")
    external_vendor_name = serializers.CharField(source="external_vendor.name", read_only=True, default="")
    sales_person_name = serializers.CharField(source="sales_person.name", read_only=True, default="")
    mode_label = serializers.CharField(source="get_mode_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    previous_repair_no = serializers.CharField(
        source="previous_repair_order.no", read_only=True, default=""
    )
    previous_repair_completed_at = serializers.DateTimeField(
        source="previous_repair_order.completed_at", read_only=True, default=None
    )
    warranty_info = serializers.SerializerMethodField()

    def get_warranty_info(self, obj):
        """根據 previous_repair_order + 租戶保固天數,即時推算保固狀態。"""
        if not obj.is_return_visit or not obj.previous_repair_order_id:
            return None
        prev = obj.previous_repair_order
        completed = prev.completed_at
        if not completed:
            return {"status": "unknown", "warranty_days": obj.tenant.repair_warranty_days}
        from django.utils import timezone
        days_since = (timezone.now().date() - completed.date()).days
        warranty_days = obj.tenant.repair_warranty_days
        within = days_since <= warranty_days
        return {
            "status": "within" if within else "expired",
            "warranty_days": warranty_days,
            "days_since_complete": days_since,
            "previous_completed_date": completed.date().isoformat(),
        }

    class Meta:
        model = RepairOrder
        fields = [
            "id",
            "no",
            "mode",
            "mode_label",
            "status",
            "status_label",
            "customer",
            "customer_name",
            "customer_phone",
            "host_model_key",
            "host_model_name",
            "device_serial",
            "defect_description",
            "unlock_method",
            "unlock_password",
            "unlock_pattern",
            "is_return_visit",
            "previous_repair_order",
            "previous_repair_no",
            "previous_repair_completed_at",
            "warranty_info",
            "internal_note",
            "received_date",
            "expected_complete_date",
            "warehouse",
            "warehouse_code",
            "warehouse_name",
            "warehouse_address",
            "warehouse_phone",
            "sales_person",
            "sales_person_name",
            "repair_item",
            "repair_item_name",
            "labor_fee",
            "suggested_quote",
            "final_quote",
            "external_vendor",
            "external_vendor_name",
            "external_quote_estimated",
            "external_quote_actual",
            "sent_external_at",
            "external_expected_pickup",
            "customer_paid_amount",
            "completed_at",
            "is_void",
            "parts",
            "parts_input",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "no",
            "completed_at",
            "is_void",
            "parts",
            "customer_name",
            "customer_phone",
            "warehouse_code",
            "warehouse_name",
            "warehouse_address",
            "warehouse_phone",
            "repair_item_name",
            "external_vendor_name",
            "sales_person_name",
            "mode_label",
            "status_label",
            "previous_repair_no",
            "previous_repair_completed_at",
            "warranty_info",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        parts_input = validated_data.pop("parts_input", None)
        instance = super().create(validated_data)
        if parts_input is not None:
            self._sync_parts(instance, parts_input)
        return instance

    def update(self, instance, validated_data):
        parts_input = validated_data.pop("parts_input", None)
        instance = super().update(instance, validated_data)
        if parts_input is not None:
            self._sync_parts(instance, parts_input)
        return instance

    def _sync_parts(self, order, parts_input):
        tenant = order.tenant
        wanted: dict[int, dict] = {}
        for r in parts_input:
            pid = r.get("part_product")
            if not pid:
                continue
            pid = int(pid)
            wanted[pid] = {
                "qty": int(r.get("qty") or 1),
            }
        existing = {p.part_product_id: p for p in order.parts.all()}
        for pid, row in existing.items():
            if pid not in wanted:
                row.delete()
            elif row.qty != wanted[pid]["qty"]:
                row.qty = wanted[pid]["qty"]
                row.save(update_fields=["qty"])
        for pid, data in wanted.items():
            if pid not in existing:
                # snapshot 當下成本(完工時會再 refresh 一次)
                from decimal import Decimal
                part = Product.objects.for_tenant(tenant).get(pk=pid)
                RepairOrderPart.objects.create(
                    tenant=tenant,
                    repair_order=order,
                    part_product=part,
                    qty=data["qty"],
                    unit_cost=part.weighted_avg_cost or Decimal("0"),
                )
