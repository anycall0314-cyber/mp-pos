from datetime import timedelta

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db import transaction
from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.filters import _is_postgres
from apps.inventory.models import ProductSerial, StockBalance, Warehouse
from apps.purchasing.models import PurchaseOrderItem
from apps.sales.models import SalesOrderItem
from apps.transfers.models import TransferOrder, TransferOrderItem

from .brand_import import import_brands_series
from .import_service import import_products_from_file
from .models import (
    Brand,
    Category,
    PartTemplate,
    PhoneSeries,
    Product,
    ProductRelation,
)
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    PartTemplateSerializer,
    PhoneSeriesSerializer,
    ProductSerializer,
)
from .services_parts import bulk_create_parts, build_preview


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
        """依查詢內容動態調整搜尋欄位:

        - 含中文:只比對「描述性」欄位(品名 / 規格 / 類別名稱),
          不碰品號 / 條碼 / IMEI(那些是英數代碼,中文查詢不該命中)。
          這樣「中古 11」的「11」只會在品名找(命中 中古iPhone11),
          不會因為 SKU 剛好是 AA-000011 而把不相干的商品帶出來。
        - 純英數:比對代碼 + 描述欄位;且純數字 6 碼以上才把序號(IMEI)
          納入比對,避免「18 pro 256」誤命中含 18 的中古機 IMEI。
        """
        q = self.request.query_params.get("search", "").strip()
        # 偵測是否含中日韓統一漢字(U+4E00–U+9FFF),涵蓋繁體中文常用字
        has_cjk = any("一" <= ch <= "鿿" for ch in q)
        if has_cjk:
            return ["name", "spec", "category__name"]
        base = list(self.search_fields)
        if q and q.isdigit() and len(q) >= 6:
            base.append("serials__serial_no")
        return base

    def filter_queryset(self, queryset):
        """在套完一般 filter / search 後,搜尋情境下改以「相關度」排序:

        DRF 的 OrderingFilter 會把結果壓回預設 `ordering=["sku"]`,所以即使有命中,
        清單仍是品號順序(打「手機 17」時 iPhone 15 Pro 因品號小排在前)。
        這裡在最後一步、僅針對「有 search 且未明確指定 ordering」的查詢,
        用 TrigramWordSimilarity 對查詢字串重新排序,最符合的排前面,品號作為次要排序。
        只作用在商品,供應商 / 客戶等其他 viewset 不受影響。
        """
        qs = super().filter_queryset(queryset)
        q = self.request.query_params.get("search", "").strip()
        explicit_ordering = self.request.query_params.get("ordering")
        if not q or explicit_ordering or not _is_postgres():
            return qs
        plain_fields = [
            f[1:] if f and f[0] in {"^", "=", "$", "@"} else f
            for f in self.get_search_fields()
        ]
        sim_exprs = [TrigramWordSimilarity(q, f) for f in plain_fields]
        max_sim = sim_exprs[0] if len(sim_exprs) == 1 else Greatest(*sim_exprs)
        return qs.annotate(_relevance=max_sim).order_by(
            F("_relevance").desc(nulls_last=True), "sku"
        )

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
        # 排除零件倉商品(除非 is_externally_sellable=True,可對外調貨給同行)
        if self.request.query_params.get("sales_pickable") == "true":
            qs = qs.filter(Q(stock_qty__gt=0) | Q(is_virtual=True)).filter(
                Q(warehouse_type=Product.WarehouseType.PRODUCT)
                | Q(
                    warehouse_type=Product.WarehouseType.PARTS,
                    is_externally_sellable=True,
                )
            )
        # 機型配件挑「相容主機」用:只列主機(accessory_type=none)
        if self.request.query_params.get("host_only") == "true":
            qs = qs.filter(accessory_type=Product.AccessoryType.NONE)
        return qs

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(
        detail=False,
        methods=["post"],
        url_path="import",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def import_csv(self, request):
        """CSV / Excel 商品匯入。

        - 必填:品名 / 類別(名稱或代碼)/ 品號
        - 選填:安全庫存(預設 0)/ 建議售價 / 條碼
        - 類別不存在自動建立,品號 / 品名重複跳過
        - 新匯入商品 lifecycle_status=pending,不影響庫存警示
        - dry_run=true(預設)只回報告不寫入;false 才正式 commit

        Body(multipart):
            file: 上傳檔(xlsx / csv)
            dry_run: "true" / "false"(預設 true)
        """
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"detail": "請上傳 xlsx 或 csv 檔(欄位名稱 file)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dry_run_raw = request.data.get("dry_run", "true")
        dry_run = str(dry_run_raw).lower() not in ("false", "0", "no")
        try:
            report = import_products_from_file(
                request.tenant, file_obj, file_obj.name, dry_run=dry_run
            )
        except ValueError as e:
            return Response(
                {"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(report)

    @action(detail=False, methods=["get"], url_path="phone-models")
    def phone_models(self, request):
        """列出所有「機型」(distinct phone_model_key 內含於主機 SKU)。

        每筆回傳:
        - model_key:lowercase 機型 key
        - model_name:顯示用機型名稱
        - sku_count:該機型有幾支 SKU
        - total_stock:該機型所有 SKU 的跨倉庫存合計
        - any_lifecycle_status:採用任一支 active 的狀態,沒有則用第一支
        - sample_sku:代表 SKU(顯示用)
        - brand / series:任一支提供(用於後續 filter)
        """
        tenant = request.tenant
        # 主機 SKU(accessory_type=none),含跨倉庫存 annotation
        serial_sq = (
            ProductSerial.objects.filter(
                product=OuterRef("pk"),
                status=ProductSerial.Status.IN_STOCK,
            )
            .order_by()
            .values("product")
            .annotate(c=Count("*"))
            .values("c")[:1]
        )
        balance_sq = (
            StockBalance.objects.filter(
                product=OuterRef("pk"), tenant=tenant
            )
            .order_by()
            .values("product")
            .annotate(t=Sum("qty"))
            .values("t")[:1]
        )
        # 只列「需要序號」的主機:配件 / 耗材即使 accessory_type 漏填,也不應出現在機型清單
        qs = (
            Product.objects.for_tenant(tenant)
            .filter(
                accessory_type=Product.AccessoryType.NONE,
                requires_serial=True,
                is_active=True,
                is_virtual=False,
            )
            .annotate(
                _sc=Coalesce(Subquery(serial_sq, output_field=IntegerField()), Value(0)),
                _bc=Coalesce(Subquery(balance_sq, output_field=IntegerField()), Value(0)),
                stock=F("_sc") + F("_bc"),
            )
            .order_by("name")
        )

        # 可選 search 過濾
        q = request.query_params.get("search", "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(series__icontains=q)
            )

        # group by model_key — 優先用 Product.brand FK 的 code;沒設就退回從品名推斷
        from .phone_model import infer_brand_from_name
        groups: dict[str, dict] = {}
        for p in qs.select_related("brand", "series"):
            key = p.phone_model_key
            if not key:
                continue
            g = groups.get(key)
            if g is None:
                brand_code = p.brand.code if p.brand_id else ""
                brand_name = p.brand.name if p.brand_id else ""
                if not brand_code:
                    brand_code = infer_brand_from_name(p.name)
                    brand_name = brand_code  # fallback,沒主檔
                g = {
                    "model_key": key,
                    "model_name": p.phone_model_name,
                    "sku_count": 0,
                    "total_stock": 0,
                    "any_lifecycle_status": p.lifecycle_status,
                    "any_lifecycle_status_label": p.get_lifecycle_status_display(),
                    "sample_sku_id": p.id,
                    "sample_sku_name": p.name,
                    "brand": brand_code,
                    "brand_name": brand_name,
                    "series_id": p.series_id,
                    "series_name": p.series.name if p.series_id else "",
                }
                groups[key] = g
            g["sku_count"] += 1
            g["total_stock"] += int(p.stock)
            # 任一支 active → 該機型整體記 active(顯示用)
            if p.lifecycle_status == Product.LifecycleStatus.ACTIVE:
                g["any_lifecycle_status"] = p.lifecycle_status
                g["any_lifecycle_status_label"] = p.get_lifecycle_status_display()

        return Response(sorted(groups.values(), key=lambda g: g["model_name"]))

    @action(detail=True, methods=["get"], url_path="compatibility")
    def compatibility(self, request, pk=None):
        """商品相容性查詢。

        - 主機(accessory_type=none):列出所有「以此為 host_product」的配件,
          含品名/類別/目前跨倉庫存
        - 機型配件(accessory_type=phone_specific):列出所有 related_hosts 主機,
          含品名/狀態/庫存/需求熱度 (近 30 天日均銷量)
        - 通用配件:回傳空 list

        需求熱度 demand_label:
          0       → 無近期銷售
          0~1     → 冷門
          1~3     → 平穩
          3~10    → 熱銷
          >=10    → 爆款
        """
        tenant = request.tenant
        product = self.get_object()
        is_host = product.accessory_type == Product.AccessoryType.NONE
        is_accessory_specific = (
            product.accessory_type == Product.AccessoryType.PHONE_SPECIFIC
        )

        if is_host:
            # 主機:用此 product 的 phone_model_key 反查 ProductRelation
            # → 列出所有「綁此機型」的配件 SKU
            my_key = product.phone_model_key
            related_ids = list(
                ProductRelation.objects.filter(
                    tenant=tenant, host_model_key=my_key
                ).values_list("accessory_product_id", flat=True).distinct()
            )
            role = "host"
        elif is_accessory_specific:
            # 配件:列出綁定的所有 model_key,每個 key 反查同款主機 SKU
            host_keys = list(
                ProductRelation.objects.filter(
                    tenant=tenant, accessory_product=product
                ).values_list("host_model_key", flat=True).distinct()
            )
            if not host_keys:
                return Response({"role": "accessory", "items": []})
            # 撈出所有 key 對應的主機 SKU(可能多個機型,每機型多個 SKU)
            all_hosts = list(
                Product.objects.for_tenant(tenant)
                .filter(
                    accessory_type=Product.AccessoryType.NONE,
                    is_active=True,
                    is_virtual=False,
                )
            )
            # 依 phone_model_key match
            related_ids = [
                p.id for p in all_hosts if p.phone_model_key in host_keys
            ]
            role = "accessory"
        else:
            return Response({"role": "universal", "items": []})

        if not related_ids:
            return Response({"role": role, "items": []})

        # 跨倉庫存 annotate(同 stock-matrix 模式)
        serial_sq = (
            ProductSerial.objects.filter(
                product=OuterRef("pk"),
                status=ProductSerial.Status.IN_STOCK,
            )
            .order_by()
            .values("product")
            .annotate(c=Count("*"))
            .values("c")[:1]
        )
        balance_sq = (
            StockBalance.objects.filter(
                product=OuterRef("pk"), tenant=tenant
            )
            .order_by()
            .values("product")
            .annotate(t=Sum("qty"))
            .values("t")[:1]
        )
        related_qs = (
            Product.objects.for_tenant(tenant)
            .filter(id__in=related_ids)
            .select_related("category")
            .annotate(
                _sc=Coalesce(Subquery(serial_sq, output_field=IntegerField()), Value(0)),
                _bc=Coalesce(Subquery(balance_sq, output_field=IntegerField()), Value(0)),
                stock=F("_sc") + F("_bc"),
            )
        )

        # 算近 30 天日均銷量
        since = timezone.now().date() - timedelta(days=30)
        sales_rows = (
            SalesOrderItem.objects.for_tenant(tenant)
            .filter(
                product_id__in=related_ids,
                so__doc_date__gte=since,
                so__is_void=False,
            )
            .values("product_id")
            .annotate(total=Sum("qty"))
        )
        daily_avg = {r["product_id"]: float(r["total"] or 0) / 30 for r in sales_rows}

        def _label(avg: float) -> str:
            if avg <= 0:
                return "無近期銷售"
            if avg < 1:
                return "冷門"
            if avg < 3:
                return "平穩"
            if avg < 10:
                return "熱銷"
            return "爆款"

        items = []
        if role == "host":
            # 主機看配件 → 仍以 SKU 為單位列(配件本來就 SKU 級)
            for p in related_qs:
                avg = daily_avg.get(p.id, 0.0)
                items.append(
                    {
                        "id": p.id,
                        "sku": p.sku,
                        "name": p.name,
                        "category_name": p.category.name if p.category else "",
                        "current_qty": int(p.stock),
                        "lifecycle_status": p.lifecycle_status,
                        "lifecycle_status_label": p.get_lifecycle_status_display(),
                        "accessory_type": p.accessory_type,
                        "daily_avg": round(avg, 2),
                        "demand_label": _label(avg),
                        "is_model": False,
                    }
                )
            items.sort(key=lambda x: x["current_qty"])
        else:
            # 配件看主機 → 依機型 group(每個 model_key 一個 row,
            # current_qty=機型總庫存,daily_avg=機型總日均)
            groups: dict[str, dict] = {}
            for p in related_qs:
                key = p.phone_model_key
                if not key:
                    continue
                avg = daily_avg.get(p.id, 0.0)
                g = groups.get(key)
                if g is None:
                    g = {
                        "id": p.id,  # 代表 SKU
                        "model_key": key,
                        "name": p.phone_model_name,
                        "sku_count": 0,
                        "current_qty": 0,
                        "daily_avg": 0.0,
                        "lifecycle_status": p.lifecycle_status,
                        "lifecycle_status_label": p.get_lifecycle_status_display(),
                        "accessory_type": p.accessory_type,
                        "is_model": True,
                    }
                    groups[key] = g
                g["sku_count"] += 1
                g["current_qty"] += int(p.stock)
                g["daily_avg"] += avg
                # 取 active 的狀態作代表
                if p.lifecycle_status == Product.LifecycleStatus.ACTIVE:
                    g["lifecycle_status"] = p.lifecycle_status
                    g["lifecycle_status_label"] = p.get_lifecycle_status_display()
            for g in groups.values():
                g["daily_avg"] = round(g["daily_avg"], 2)
                g["demand_label"] = _label(g["daily_avg"])
                # 補幾個欄位讓前端共用 component 不會炸
                g["sku"] = ""
                g["category_name"] = f"{g['sku_count']} 款 SKU"
            items = sorted(groups.values(), key=lambda x: -x["daily_avg"])

        return Response(
            {
                "role": role,
                "self": {
                    "id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "accessory_type": product.accessory_type,
                    "lifecycle_status": product.lifecycle_status,
                    "lifecycle_status_label": product.get_lifecycle_status_display(),
                },
                "items": items,
            }
        )

    @action(detail=True, methods=["get"], url_path="pending-transfers")
    def pending_transfers(self, request, pk=None):
        """配件用:列出此商品「已派發、尚未確認」的調撥明細。

        配件在派發當下就從來源倉 balance 扣掉、要等目的倉確認才入帳,
        中間這段在庫存矩陣上看不出來。此 endpoint 讓使用者確認某商品是否
        正卡在調撥途中。

        - 可帶 ?warehouse=N 只看與該倉相關的(從該倉出 or 即將進該倉)。
        - direction:相對於 ?warehouse,out = 從該倉派出,in = 即將進該倉。
        """
        tenant = request.tenant
        product = self.get_object()
        items = (
            TransferOrderItem.objects.filter(
                tenant=tenant,
                product=product,
                to__status=TransferOrder.Status.DISPATCHED,
                to__is_void=False,
            )
            .select_related("to", "to__from_warehouse", "to__to_warehouse")
            .order_by("-to__doc_date", "-to_id")
        )
        wh = request.query_params.get("warehouse")
        wid = int(wh) if wh and wh.isdigit() else None
        if wid is not None:
            items = items.filter(
                Q(to__from_warehouse_id=wid) | Q(to__to_warehouse_id=wid)
            )
        data = []
        for it in items:
            order = it.to
            direction = None
            if wid is not None:
                direction = "out" if order.from_warehouse_id == wid else "in"
            data.append(
                {
                    "transfer_no": order.no,
                    "doc_date": order.doc_date,
                    "qty": it.qty,
                    "direction": direction,
                    "from_warehouse": {
                        "code": order.from_warehouse.code,
                        "name": order.from_warehouse.name,
                    },
                    "to_warehouse": {
                        "code": order.to_warehouse.code,
                        "name": order.to_warehouse.name,
                    },
                }
            )
        return Response(data)

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
        # category 單選(舊版相容);category_ids 多選 CSV
        category_id = request.query_params.get("category")
        if category_id and category_id.isdigit():
            qs = qs.filter(category_id=int(category_id))
        raw_cat_ids = request.query_params.get("category_ids", "")
        if raw_cat_ids:
            cat_ids = [
                int(x) for x in raw_cat_ids.split(",")
                if x.strip().isdigit()
            ]
            if cat_ids:
                qs = qs.filter(category_id__in=cat_ids)

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
                    "spec": p.spec,
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

    @action(detail=False, methods=["post"], url_path="bulk-edit")
    def bulk_edit(self, request):
        """批次修改既有商品欄位。

        payload:
        {
          "ids": [1, 2, 3],
          "patch": {
            "list_price": "990",
            "lifecycle_status": "clearance",
            "accessory_type": "phone_specific",
            "related_host_keys": ["iphone 15 pro"]  // 覆寫(replace)
            ...
          }
        }
        - 用 ProductSerializer partial=True 做欄位驗證
        - 任一筆驗證失敗就整批 rollback,回傳每筆錯誤
        - 不允許批次修改 name(避免命名衝突)
        """
        ids = request.data.get("ids") or []
        patch = request.data.get("patch") or {}
        if not ids:
            return Response(
                {"detail": "ids 為空"}, status=status.HTTP_400_BAD_REQUEST
            )
        if not patch:
            return Response(
                {"detail": "patch 為空,沒有要修改的欄位"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if "name" in patch or "sku" in patch:
            return Response(
                {"detail": "不允許批次修改 name / sku(避免命名衝突)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = (
            Product.objects.for_tenant(request.tenant)
            .filter(id__in=ids)
        )
        if not qs.exists():
            return Response(
                {"detail": "找不到任何符合的商品"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        updated_ids: list[int] = []
        errors: list[dict] = []
        try:
            with transaction.atomic():
                for p in qs:
                    ser = ProductSerializer(
                        p,
                        data=patch,
                        partial=True,
                        context={"request": request},
                    )
                    if ser.is_valid():
                        ser.save()
                        updated_ids.append(p.id)
                    else:
                        errors.append(
                            {"id": p.id, "name": p.name, "errors": ser.errors}
                        )
                if errors:
                    raise ValueError("partial_failed")
        except ValueError:
            return Response(
                {"detail": "部分商品失敗,已全部復原", "errors": errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"updated": len(updated_ids), "ids": updated_ids})

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


class BrandViewSet(viewsets.ModelViewSet):
    """品牌主檔 CRUD(per-tenant)。"""

    serializer_class = BrandSerializer
    search_fields = ["code", "name"]
    ordering_fields = ["sort_order", "code", "name"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active"]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return (
            Brand.objects.for_tenant(self.request.tenant)
            .annotate(series_count=Count("series"))
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(
        detail=False,
        methods=["post"],
        url_path="import",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def import_csv(self, request):
        """品牌 + 系列 批次匯入。

        CSV / xlsx 一行一個系列(同品牌可多列):
          品牌名稱, 品牌代碼, 系列名稱, 系列代碼, 品牌排序, 系列排序

        dry_run=true(預設)只回 preview 不寫入;
        dry_run=false 才正式 commit。
        """
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"detail": "請上傳 file 欄位(CSV 或 xlsx)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dry_run = str(request.data.get("dry_run", "true")).lower() == "true"
        result = import_brands_series(
            request.tenant,
            file_obj,
            file_obj.name,
            dry_run=dry_run,
        )
        if not dry_run and result.get("errors"):
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class PhoneSeriesViewSet(viewsets.ModelViewSet):
    """產品系列主檔 CRUD(掛在 Brand 下,per-tenant)。

    用 ?brand=<id> 過濾單一品牌的系列。
    """

    serializer_class = PhoneSeriesSerializer
    search_fields = ["code", "name"]
    ordering_fields = ["sort_order", "code", "name"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active", "brand"]

    def get_queryset(self):
        return PhoneSeries.objects.for_tenant(
            self.request.tenant
        ).select_related("brand")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class PartTemplateViewSet(viewsets.ModelViewSet):
    """零件範本 CRUD + 批次建立 actions。

    /api/v1/part-templates/                            CRUD
    /api/v1/part-templates/{id}/preview/               POST 預覽笛卡兒積
    /api/v1/part-templates/{id}/bulk-create/           POST 真的批次建立
    """

    serializer_class = PartTemplateSerializer
    search_fields = ["name", "note"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return (
            PartTemplate.objects.for_tenant(self.request.tenant)
            .prefetch_related("items")
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=["post"], url_path="preview")
    def preview(self, request, pk=None):
        body = request.data
        rows = build_preview(
            request.tenant,
            pk,
            body.get("model_keys", []),
            body.get("defaults", {}),
        )
        return Response({"rows": rows})

    @action(detail=True, methods=["post"], url_path="bulk-create")
    def bulk_create_action(self, request, pk=None):
        body = request.data
        category_id = body.get("category_id")
        rows = body.get("rows") or []
        if not category_id:
            return Response(
                {"detail": "category_id 為必填"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not rows:
            return Response(
                {"detail": "rows 為空,沒有要建立的項目"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = bulk_create_parts(request.tenant, category_id, rows)
        return Response(result)
