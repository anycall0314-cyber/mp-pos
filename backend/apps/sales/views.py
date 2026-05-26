from django.db import transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.core.warehouse_scoping import WarehouseScopedMixin
from apps.inventory.models import Warehouse
from apps.inventory.serializers import ProductSerialSerializer
from apps.parties.models import Member

from .models import LegacyPurchase, SalesOrder, SalesReturn
from .serializers import (
    LegacyPurchaseSerializer,
    SalesOrderSerializer,
    SalesReturnSerializer,
)
from .services import (
    SalesOrderError,
    SalesReturnError,
    SecondhandIntakeError,
    acquire_secondhand_from_member,
    commit_sales_order,
    commit_sales_return,
    void_sales_order,
    void_sales_return,
)


class SecondhandAcquisitionInputSerializer(serializers.Serializer):
    member = serializers.PrimaryKeyRelatedField(queryset=Member.objects.all())
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all())
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    serial_no = serializers.CharField(max_length=80)
    condition_grade = serializers.CharField(max_length=2)
    custom_unit_price = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )
    battery_health = serializers.IntegerField(
        min_value=0, max_value=100, required=False, allow_null=True
    )
    condition_note = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    acquisition_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    payment_method_code = serializers.CharField(max_length=20)
    doc_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )


class SalesOrderViewSet(
    WarehouseScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """銷貨單:儲存即生效;不開放 update / delete,要取消請用 void action。"""

    serializer_class = SalesOrderSerializer
    search_fields = [
        "no",
        "customer__code",
        "customer__name",
        "customer__phone",
        "invoice_no",
        "note",
    ]
    ordering_fields = ["doc_date", "no", "created_at", "total"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "warehouse": ["exact"],
        "customer": ["exact"],
        "member": ["exact"],
        "sales_person": ["exact"],
        "sales_type": ["exact"],
        "tax_method": ["exact"],
        "is_void": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return (
            SalesOrder.objects.for_tenant(self.request.tenant)
            .select_related("customer", "member", "warehouse")
            .prefetch_related(
                "items__product",
                "items__sim_card",
                "items__serials__serial",
                "payments",
            )
        )

    def perform_create(self, serializer):
        user = (
            self.request.user
            if getattr(self.request, "user", None) and self.request.user.is_authenticated
            else None
        )
        with transaction.atomic():
            serializer.save(tenant=self.request.tenant, created_by=user)
            try:
                commit_sales_order(serializer.instance)
            except SalesOrderError as exc:
                raise serializers.ValidationError({"detail": str(exc)})

    @action(detail=False, methods=["get"], url_path="last-price")
    def last_price(self, request):
        """查某會員上次買某商品的成交價(用於銷貨建單時自動帶價)。

        同時翻新系統(`SalesOrderItem`)與舊系統匯入(`LegacyPurchase`),
        - 只看該會員、unit_price>0 的列(跳過贈品 / 搭機送)
        - 新系統需未作廢
        - 兩邊都有時,取 doc_date 較新者
        - 查無則 404
        """
        from .models import LegacyPurchase, SalesOrderItem

        member_id = request.query_params.get("member")
        product_id = request.query_params.get("product")
        if not member_id or not product_id:
            return Response(
                {"detail": "需提供 member 與 product"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        tenant = request.tenant
        item = (
            SalesOrderItem.objects.for_tenant(tenant)
            .filter(
                so__member_id=member_id,
                product_id=product_id,
                so__is_void=False,
                unit_price__gt=0,
            )
            .select_related("so")
            .order_by("-so__doc_date", "-so__id", "-id")
            .first()
        )
        legacy = (
            LegacyPurchase.objects.for_tenant(tenant)
            .filter(
                member_id=member_id,
                product_id=product_id,
                unit_price__gt=0,
            )
            .order_by("-doc_date", "-id")
            .first()
        )

        # 兩邊都有 → 取較新的
        candidates = []
        if item is not None:
            candidates.append(
                (
                    item.so.doc_date,
                    {
                        "unit_price": str(item.unit_price),
                        "doc_date": item.so.doc_date,
                        "sales_order_no": item.so.no,
                        "sales_order_id": item.so.id,
                        "source": "current",
                    },
                )
            )
        if legacy is not None:
            candidates.append(
                (
                    legacy.doc_date,
                    {
                        "unit_price": str(legacy.unit_price),
                        "doc_date": legacy.doc_date,
                        "sales_order_no": legacy.source_no or "(舊系統)",
                        "sales_order_id": None,
                        "source": "legacy",
                    },
                )
            )
        if not candidates:
            return Response({"detail": "未找到"}, status=status.HTTP_404_NOT_FOUND)
        candidates.sort(key=lambda x: x[0], reverse=True)
        return Response(candidates[0][1])

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        so = self.get_object()
        try:
            void_sales_order(so)
        except SalesOrderError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        so = self.get_queryset().get(pk=so.pk)
        return Response(self.get_serializer(so).data)

    @action(detail=False, methods=["post"], url_path="secondhand-acquisition")
    def secondhand_acquisition(self, request):
        """個人收購入庫:一個 transaction 內建立中古機序號 + 收購二手銷貨單。"""
        tenant = request.tenant
        in_ser = SecondhandAcquisitionInputSerializer(data=request.data)
        in_ser.is_valid(raise_exception=True)
        data = in_ser.validated_data

        member = data["member"]
        warehouse = data["warehouse"]
        product = data["product"]
        if member.tenant_id != tenant.id:
            return Response(
                {"detail": "會員不屬於此租戶"}, status=status.HTTP_400_BAD_REQUEST
            )
        if warehouse.tenant_id != tenant.id:
            return Response(
                {"detail": "倉庫不屬於此租戶"}, status=status.HTTP_400_BAD_REQUEST
            )
        if product.tenant_id != tenant.id:
            return Response(
                {"detail": "商品不屬於此租戶"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            serial, so = acquire_secondhand_from_member(
                tenant=tenant,
                member=member,
                warehouse=warehouse,
                secondhand_product=product,
                serial_no=data["serial_no"].strip(),
                condition_grade=data["condition_grade"],
                custom_unit_price=data.get("custom_unit_price"),
                acquisition_price=data["acquisition_price"],
                payment_method_code=data["payment_method_code"],
                battery_health=data.get("battery_health"),
                condition_note=data.get("condition_note", ""),
                doc_date=data.get("doc_date"),
                note=data.get("note", ""),
            )
        except SecondhandIntakeError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        so = self.get_queryset().get(pk=so.pk)
        return Response(
            {
                "serial": ProductSerialSerializer(serial).data,
                "sales_order": self.get_serializer(so).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LegacyPurchaseViewSet(viewsets.ModelViewSet):
    """舊系統匯入的會員消費紀錄。

    主要用途:
    - 銷貨建單時與新銷貨單一起參與「上次成交價」查詢(在 SalesOrderViewSet.last_price)
    - 會員管理頁顯示與當前消費合併的完整時間軸
    一般情況用 CSV 批次匯入(`manage.py import_legacy_purchases`),不走 UI 建立。
    """

    serializer_class = LegacyPurchaseSerializer
    search_fields = ["member__name", "member__phone", "product__sku", "product__name", "source_no", "serial_no"]
    ordering_fields = ["doc_date", "created_at"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "member": ["exact"],
        "product": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return (
            LegacyPurchase.objects.for_tenant(self.request.tenant)
            .select_related("member", "product")
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class SalesReturnViewSet(
    WarehouseScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """銷退單:儲存即生效;不開放 update / delete,取消請用 void action。"""

    serializer_class = SalesReturnSerializer
    search_fields = [
        "no",
        "original_so__no",
        "customer__name",
        "customer__phone",
        "note",
    ]
    ordering_fields = ["doc_date", "no", "created_at", "total"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "warehouse": ["exact"],
        "customer": ["exact"],
        "member": ["exact"],
        "original_so": ["exact"],
        "is_void": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return (
            SalesReturn.objects.for_tenant(self.request.tenant)
            .select_related("original_so", "customer", "member", "warehouse")
            .prefetch_related(
                "items__product",
                "items__original_item",
                "items__serials__serial",
            )
        )

    def perform_create(self, serializer):
        user = (
            self.request.user
            if getattr(self.request, "user", None) and self.request.user.is_authenticated
            else None
        )
        with transaction.atomic():
            serializer.save(tenant=self.request.tenant, created_by=user)
            try:
                commit_sales_return(serializer.instance)
            except SalesReturnError as exc:
                raise serializers.ValidationError({"detail": str(exc)})

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        sr = self.get_object()
        try:
            void_sales_return(sr)
        except SalesReturnError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        sr = self.get_queryset().get(pk=sr.pk)
        return Response(self.get_serializer(sr).data)

    @action(detail=False, methods=["get"], url_path="returnable")
    def returnable(self, request):
        """查指定 SalesOrder 的「可退明細」:每行剩可退數量 + 可退序號清單。

        Query params: `?sales_order=<id>`
        """
        from .models import SalesReturnItem, SalesReturnItemSerial

        so_id = request.query_params.get("sales_order")
        if not so_id:
            return Response(
                {"detail": "需提供 sales_order"}, status=status.HTTP_400_BAD_REQUEST
            )
        so = (
            SalesOrder.objects.for_tenant(request.tenant)
            .filter(pk=so_id, is_void=False)
            .first()
        )
        if so is None:
            return Response(
                {"detail": "查無或已作廢的銷貨單"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 已退累計(by original_item_id)
        prior_returned = {}
        for oid, qty in SalesReturnItem.objects.filter(
            original_item__so=so,
            sr__is_void=False,
        ).values_list("original_item_id", "qty"):
            prior_returned[oid] = prior_returned.get(oid, 0) + qty

        # 已退過的序號集合
        prior_serial_ids = set(
            SalesReturnItemSerial.objects.filter(
                item__original_item__so=so,
                item__sr__is_void=False,
            ).values_list("serial_id", flat=True)
        )

        items_payload = []
        for it in so.items.select_related("product").prefetch_related(
            "serials__serial"
        ):
            already = prior_returned.get(it.id, 0)
            remaining = max(0, it.qty - already)
            available_serials = [
                {
                    "id": s.serial.id,
                    "serial_no": s.serial.serial_no,
                }
                for s in it.serials.select_related("serial").all()
                if s.serial.id not in prior_serial_ids
            ]
            items_payload.append({
                "id": it.id,
                "line_no": it.line_no,
                "product": it.product_id,
                "product_sku": it.product.sku,
                "product_name": it.product.name,
                "product_requires_serial": it.product.requires_serial,
                "product_is_virtual": it.product.is_virtual,
                "qty": it.qty,
                "already_returned": already,
                "remaining": remaining,
                "unit_price": str(it.unit_price),
                "available_serials": available_serials,
            })

        # 原單付款方式(供退款方式 dropdown 用)
        original_methods = list(
            so.payments.values_list("method", flat=True).distinct()
        )

        return Response({
            "sales_order_id": so.id,
            "sales_order_no": so.no,
            "doc_date": so.doc_date,
            "tax_method": so.tax_method,
            "invoice_voided": so.invoice_voided,
            "customer": so.customer_id,
            "customer_name": so.customer.name if so.customer else "",
            "member": so.member_id,
            "member_name": so.member.name if so.member else "",
            "warehouse": so.warehouse_id,
            "warehouse_name": so.warehouse.name,
            "payment_methods": original_methods,
            "items": items_payload,
        })
