from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers

from apps.catalog.models import Product
from apps.parties.serializers import MemberSerializer
from apps.core.manager_fields import ManagerOnlyFieldsMixin
from apps.core.tenant_fields import TenantScopedRelatedFieldsMixin

from .models import (
    RepairItem,
    RepairItemModel,
    RepairItemPart,
    RepairOrder,
    RepairOrderPart,
)


def _own_parts(tenant, ids):
    """parts_input 是原始編號(不是關聯欄位):這裡確認每一個零件都是這家公司的商品。"""
    found = {p.pk: p for p in Product.objects.filter(tenant=tenant, pk__in=list(ids))}
    if set(ids) - set(found):
        raise serializers.ValidationError({"parts_input": "零件不屬於這家公司"})
    return found


class RepairItemPartSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    part_name = serializers.CharField(source="part_product.name", read_only=True)
    part_sku = serializers.CharField(source="part_product.sku", read_only=True)

    class Meta:
        model = RepairItemPart
        fields = ["id", "part_product", "part_name", "part_sku", "default_qty"]


class RepairItemSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
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
        _own_parts(tenant, wanted)
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


class RepairOrderPartSerializer(ManagerOnlyFieldsMixin, TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    # 單位成本是實際成本:只有管理員拿得到;大家都有一件的業務員成本(沒有記的舊零件 = 單位成本)
    # (owner 2026-10-28;規則在 core/cost_access.py)
    manager_only_fields = ("unit_cost",)

    part_name = serializers.CharField(source="part_product.name", read_only=True)
    part_sku = serializers.CharField(source="part_product.sku", read_only=True)
    staff_unit_cost = serializers.SerializerMethodField()

    def get_staff_unit_cost(self, obj) -> str:
        from .services import part_unit_cost
        return str(part_unit_cost(obj, staff=True))

    class Meta:
        model = RepairOrderPart
        fields = [
            "id",
            "part_product",
            "part_name",
            "part_sku",
            "qty",
            "unit_cost",
            "staff_unit_cost",
        ]
        read_only_fields = ["id", "part_name", "part_sku", "unit_cost"]


class RepairOrderSerializer(ManagerOnlyFieldsMixin, TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    # 建議報價是存下來的「零件實際成本 + 工資」,扣掉工資就是實際成本:只有管理員拿得到
    # (畫面上的建議報價是用零件的業務員成本即時算的;owner 2026-10-28)
    # 加進自家庫存那一台的成本(零件實際成本 + 委外費用)也一樣
    manager_only_fields = ("suggested_quote", "stock_cost_added")

    member_detail = MemberSerializer(source="member", read_only=True)
    parts = RepairOrderPartSerializer(many=True, read_only=True)
    parts_input = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        write_only=True,
    )
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    member_name = serializers.CharField(source="member.name", read_only=True, default="")
    member_phone = serializers.CharField(source="member.phone", read_only=True, default="")
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
    technician_name = serializers.CharField(source="technician.name", read_only=True, default="")
    margin_breakdown = serializers.SerializerMethodField()
    # 自家庫存送去整理的那一台(repairs/stock.py);客人的單是 null
    stock_serial_detail = serializers.SerializerMethodField()
    # 這張單公司賺多少(維修毛利只有 services.money_of 那一份算法;清單、開單頁、月報都是這個數字)。
    # 不是管理員:零件照業務員成本算 = 業務員毛利(owner 2026-10-28)
    margin = serializers.SerializerMethodField()

    def _staff(self) -> bool:
        return not self._for_a_manager()

    def get_stock_serial_detail(self, obj):
        s = obj.stock_serial
        if s is None:
            return None
        return {
            "id": s.id, "serial_no": s.serial_no, "product_name": s.product.name,
            "warehouse_name": s.warehouse.name if s.warehouse_id else "",
            "status": s.status, "status_label": s.get_status_display(),
        }

    def get_margin(self, obj) -> str:
        from .services import compute_margin
        return str(compute_margin(obj, staff=self._staff()))

    def get_margin_breakdown(self, obj):
        from .services import compute_personal_margin
        b = compute_personal_margin(obj, staff=self._staff())
        return {
            "kind": b["kind"],
            "sales_person_id": b["sales_person_id"],
            "sales_person_amount": str(b["sales_person_amount"]),
            "technician_id": b["technician_id"],
            "technician_amount": str(b["technician_amount"]),
        }
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
            "member",
            "member_detail",
            "member_name",
            "member_phone",
            "customer_name",
            "customer_phone",
            "host_model_key",
            "host_model_name",
            "device_serial",
            "serial_unavailable",
            "intake_estimate",
            "accessories",
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
            "technician",
            "technician_name",
            "internal_settle_amount",
            "margin_breakdown",
            "margin",
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
            "payment_method",
            "completed_at",
            "is_void",
            "stock_serial",
            "stock_serial_detail",
            "stock_cost_added",
            "parts",
            "parts_input",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "stock_serial_detail",
            "stock_cost_added",
            "status",
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
            "technician_name",
            "margin_breakdown",
            "margin",
            "mode_label",
            "status_label",
            "previous_repair_no",
            "previous_repair_completed_at",
            "warranty_info",
            "created_at",
            "updated_at",
        ]

    def get_customer_name(self, obj):
        party = obj.member or obj.customer
        return party.name if party else ""

    def get_customer_phone(self, obj):
        party = obj.member or obj.customer
        return party.phone if party else ""

    def validate(self, attrs):
        member = attrs.get("member", getattr(self.instance, "member", None))
        customer = attrs.get("customer", getattr(self.instance, "customer", None))
        existing_member_id = getattr(self.instance, "member_id", None)
        if member is not None and not member.is_active and member.pk != existing_member_id:
            raise serializers.ValidationError({"member": "會員已停用"})
        # 自家庫存的整理單(repairs/stock.py):建單之後不能換台;沒有會員、不收錢
        if self.instance is not None and "stock_serial" in attrs \
                and attrs["stock_serial"] != self.instance.stock_serial:
            raise serializers.ValidationError({"stock_serial": "建單之後不能換整理的機器"})
        unit = attrs.get("stock_serial", getattr(self.instance, "stock_serial", None))
        if unit is not None:
            if member is not None or customer is not None:
                raise serializers.ValidationError({"stock_serial": "自家庫存的維修單不選會員"})
            paid = attrs.get("customer_paid_amount", getattr(self.instance, "customer_paid_amount", 0))
            method = attrs.get("payment_method", getattr(self.instance, "payment_method", None))
            if paid or method is not None:
                raise serializers.ValidationError({"customer_paid_amount": "自家庫存的維修單不收錢"})
        elif member is None and customer is None:
            raise serializers.ValidationError({"member": "請選送修會員"})
        # 序號 / IMEI 必填(開不了機勾「取不到」)擋在收件畫面(RepairEntryPage),伺服器不擋:
        # 其他建維修單的地方與既有的單照舊
        estimate = attrs.get("intake_estimate")
        if estimate is not None and estimate < 0:
            raise serializers.ValidationError({"intake_estimate": "預估費用不能是負的"})
        if estimate is not None:
            attrs["intake_estimate"] = estimate.quantize(Decimal("1"), rounding=ROUND_HALF_UP)   # 全站金額整數
        return attrs

    def create(self, validated_data):
        from django.db import transaction

        if validated_data.get("member") is not None:
            from apps.parties.sources import transaction_source
            validated_data["customer"] = transaction_source(validated_data, validated_data["tenant"])
        parts_input = validated_data.pop("parts_input", None)
        unit = validated_data.get("stock_serial")
        if unit is not None:
            # 收件單上看的機型與序號照那一台帶
            validated_data["device_serial"] = unit.serial_no
            validated_data["serial_unavailable"] = False
            if not validated_data.get("host_model_name"):
                validated_data["host_model_name"] = unit.product.name[:128]
            if not validated_data.get("host_model_key"):
                validated_data["host_model_key"] = unit.product.phone_model_key[:128]
        with transaction.atomic():
            instance = super().create(validated_data)
            if parts_input is not None:
                self._sync_parts(instance, parts_input)
            if unit is not None:
                self._start_refurb(instance, unit)
        return instance

    def _start_refurb(self, order, unit):
        """那一台 在庫 → 整理中(鎖住那一台之後才看;鎖在門市的帳號只能刷自己門市的)。"""
        from apps.core.warehouse_scoping import locked_warehouse_id

        from . import stock

        request = self.context.get("request")
        own = locked_warehouse_id(request.user) if request is not None else None
        try:
            stock.start(order, unit.pk, own_warehouse_id=own)
        except stock.StockRepairError as exc:
            raise serializers.ValidationError({"stock_serial": str(exc)})
        unit.refresh_from_db(fields=["status", "warehouse"])        # 回應裡看到的是改過之後的

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
        own = _own_parts(tenant, wanted)
        existing = {p.part_product_id: p for p in order.parts.all()}
        for pid, row in existing.items():
            if pid not in wanted:
                row.delete()
            elif row.qty != wanted[pid]["qty"]:
                row.qty = wanted[pid]["qty"]
                row.save(update_fields=["qty"])
        for pid, data in wanted.items():
            if pid not in existing:
                # snapshot 當下成本與業務員成本(完工時還沒記到的會再 refresh 一次)
                from .services import snapshot_part_cost
                part = own[pid]
                line = RepairOrderPart(tenant=tenant, repair_order=order, part_product=part, qty=data["qty"])
                snapshot_part_cost(line, part, tenant)
                line.save()
