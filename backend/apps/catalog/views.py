from django.db import transaction
from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.inventory.models import ProductSerial, StockBalance, Warehouse
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
    # 基本搜尋欄;serials__serial_no 改由 get_search_fields 動態加入,
    # 只有純數字 6 碼以上的查詢(IMEI-like)才會把序號納入比對,
    # 避免「18 pro 256」把含 18 的 IMEI 中古機誤帶出來。
    search_fields = [
        "sku",
        "name",
        "spec",
        "barcode",
        "category__name",
        "category__code",
    ]
    ordering_fields = ["sku", "name", "created_at", "list_price"]
    ordering = ["sku"]
    filterset_fields = ["is_active", "category", "requires_serial", "is_secondhand", "is_virtual"]

    def get_search_fields(self):
        """動態 search_fields:IMEI-like 查詢才把序號比對加進來。"""
        base = list(self.search_fields)
        q = self.request.query_params.get("search", "").strip()
        if q and q.isdigit() and len(q) >= 6:
            base.append("serials__serial_no")
        return base

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
        # serial_count / balance_total 都用 Subquery 避免被 search 的 JOIN 干擾
        # (例如打 IMEI 時若 Count 走主 queryset 的 JOIN 會被過濾掉算錯)
        warehouse_id = self.request.query_params.get("warehouse")
        serial_filter = Q(
            product=OuterRef("pk"),
            status=ProductSerial.Status.IN_STOCK,
        )
        balance_filter = Q(product=OuterRef("pk"), tenant=tenant)
        if warehouse_id:
            try:
                wid = int(warehouse_id)
                serial_filter &= Q(warehouse_id=wid)
                balance_filter &= Q(warehouse_id=wid)
            except (TypeError, ValueError):
                pass
        serial_count_sq = (
            ProductSerial.objects.filter(serial_filter)
            .order_by()
            .values("product")
            .annotate(c=Count("*"))
            .values("c")[:1]
        )
        balance_sub = (
            StockBalance.objects.filter(balance_filter)
            .order_by()
            .values("product")
            .annotate(total=Sum("qty"))
            .values("total")[:1]
        )
        qs = (
            Product.objects.for_tenant(tenant)
            .select_related("category")
            .annotate(
                serial_count=Coalesce(
                    Subquery(serial_count_sq, output_field=IntegerField()),
                    Value(0),
                ),
                balance_total=Coalesce(
                    Subquery(balance_sub, output_field=IntegerField()),
                    Value(0),
                ),
                stock_qty=F("serial_count") + F("balance_total"),
                last_purchase_price=Subquery(last_price_sq),
            )
            # search 走 serials__serial_no 會 JOIN serials,distinct 避免單一商品出現多次
            .distinct()
        )
        # 庫存查詢頁 + 庫存倉別篩選 都會帶 ?warehouse 或要看 stock_qty,
        # 用 ?in_stock_only=true 過濾掉沒貨的(主檔頁不帶,所以仍可看到全部商品)
        if self.request.query_params.get("in_stock_only") == "true":
            qs = qs.filter(stock_qty__gt=0)
        # 銷貨用:能挑的 = 有庫存 OR 虛擬商品(手續費 / 收購二手 等不算庫存的)
        if self.request.query_params.get("sales_pickable") == "true":
            qs = qs.filter(Q(stock_qty__gt=0) | Q(is_virtual=True))
        return qs

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=["get"], url_path="stock-matrix")
    def stock_matrix(self, request):
        """庫存矩陣:每個商品在多個指定倉的庫存,給庫存查詢頁用。

        Query params:
        - warehouse_ids:逗號分隔的倉 ID;空白 → 該 tenant 所有 active 倉
        - search:關鍵字(走 sku/name/spec/barcode/category)
        - category:類別 ID
        - in_stock_only:預設 true,只列「有貨」的商品
        """
        tenant = request.tenant

        # 1. 倉別
        raw_ids = request.query_params.get("warehouse_ids", "")
        warehouse_ids = []
        if raw_ids:
            for x in raw_ids.split(","):
                x = x.strip()
                if x.isdigit():
                    warehouse_ids.append(int(x))
        if not warehouse_ids:
            warehouse_ids = list(
                Warehouse.objects.for_tenant(tenant)
                .filter(is_active=True)
                .values_list("id", flat=True)
            )
        warehouses = list(
            Warehouse.objects.for_tenant(tenant)
            .filter(id__in=warehouse_ids)
            .order_by("code")
            .values("id", "code", "name")
        )

        # 2. 商品篩選
        qs = (
            Product.objects.for_tenant(tenant)
            .select_related("category")
            .filter(is_active=True)
        )
        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(sku__icontains=search)
                | Q(name__icontains=search)
                | Q(spec__icontains=search)
                | Q(barcode__icontains=search)
                | Q(category__name__icontains=search)
                | Q(category__code__icontains=search)
            )
        category_id = request.query_params.get("category")
        if category_id and category_id.isdigit():
            qs = qs.filter(category_id=int(category_id))

        qs = qs.order_by("category__sort_order", "category__code", "sku")
        products = list(qs[:500])
        product_ids = [p.id for p in products]

        # 3. 批次抓「序號商品」每倉的在庫數
        serial_data = (
            ProductSerial.objects.filter(
                tenant=tenant,
                product_id__in=product_ids,
                warehouse_id__in=warehouse_ids,
                status=ProductSerial.Status.IN_STOCK,
            )
            .values("product_id", "warehouse_id")
            .annotate(c=Count("id"))
        )
        serial_map = {
            (d["product_id"], d["warehouse_id"]): d["c"] for d in serial_data
        }

        # 4. 批次抓「配件」每倉 balance
        balance_data = StockBalance.objects.filter(
            tenant=tenant,
            product_id__in=product_ids,
            warehouse_id__in=warehouse_ids,
        ).values("product_id", "warehouse_id", "qty")
        balance_map = {
            (d["product_id"], d["warehouse_id"]): d["qty"] for d in balance_data
        }

        in_stock_only = request.query_params.get("in_stock_only", "true") == "true"

        # 5. 組裝
        products_data = []
        for p in products:
            stock_by_wh = {}
            for wid in warehouse_ids:
                qty = serial_map.get((p.id, wid), 0) + balance_map.get(
                    (p.id, wid), 0
                )
                stock_by_wh[str(wid)] = qty
            total = sum(stock_by_wh.values())
            # 虛擬商品(手續費等)沒有實體庫存,不列入庫存表
            if p.is_virtual:
                continue
            if in_stock_only and total == 0:
                continue
            products_data.append(
                {
                    "id": p.id,
                    "sku": p.sku,
                    "name": p.name,
                    "category_id": p.category_id,
                    "category_name": p.category.name if p.category else "",
                    "category_code": p.category.code if p.category else "",
                    "list_price": str(p.list_price),
                    "weighted_avg_cost": str(p.weighted_avg_cost),
                    "requires_serial": p.requires_serial,
                    "is_secondhand": p.is_secondhand,
                    "stock_by_warehouse": stock_by_wh,
                    "stock_total": total,
                }
            )

        return Response(
            {
                "warehouses": warehouses,
                "products": products_data,
            }
        )

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
