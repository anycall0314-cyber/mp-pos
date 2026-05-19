from django.db import transaction
from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.inventory.models import ProductSerial, StockBalance
from apps.purchasing.models import PurchaseOrderItem

from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    search_fields = ["code", "name"]
    ordering_fields = ["sort_order", "code", "name", "created_at"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return Category.objects.for_tenant(self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    search_fields = ["sku", "name", "spec", "barcode", "category__name", "category__code"]
    ordering_fields = ["sku", "name", "created_at", "list_price"]
    ordering = ["sku"]
    filterset_fields = ["is_active", "category", "requires_serial", "is_secondhand", "is_virtual"]

    def get_queryset(self):
        tenant = self.request.tenant
        # 上一次進貨(不含作廢)的單價
        last_price_sq = (
            PurchaseOrderItem.objects.filter(
                product=OuterRef("pk"),
                po__is_void=False,
            )
            .order_by("-po__doc_date", "-id")
            .values("unit_price")[:1]
        )
        # 庫存統計:可選 ?warehouse=N 限定倉別
        # - 序號商品:Count(ProductSerial in_stock)
        # - 配件:Sum(StockBalance.qty)
        # 兩者擇一不為 0,加總即為總在庫
        warehouse_id = self.request.query_params.get("warehouse")
        stock_q = Q(serials__status=ProductSerial.Status.IN_STOCK)
        balance_filter = Q(product=OuterRef("pk"), tenant=tenant)
        if warehouse_id:
            try:
                wid = int(warehouse_id)
                stock_q &= Q(serials__warehouse_id=wid)
                balance_filter &= Q(warehouse_id=wid)
            except (TypeError, ValueError):
                pass
        balance_sub = (
            StockBalance.objects.filter(balance_filter)
            .order_by()
            .values("product")
            .annotate(total=Sum("qty"))
            .values("total")[:1]
        )
        return (
            Product.objects.for_tenant(tenant)
            .select_related("category")
            .annotate(
                serial_count=Count("serials", filter=stock_q),
                balance_total=Coalesce(
                    Subquery(balance_sub, output_field=IntegerField()),
                    Value(0),
                ),
                stock_qty=F("serial_count") + F("balance_total"),
                last_purchase_price=Subquery(last_price_sq),
            )
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk_create(self, request):
        """批次新增商品。

        payload:
        {
          "common": { "category": int, "requires_serial": bool, ... },
          "items": [
            { "name": "iPhone 15 Pro 黑", "spec": "256GB", "barcode": "", "list_price": "36900" }
          ]
        }
        任一筆驗證失敗 → 整批 rollback。
        """
        common = request.data.get("common", {}) or {}
        items = request.data.get("items", []) or []
        if not items:
            return Response(
                {"detail": "至少 1 筆"}, status=status.HTTP_400_BAD_REQUEST
            )

        created = []
        errors = []
        # 預先抓 category 名稱對應(per-tenant),per-row category_name 用到
        tenant = request.tenant
        cat_by_name = {
            c.name: c.id
            for c in Category.objects.for_tenant(tenant).all()
        }
        try:
            with transaction.atomic():
                for idx, row in enumerate(items, start=1):
                    payload = {**common, **row}
                    if not payload.get("name"):
                        errors.append({"line": idx, "errors": "品名為必填"})
                        continue
                    # per-row 類別覆寫:接受 category_name(較易輸入)
                    cat_name = payload.pop("category_name", None)
                    if cat_name:
                        cat_id = cat_by_name.get(cat_name)
                        if cat_id is None:
                            errors.append(
                                {"line": idx, "errors": f"類別「{cat_name}」不存在"}
                            )
                            continue
                        payload["category"] = cat_id
                    serializer = ProductSerializer(
                        data=payload, context={"request": request}
                    )
                    if serializer.is_valid():
                        instance = serializer.save(tenant=tenant)
                        created.append(ProductSerializer(instance).data)
                    else:
                        errors.append({"line": idx, "errors": serializer.errors})
                if errors:
                    raise ValueError("validation_failed")
        except ValueError:
            return Response(
                {"detail": "部分品項失敗,已全部復原", "errors": errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"created": created, "count": len(created)},
            status=status.HTTP_201_CREATED,
        )
