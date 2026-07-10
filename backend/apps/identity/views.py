from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from django.db.models import Q

from apps.inventory.models import Warehouse
from apps.parties.models import Supplier

from . import services


def _allowed_wh_ids(request):
    """鎖倉帳號可操作的倉 id;None = 不限(tenant_admin / platform_admin)。"""
    user = getattr(request, "user", None)
    profile = getattr(user, "profile", None) if user and user.is_authenticated else None
    if not profile or not profile.is_warehouse_locked:
        return None
    return [profile.default_warehouse_id] if profile.default_warehouse_id else []
from .models import IntakeBatch, IntakeItem, ProductAlias
from .serializers import (
    CorrectIntakeItemSerializer,
    IntakeBatchSerializer,
    IntakeCreateSerializer,
    IntakeItemSerializer,
    MatchItemSerializer,
    NewProductForItemSerializer,
    ProductAliasSerializer,
    SetHeaderSerializer,
)


class ProductAliasViewSet(viewsets.ModelViewSet):
    """商品別名 CRUD(別名管理頁用)。"""
    serializer_class = ProductAliasSerializer
    search_fields = ["value", "normalized_value"]
    filterset_fields = ["product", "supplier", "kind", "verified", "is_active"]
    ordering = ["product", "kind", "value"]

    def get_queryset(self):
        return ProductAlias.objects.for_tenant(self.request.tenant).select_related(
            "product", "supplier"
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class IntakeBatchViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """進貨待確認批次。

    POST /api/v1/identity/intakes/            貼一段文字 → 建批次 + 逐行識別
    GET  /api/v1/identity/intakes/            批次清單
    POST /api/v1/identity/intakes/{id}/commit/  全部對應完 → 過帳成進貨單
    """
    serializer_class = IntakeBatchSerializer
    filterset_fields = ["status", "source", "supplier"]
    ordering = ["-id"]

    def get_queryset(self):
        qs = (
            IntakeBatch.objects.for_tenant(self.request.tenant)
            .select_related("supplier", "warehouse")
            .prefetch_related("items__matched_product", "documents")
        )
        # 鎖倉帳號只看自己倉的批次(尚未指定倉的草稿也看得到)
        ids = _allowed_wh_ids(self.request)
        if ids is not None:
            qs = qs.filter(Q(warehouse_id__in=ids) | Q(warehouse__isnull=True))
        return qs

    def _lookup_supplier_warehouse(self, data):
        supplier = warehouse = None
        if data.get("supplier"):
            supplier = Supplier.objects.for_tenant(self.request.tenant).filter(
                id=data["supplier"]).first()
        if data.get("warehouse"):
            warehouse = Warehouse.objects.for_tenant(self.request.tenant).filter(
                id=data["warehouse"]).first()
        return supplier, warehouse

    def _user(self):
        u = getattr(self.request, "user", None)
        return u if u and u.is_authenticated else None

    def create(self, request, *args, **kwargs):
        payload = IntakeCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        supplier, warehouse = self._lookup_supplier_warehouse(data)
        batch = services.run_intake_from_text(
            tenant=request.tenant, raw_text=data["raw_text"], source=data["source"],
            supplier=supplier, warehouse=warehouse,
            vendor_doc_no=data.get("vendor_doc_no", ""), user=self._user(),
        )
        return Response(self.get_serializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="ocr")
    def ocr(self, request):
        """上傳進貨單照片 → 讀圖成明細 → 建待確認批次。"""
        from .ocr import OcrError, OcrNotConfigured

        image = request.FILES.get("image")
        if not image:
            return Response({"detail": "請附上圖片檔(欄位名 image)"}, status=status.HTTP_400_BAD_REQUEST)
        supplier, warehouse = self._lookup_supplier_warehouse(request.data)
        try:
            batch = services.run_intake_from_image(
                request.tenant, image, supplier=supplier, warehouse=warehouse, user=self._user()
            )
        except OcrNotConfigured:
            return Response(
                {"detail": "尚未設定讀圖模型(請先提供金鑰並開啟 OCR)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except OcrError as exc:
            return Response({"detail": f"讀圖失敗:{exc}"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="set-header")
    def set_header(self, request, pk=None):
        batch = self.get_object()
        body = SetHeaderSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        supplier, warehouse = self._lookup_supplier_warehouse(data)
        # 鎖倉帳號不可把批次指到別的倉
        ids = _allowed_wh_ids(request)
        if ids is not None and warehouse is not None and warehouse.id not in ids:
            return Response({"detail": "不可指定到非自己門市"}, status=status.HTTP_403_FORBIDDEN)
        kwargs = {"supplier": supplier, "warehouse": warehouse,
                  "tax_method": data.get("tax_method"), "vendor_doc_no": data.get("vendor_doc_no")}
        if "document_total" in data:
            kwargs["document_total"] = data["document_total"]
        try:
            services.set_header(batch, **kwargs)
        except services.IdentityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        batch.refresh_from_db()
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"])
    def commit(self, request, pk=None):
        batch = self.get_object()
        ids = _allowed_wh_ids(request)
        if ids is not None and batch.warehouse_id not in ids:
            return Response({"detail": "不可過帳到非自己門市"}, status=status.HTTP_403_FORBIDDEN)
        try:
            po = services.commit_batch(batch, user=self._user())
        except services.IdentityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        batch.refresh_from_db()
        data = self.get_serializer(batch).data
        data["purchase_order_no"] = po.no
        return Response(data)


class IntakeItemViewSet(
    mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """待確認明細逐筆處理:選候選 / 建新品 / 駁回。"""
    serializer_class = IntakeItemSerializer

    def get_queryset(self):
        return IntakeItem.objects.for_tenant(self.request.tenant).select_related(
            "matched_product", "batch"
        )

    def _user(self):
        u = getattr(self.request, "user", None)
        return u if u and u.is_authenticated else None

    @action(detail=True, methods=["post"])
    def match(self, request, pk=None):
        item = self.get_object()
        body = MatchItemSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        from apps.catalog.models import Product
        product = Product.objects.for_tenant(request.tenant).filter(
            id=body.validated_data["product"]
        ).first()
        if not product:
            return Response({"detail": "找不到指定的商品"}, status=status.HTTP_400_BAD_REQUEST)
        services.resolve_item_match(
            item, product, learn_alias=body.validated_data["learn_alias"], user=self._user()
        )
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"], url_path="new-product")
    def new_product(self, request, pk=None):
        item = self.get_object()
        body = NewProductForItemSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            services.resolve_item_new_product(item, body.validated_data, user=self._user())
        except services.IdentityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def correct(self, request, pk=None):
        item = self.get_object()
        body = CorrectIntakeItemSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.correct_intake_item(item, body.validated_data, user=self._user())
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        item = self.get_object()
        services.reject_item(item, user=self._user())
        return Response(self.get_serializer(item).data)
