from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.inventory.models import Warehouse
from apps.parties.models import Supplier

from . import services
from .models import IntakeBatch, IntakeItem, ProductAlias
from .serializers import (
    IntakeBatchSerializer,
    IntakeCreateSerializer,
    IntakeItemSerializer,
    MatchItemSerializer,
    NewProductForItemSerializer,
    ProductAliasSerializer,
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
        return (
            IntakeBatch.objects.for_tenant(self.request.tenant)
            .select_related("supplier", "warehouse")
            .prefetch_related("items__matched_product")
        )

    def _user(self):
        u = getattr(self.request, "user", None)
        return u if u and u.is_authenticated else None

    def create(self, request, *args, **kwargs):
        payload = IntakeCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        supplier = warehouse = None
        if data.get("supplier"):
            supplier = Supplier.objects.for_tenant(request.tenant).filter(id=data["supplier"]).first()
        if data.get("warehouse"):
            warehouse = Warehouse.objects.for_tenant(request.tenant).filter(id=data["warehouse"]).first()
        batch = services.run_intake_from_text(
            tenant=request.tenant, raw_text=data["raw_text"], source=data["source"],
            supplier=supplier, warehouse=warehouse,
            vendor_doc_no=data.get("vendor_doc_no", ""), user=self._user(),
        )
        return Response(self.get_serializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def commit(self, request, pk=None):
        batch = self.get_object()
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
    def reject(self, request, pk=None):
        item = self.get_object()
        services.reject_item(item, user=self._user())
        return Response(self.get_serializer(item).data)
