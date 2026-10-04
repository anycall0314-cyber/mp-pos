from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from django.db import IntegrityError
from django.db.models import Q

from apps.catalog.models import Product
from apps.inventory.models import Warehouse
from apps.parties.models import Supplier
from apps.tenants.permissions import is_tenant_admin

from . import services
from .dedup import DuplicateProduct


def _allowed_wh_ids(request):
    """鎖倉帳號可操作的倉 id;None = 不限(tenant_admin / platform_admin)。"""
    user = getattr(request, "user", None)
    profile = getattr(user, "profile", None) if user and user.is_authenticated else None
    if not profile or not profile.is_warehouse_locked:
        return None
    return [profile.default_warehouse_id] if profile.default_warehouse_id else []
from .models import IntakeBatch, IntakeItem, ProductAlias
from .serializers import (
    CaptureUnitsSerializer,
    CorrectIntakeItemSerializer,
    IntakeBatchSerializer,
    IntakeCreateSerializer,
    IntakeItemSerializer,
    MatchItemSerializer,
    NewProductForItemSerializer,
    AliasConflict,
    ProductAliasSerializer,
    RememberPhraseSerializer,
    SetHeaderSerializer,
)


class ProductAliasViewSet(viewsets.ModelViewSet):
    """商品別名(別名管理頁用)。

    新增:能建檔 / 入庫的人都可以(記一個叫法)。
    修改 / 停用 / 刪除:限公司管理員 —— 那等於改掉「這句話指到哪個商品」,
    會影響之後每一次進貨的對應。
    """
    serializer_class = ProductAliasSerializer
    search_fields = ["value", "normalized_value"]
    filterset_fields = ["product", "supplier", "kind", "verified", "is_active"]
    ordering = ["product", "kind", "value"]

    def get_queryset(self):
        return ProductAlias.objects.for_tenant(self.request.tenant).select_related(
            "product", "supplier", "created_by", "updated_by"
        )

    def _require_admin(self):
        if not is_tenant_admin(self.request.user):
            raise PermissionDenied("修改或停用別名需要管理員權限")

    def create(self, request, *args, **kwargs):
        """手動加別名也走 service:籠統 / 多款符合的降為關鍵字,衝突回 409。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        alias, action_taken = services.create_alias(
            request.tenant, data["product"], data["kind"], data["value"],
            supplier=data.get("supplier"), verified=data.get("verified", True),
            note=data.get("note", ""), user=request.user,
        )
        if action_taken == "skipped" or alias is None:
            return Response({"value": ["請輸入別名內容"]}, status=status.HTTP_400_BAD_REQUEST)
        if action_taken == "conflict":
            raise AliasConflict(
                f"這個叫法已經指到「{alias.product.name}」。"
                "要改指請管理員先把那一筆停用"
            )
        return Response(
            self.get_serializer(alias).data,
            status=status.HTTP_200_OK if action_taken == "kept" else status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        """只能改啟用 / 已確認 / 備註,而且重新變成已確認時要過完整規則。"""
        self._require_admin()
        alias = self.get_object()
        # 送回來跟原本一樣的欄位不算「要改」(前端可能整筆送回)
        changes = {
            k: v for k, v in request.data.items()
            if k in ("is_active", "verified", "note", "product", "supplier", "kind", "value")
        }
        same = {
            "product": alias.product_id, "supplier": alias.supplier_id,
            "kind": alias.kind, "value": alias.value,
        }
        changes = {k: v for k, v in changes.items() if not (k in same and same[k] == v)}
        for flag in ("is_active", "verified"):
            if flag in changes and not isinstance(changes[flag], bool):
                changes[flag] = str(changes[flag]).lower() in ("true", "1", "yes")
        try:
            services.update_alias(alias, changes, user=request.user)
        except services.AliasOwnedElsewhere as exc:
            raise AliasConflict(str(exc))
        except services.IdentityError as exc:
            raise ValidationError({"detail": [str(exc)]})
        return Response(self.get_serializer(alias).data)

    def perform_destroy(self, instance):
        self._require_admin()
        instance.delete()

    @action(detail=False, methods=["post"])
    def remember(self, request):
        """店員按「記住這個叫法」。太籠統或有好幾款都符合的,只記成搜尋關鍵字。"""
        body = RememberPhraseSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        product = Product.objects.for_tenant(request.tenant).filter(id=data["product"]).first()
        if product is None:
            return Response({"detail": "找不到指定的商品"}, status=status.HTTP_400_BAD_REQUEST)
        supplier = None
        if data.get("supplier"):
            supplier = Supplier.objects.for_tenant(request.tenant).filter(
                id=data["supplier"]).first()
            if supplier is None:
                return Response({"detail": "找不到指定的廠商"}, status=status.HTTP_400_BAD_REQUEST)
        if data["repoint"] and not is_tenant_admin(request.user):
            return Response(
                {"detail": "改指別名需要管理員權限"}, status=status.HTTP_403_FORBIDDEN
            )
        # 預設所有人遇到衝突都先看到衝突;管理員要改指得明確帶 repoint=true
        alias, action_taken, owner = services.remember_phrase(
            request.tenant, product, data["value"], supplier=supplier,
            user=request.user, can_repoint=data["repoint"],
        )
        if action_taken == "conflict":
            return Response(
                {
                    "detail": f"這個叫法已經指到「{owner.name}」,沒有改動",
                    "action": action_taken,
                    "owner": {"id": owner.id, "sku": owner.sku, "name": owner.name},
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response({
            "action": action_taken,
            "alias": self.get_serializer(alias).data if alias is not None else None,
        })


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
            .prefetch_related(
                "items__matched_product", "items__received_units__identifiers", "documents"
            )
        )
        # 鎖倉帳號只看自己倉的批次(尚未指定倉的草稿也看得到)
        ids = _allowed_wh_ids(self.request)
        if ids is not None:
            qs = qs.filter(Q(warehouse_id__in=ids) | Q(warehouse__isnull=True))
        return qs

    def _lookup_supplier_warehouse(self, data):
        """供應商 / 門市是原始編號:有送就一定要是這家公司的,找不到回 400(不靜默當成空白)。"""
        from rest_framework.exceptions import ValidationError

        found = {}
        for field, model in (("supplier", Supplier), ("warehouse", Warehouse)):
            raw = data.get(field)
            if not raw:
                found[field] = None
                continue
            obj = (
                model.objects.for_tenant(self.request.tenant).filter(id=raw).first()
                if str(raw).isdigit() else None
            )
            if obj is None:
                raise ValidationError({field: "找不到這筆資料"})
            found[field] = obj
        return found["supplier"], found["warehouse"]

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
        ).prefetch_related("received_units__identifiers")

    def _user(self):
        u = getattr(self.request, "user", None)
        return u if u and u.is_authenticated else None

    @action(detail=True, methods=["post"])
    def match(self, request, pk=None):
        item = self.get_object()
        body = MatchItemSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        product = Product.objects.for_tenant(request.tenant).filter(
            id=body.validated_data["product"]
        ).first()
        if not product:
            return Response({"detail": "找不到指定的商品"}, status=status.HTTP_400_BAD_REQUEST)
        admin = is_tenant_admin(request.user)
        restore = body.validated_data["restore"]
        repoint = body.validated_data["repoint"]
        if not product.is_active and restore and not admin:
            return Response(
                {"detail": "恢復已停用的商品需要管理員權限"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if repoint and not admin:
            return Response(
                {"detail": "改指別名需要管理員權限"}, status=status.HTTP_403_FORBIDDEN
            )
        try:
            services.resolve_item_match(
                item, product, learn_alias=body.validated_data["learn_alias"],
                user=self._user(), restore_inactive=restore, can_repoint=repoint,
            )
        except services.IdentityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"], url_path="new-product")
    def new_product(self, request, pk=None):
        item = self.get_object()
        body = NewProductForItemSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            services.resolve_item_new_product(item, body.validated_data, user=self._user())
        except DuplicateProduct as dup:
            return Response(dup.as_dict(), status=status.HTTP_409_CONFLICT)
        except IntegrityError as exc:
            # 有人同時建了同名的商品:資料庫擋住了,這裡回看得懂的錯
            if "uniq_product_tenant_name" not in str(exc):
                raise
            return Response(
                {"detail": "有人剛建立了同名商品,請重新確認"},
                status=status.HTTP_409_CONFLICT,
            )
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
    def units(self, request, pk=None):
        """逐台登記實體 unit + 識別碼(序號商品用)。"""
        item = self.get_object()
        body = CaptureUnitsSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            services.capture_units(item, body.validated_data["units"], user=self._user())
        except services.IdentityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        item.refresh_from_db()
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        item = self.get_object()
        services.reject_item(item, user=self._user())
        return Response(self.get_serializer(item).data)
