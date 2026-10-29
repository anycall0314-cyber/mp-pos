from django.db import transaction
from django.db.models import Q
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core import cost_access
from apps.core.warehouse_scoping import WarehouseScopedMixin
from apps.tenants import abilities

from .models import RepairItem, RepairOrder
from .serializers import RepairItemSerializer, RepairOrderSerializer
from .services import (
    complete_repair_order,
    compute_in_house_quote,
    compute_margin,
    ensure_editable,
    parts_with_insufficient_stock,
    reopen_repair_order,
    set_repair_status,
    void_repair_order,
)


class RepairItemViewSet(viewsets.ModelViewSet):
    """維修項目模板 CRUD。"""

    serializer_class = RepairItemSerializer
    search_fields = ["name"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return (
            RepairItem.objects.for_tenant(self.request.tenant)
            .prefetch_related("parts__part_product", "model_bindings")
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=["get"], url_path="by-model")
    def by_model(self, request):
        """依機型 key 列出可用維修項目(維修單建單頁用)。"""
        key = request.query_params.get("model_key", "").strip().lower()
        if not key:
            return Response([])
        qs = (
            RepairItem.objects.for_tenant(request.tenant)
            .filter(is_active=True, model_bindings__host_model_key=key)
            .prefetch_related("parts__part_product")
            .distinct()
        )
        return Response(RepairItemSerializer(qs, many=True).data)


class RepairOrderViewSet(WarehouseScopedMixin, viewsets.ModelViewSet):
    """維修單 CRUD + 狀態切換 action。"""

    serializer_class = RepairOrderSerializer
    search_fields = ["no", "member__name", "member__phone", "customer__name", "customer__phone", "device_serial"]
    filterset_fields = {
        "mode": ["exact"],
        "status": ["exact"],
        "warehouse": ["exact"],
        "is_void": ["exact"],
        "received_date": ["exact", "gte", "lte"],
    }
    ordering_fields = ["received_date", "completed_at", "created_at"]
    ordering = ["-received_date", "-id"]

    def get_queryset(self):
        qs = (
            RepairOrder.objects.for_tenant(self.request.tenant)
            .select_related(
                "customer", "member", "member__default_customer",
                "warehouse",
                "sales_person",
                "repair_item",
                "external_vendor",
                "stock_serial__product", "stock_serial__warehouse",
            )
            .prefetch_related("parts__part_product")
        )
        # ?open=1:還沒完成、沒作廢的(維修單清單預設看這些;全站檢視 E4)
        if self.request.query_params.get("open") == "1":
            qs = qs.filter(is_void=False).exclude(status=RepairOrder.Status.COMPLETED)
        return qs

    def perform_create(self, serializer):
        self.check_create_warehouse(serializer)
        serializer.save(tenant=self.request.tenant)

    def perform_update(self, serializer):
        # 鎖住並重讀之後才改:已完工 / 已作廢的不能改(同時有人按完工也不會被這次修改蓋掉)
        with transaction.atomic():
            try:
                ensure_editable(serializer.instance)
            except ValueError as exc:
                raise serializers.ValidationError({"detail": str(exc)})
            super().perform_update(serializer)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "維修單不能刪除,請用作廢"}, status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        """切換狀態(pending/quoting/in_repair/sent_external/ready_pickup)。
        狀態 completed 走 /complete/ action。"""
        order = self.get_object()
        new_status = request.data.get("status")
        valid = {s for s, _ in RepairOrder.Status.choices if s != "completed"}
        if new_status not in valid:
            return Response(
                {"detail": f"狀態 {new_status} 不在允許範圍"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            set_repair_status(order, new_status)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        """轉「完成」狀態:扣零件倉庫存 + 寫異動。"""
        order = self.get_object()
        try:
            complete_repair_order(order)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"], url_path="reopen")
    def reopen(self, request, pk=None):
        """重開已完成的維修單:歸還零件庫存 + 退回待取件狀態。

        限 tenant_admin / platform_admin。一般店員若需修改已完成單據,
        須由店長執行此操作。
        """
        profile = getattr(request.user, "profile", None)
        role = profile.role if profile else None
        if role not in ("platform_admin", "tenant_admin"):
            return Response(
                {"detail": "重開維修單需店長或管理員權限"},
                status=status.HTTP_403_FORBIDDEN,
            )
        order = self.get_object()
        if order.status != RepairOrder.Status.COMPLETED:
            return Response(
                {"detail": "此單尚未完成,不需重開"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            reopen_repair_order(order)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["get"], url_path="quote-preview")
    def quote_preview(self, request, pk=None):
        """自修建議報價預覽(零件成本 + 工資)+ 缺料檢查。"""
        order = self.get_object()
        # 不是管理員:零件照業務員成本算(owner 2026-10-28;規則在 core/cost_access.py)
        staff = not cost_access.sees_actual_cost(request.user)
        suggested = compute_in_house_quote(order, staff=staff)
        shortages = parts_with_insufficient_stock(order)
        return Response(
            {
                "suggested_quote": str(suggested),
                "shortages": shortages,
                "margin": str(compute_margin(order, staff=staff)),
            }
        )

    @action(detail=True, methods=["post"], url_path="void")
    def void(self, request, pk=None):
        abilities.require(request.user, abilities.VOID_OTHERS)
        order = self.get_object()
        try:
            void_repair_order(order)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(order).data)

    @action(detail=False, methods=["get"], url_path="stock-lookup")
    def stock_lookup(self, request):
        """自家庫存送去整理:刷到的碼是哪一台、能不能送(?code=…;規則在 repairs/stock.py,建單時鎖住之後會再看一次)。"""
        from apps.core.warehouse_scoping import locked_warehouse_id
        from apps.inventory.identifiers import find_serial_ids
        from apps.inventory.models import ProductSerial

        code = request.query_params.get("code") or ""
        if not code.strip() or len(code) > 80:
            return Response({"detail": "請刷序號"}, status=status.HTTP_400_BAD_REQUEST)
        ids = find_serial_ids(request.tenant, code)
        if len(ids) > 1:
            return Response({"detail": "這個碼對到不只一台,請改刷那一台的另一個碼"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not ids:
            return Response({"detail": "系統沒有這個序號"}, status=status.HTTP_400_BAD_REQUEST)
        s = ProductSerial.objects.select_related("product", "warehouse").get(pk=ids[0])
        own = locked_warehouse_id(request.user)
        reason = ""
        if s.status != ProductSerial.Status.IN_STOCK or s.warehouse_id is None:
            reason = f"這一台{s.get_status_display()},不能送去整理"
        elif own is not None and s.warehouse_id != own:
            reason = "這一台不在你的門市"
        return Response({
            "id": s.id, "serial_no": s.serial_no, "product_name": s.product.name,
            # 機型照那一台的商品帶(維修項目照機型列;owner 2026-10-29「沒辦法先選擇機型」)
            "model_key": s.product.phone_model_key, "model_name": s.product.phone_model_name,
            "warehouse": s.warehouse_id, "warehouse_name": s.warehouse.name if s.warehouse_id else "",
            "status": s.status, "status_label": s.get_status_display(),
            "ok": not reason, "reason": reason,
        })

    @action(detail=False, methods=["get"], url_path="history-by-phone")
    def history_by_phone(self, request):
        """依電話號碼查詢歷史維修紀錄(返修勾選用)。"""
        phone = (request.query_params.get("phone") or "").strip()
        if not phone:
            return Response([])
        qs = (
            self.get_queryset()
            .filter(is_void=False)
            .filter(Q(member__phone=phone) | Q(member__isnull=True, customer__phone=phone))
            .order_by("-received_date", "-id")[:30]
        )
        warranty_days = request.tenant.repair_warranty_days
        from django.utils import timezone
        today = timezone.now().date()
        items = []
        for o in qs:
            completed = o.completed_at.date() if o.completed_at else None
            days_since = (today - completed).days if completed else None
            within = (
                completed is not None and days_since is not None
                and days_since <= warranty_days
            )
            items.append(
                {
                    "id": o.id,
                    "no": o.no,
                    "mode": o.mode,
                    "mode_label": o.get_mode_display(),
                    "status": o.status,
                    "status_label": o.get_status_display(),
                    "received_date": o.received_date.isoformat(),
                    "completed_at": (
                        o.completed_at.isoformat() if o.completed_at else None
                    ),
                    "completed_date": completed.isoformat() if completed else None,
                    "host_model_name": o.host_model_name,
                    "device_serial": o.device_serial,
                    "repair_item_name": (
                        o.repair_item.name if o.repair_item_id else ""
                    ),
                    "warranty_within": within,
                    "days_since_complete": days_since,
                    "warranty_days": warranty_days,
                }
            )
        return Response(items)
