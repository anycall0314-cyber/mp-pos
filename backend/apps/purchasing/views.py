from django.db import transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core import cost_access
from apps.core.idempotency import IdempotentCreateMixin, key_of
from apps.core.warehouse_scoping import WarehouseScopedMixin
from apps.tenants import abilities

from .models import PurchaseOrder, PurchaseOrderCategory
from .serializers import (
    PurchaseOrderCategorySerializer,
    PurchaseOrderSerializer,
)
from .services import (
    PurchaseOrderError,
    commit_purchase_order,
    transferable_from_purchase,
    void_purchase_order,
)


class PurchaseOrderCategoryViewSet(viewsets.ModelViewSet):
    serializer_class = PurchaseOrderCategorySerializer
    search_fields = ["code", "name"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return PurchaseOrderCategory.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class PurchaseOrderViewSet(
    abilities.WritesNeed,
    IdempotentCreateMixin,
    WarehouseScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """進貨單:儲存即生效;不開放 update / delete,要取消請用 void action。"""

    needs_ability = abilities.PURCHASE      # 員工帳號的權限:開進貨單要有「進貨入庫」
    ability_exempt = ("void",)              # 作廢看的是「作廢進貨單」
    idempotency_scope = "purchase-order"
    serializer_class = PurchaseOrderSerializer
    search_fields = ["no", "supplier__code", "supplier__name", "note", "invoice_no"]
    ordering_fields = ["doc_date", "no", "created_at"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "warehouse": ["exact"],
        "supplier": ["exact"],
        "is_void": ["exact"],
        "category": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        # 進貨單上都是進價:沒有「進貨入庫」「廠商叫貨」的店員看不到(連清單都不給;owner 2026-10-28,
        # 規則在 core/cost_access.py)。作廢也算:作廢回的是整張單
        cost_access.require_purchase_prices(request.user)

    def get_queryset(self):
        return (
            PurchaseOrder.objects.for_tenant(self.request.tenant)
            .select_related("supplier", "warehouse", "category")
            .prefetch_related("items__product")
        )

    def perform_create(self, serializer):
        user = (
            self.request.user
            if getattr(self.request, "user", None) and self.request.user.is_authenticated
            else None
        )
        self.check_create_warehouse(serializer)
        with transaction.atomic():
            serializer.save(tenant=self.request.tenant, created_by=user)
            try:
                commit_purchase_order(serializer.instance)
            except PurchaseOrderError as exc:
                raise serializers.ValidationError({"detail": str(exc)})

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        abilities.require(request.user, abilities.VOID_PURCHASE)
        po = self.get_object()
        try:
            void_purchase_order(po)
        except PurchaseOrderError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        po = self.get_queryset().get(pk=po.pk)
        return Response(self.get_serializer(po).data)

    @action(detail=False, methods=["post"], url_path="quick-part")
    def quick_part(self, request):
        """維修單上當場進一個零件(規則在 quick_part.py):既有的零件或新建一個 + 一張只有這一行的進貨單。

        跟建進貨單一樣帶 Idempotency-Key:連線斷掉拿同一把再送,回已經進好的那一張、不會進兩次。
        """
        from apps.identity.dedup import DuplicateProduct

        from . import quick_part

        form = quick_part.QuickPartSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        key = key_of(request)
        with transaction.atomic():
            record = self._claim(request.tenant, key, request.user, scope="repair-quick-part") if key else None
            if record is not None and record.doc_no:
                done = PurchaseOrder.objects.for_tenant(request.tenant).filter(no=record.doc_no).first()
                if done is not None:
                    return Response(quick_part.result(done, request), headers={"Idempotent-Replay": "true"})
            try:
                po = quick_part.buy(self, request, form.validated_data)
            except DuplicateProduct as dup:
                transaction.set_rollback(True)          # 鑰匙也不留:改個名字或選既有的再送是新的一次
                return Response(dup.as_dict(), status=status.HTTP_409_CONFLICT)
            except PurchaseOrderError as exc:
                raise serializers.ValidationError({"detail": str(exc)})
            if record is not None:
                record.doc_no = po.no
                record.save(update_fields=["doc_no", "updated_at"])
            return Response(quick_part.result(po, request), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def transferable(self, request, pk=None):
        """整張調撥用:這張進貨單的東西現在還有哪些留在進貨門市(畫面拿去帶好一張調撥單)。只讀。

        鎖在自己門市的帳號只看得到自己門市的進貨單(跟進貨單清單同一套範圍)。
        """
        po = self.get_object()
        if po.is_void:
            return Response(
                {"detail": "這張進貨單已作廢,沒有東西可以調撥"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            "purchase_order": po.id,
            "no": po.no,
            "warehouse": po.warehouse_id,
            "warehouse_code": po.warehouse.code,
            "warehouse_name": po.warehouse.name,
            "lines": transferable_from_purchase(po),
        })
