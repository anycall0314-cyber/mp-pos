from datetime import timedelta

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db import IntegrityError, transaction
from django.db.models import (
    Case,
    Count,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from apps.core.filters import _is_postgres
from apps.identity.dedup import DuplicateProduct
from apps.identity.product_match import MatchResult, find_candidates
from apps.inventory.identifiers import find_serial_ids
from apps.inventory.models import (
    ProductSerial,
    ProductSerialIdentifier,
    StockBalance,
    Warehouse,
)
from apps.parties.models import Supplier
from apps.photos.models import ProductPhoto
from apps.photos.services import (
    PhotoRuleError, apply_to_product, committed_product, photo_urls,
)
from apps.purchasing.models import PurchaseOrderItem
from apps.sales.models import SalesOrderItem
from apps.tenants.permissions import IsPlatformAdmin, is_tenant_admin
from apps.transfers.models import TransferOrder, TransferOrderItem

from . import shop_terms
from .brand_import import import_brands_series
from .import_service import import_products_from_file
from .models import (
    Brand,
    Category,
    Condition,
    PartTemplate,
    PhoneSeries,
    Product,
    ProductRelation,
    ProductType,
)
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    ConditionSerializer,
    PartTemplateSerializer,
    PhoneSeriesSerializer,
    ProductSerializer,
    ProductTypeSerializer,
)
from .services_dynamic_stock import insights_trending
from .services_model_bundle import (
    create_phone_model_bundle,
    preview_phone_model_bundle,
)
from .services_parts import bulk_create_parts, build_preview


def _own_category_id(tenant, value):
    """批次修改送來的類別編號:是這家公司的類別才回編號;沒帶、亂填、別家的都回 None(那些由序列化器擋)。"""
    try:
        pk = int(value)
    except (TypeError, ValueError):
        return None
    return (
        Category.objects.for_tenant(tenant).filter(pk=pk)
        .values_list("pk", flat=True).first()
    )


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
        q = self.request.query_params.get("search", "").strip()
        # 共用比對找到的商品:寫法不同(reno-16 / reno16、側翻藍 / 側翻 藍)
        # 或用別名叫的。只收「輸入的每一項都對得上」的,不收只是相關的。
        # 這條路只看品名特徵與別名,不碰品號 / IMEI,下面兩個安全閥不受影響。
        extra_ids = (
            find_candidates(
                self.request.tenant, q, limit=200, with_related=False
            ).product_ids
            if q else []
        )
        # 刷到的是某一台設備的碼(IMEI 或 SN):那一台的商品要出現。
        # 只收「完全相同」的碼,不做部分比對,所以不會像「18 pro 256」那樣誤中別台的 IMEI。
        code_ids = (
            list(ProductSerial.objects.filter(pk__in=find_serial_ids(self.request.tenant, q))
                 .values_list("product_id", flat=True))
            if q else []
        )
        extra_ids = [*code_ids, *[i for i in extra_ids if i not in set(code_ids)]]
        qs = queryset
        for backend in list(self.filter_backends):
            if extra_ids and issubclass(backend, SearchFilter):
                # 其他篩選(啟用 / 類別 / 可銷貨)照常套在兩邊,這裡只把
                # 「文字搜尋命中」放寬成「文字命中 或 共用比對命中」。
                searched = backend().filter_queryset(self.request, qs, self)
                qs = qs.filter(
                    Q(pk__in=searched.order_by().values("pk")) | Q(pk__in=extra_ids)
                )
            else:
                qs = backend().filter_queryset(self.request, qs, self)
        explicit_ordering = self.request.query_params.get("ordering")
        if not q or explicit_ordering:
            return qs
        resolved = Case(
            When(pk__in=extra_ids, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
        if not _is_postgres():
            return qs.annotate(_resolved=resolved).order_by("_resolved", "sku")
        # 相關度不看序號:序號那一欄要接到設備表,一個商品有幾台就會變成幾列(同一個商品重複出現);
        # 刷到碼的商品已經由上面的 _resolved 排在最前面。
        plain_fields = [
            f[1:] if f and f[0] in {"^", "=", "$", "@"} else f
            for f in self.get_search_fields()
            if not f.startswith("serials__")
        ]
        sim_exprs = [TrigramWordSimilarity(q, f) for f in plain_fields]
        max_sim = sim_exprs[0] if len(sim_exprs) == 1 else Greatest(*sim_exprs)
        return qs.annotate(_relevance=max_sim, _resolved=resolved).order_by(
            "_resolved", F("_relevance").desc(nulls_last=True), "sku"
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
        warehouse_id = getattr(self, "_warehouse_override", None) or (
            self.request.query_params.get("warehouse")
        )
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
            # brand / series / condition 都是 serializer 每筆會讀的 FK
            # (condition 還被 tracks_unit_condition 用到),不預載就是 N+1
            .select_related(
                "category", "brand", "series", "condition", "phone_model"
            )
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
                # 照片:有幾張、主圖是哪一張(清單 / 搜尋結果要顯示縮圖;用 Subquery 不受 search 的 JOIN 影響)
                photo_count_n=Coalesce(
                    Subquery(
                        ProductPhoto.objects.filter(product=OuterRef("pk"))
                        .order_by().values("product").annotate(c=Count("*")).values("c")[:1],
                        output_field=IntegerField(),
                    ),
                    Value(0),
                ),
                primary_photo_id=Subquery(
                    ProductPhoto.objects.filter(product=OuterRef("pk"), is_primary=True)
                    .order_by().values("pk")[:1]
                ),
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

    def _photos_payload(self):
        """商品存檔時一起送來的照片清單(見 apps/photos/services.py 的 apply_to_product);沒帶就是 None。"""
        data = self.request.data
        photos = data.get("photos") if hasattr(data, "get") else None
        return photos if isinstance(photos, dict) else None

    def create(self, request, *args, **kwargs):
        # 帶著同一份照片作業重送(第一次其實存成功了、只是回應沒收到):回那個商品,不建第二個品號
        photos = self._photos_payload()
        if photos:
            done = committed_product(request.tenant, request.user, photos.get("draft"))
            if done is not None:
                # 「重送」= 同一張表單原樣再送一次,品名一定一樣。品名不一樣就是另一張表單拿到了同一份照片作業
                # (兩個分頁都接回同一份草稿):不能回別人建的那個商品、讓他以為自己的存好了
                if str(request.data.get("name") or "").strip() != done.name:
                    return Response(
                        {"detail": f"這些照片已經跟著「{done.name}」存好了,請關掉表單重新開一次"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                saved = self.get_queryset().filter(pk=done.pk).first()
                if saved is not None:
                    return Response(self.get_serializer(saved).data)
        # 防重複關卡的條碼鎖是交易層級的,整個新增要包在同一個交易裡
        try:
            with transaction.atomic():
                return super().create(request, *args, **kwargs)
        except PhotoRuleError as exc:
            # 照片沒套成:商品也不建(同一個交易,整筆退回)
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except DuplicateProduct as dup:
            return Response(dup.as_dict(), status=status.HTTP_409_CONFLICT)
        except IntegrityError as e:
            # 兩個人同時建同名商品(或同一個請求被重送):兩邊都通過「品名沒人用」
            # 的檢查,後到的在寫入時撞唯一鍵。資料庫已經擋住重複,這裡只是把
            # 500 翻成看得懂的回應。
            if "uniq_product_tenant_name" in str(e):
                return Response(
                    {"detail": "有人剛建立了同名商品,請重新搜尋後再確認"},
                    status=status.HTTP_409_CONFLICT,
                )
            raise

    def perform_create(self, serializer):
        product = serializer.save(tenant=self.request.tenant)
        # 照片跟商品同一個交易:商品建好、照片掛上、主圖定好,一次成立
        apply_to_product(product, self._photos_payload(), self.request.user, created=True)

    def perform_update(self, serializer):
        product = serializer.save()
        apply_to_product(product, self._photos_payload(), self.request.user)
        # 這一筆是存檔前查出來的,上面帶的「幾張照片、主圖是哪一張」是舊的:拿掉,回應改用現查的
        for stale in ("photo_count_n", "primary_photo_id"):
            product.__dict__.pop(stale, None)

    def update(self, request, *args, **kwargs):
        # 改品名 / 條碼也過防重複關卡:不然可以先用無關的名字建檔,
        # 再改成跟別的商品一樣,整道關卡就被繞過了。
        try:
            with transaction.atomic():
                return super().update(request, *args, **kwargs)
        except PhotoRuleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except DuplicateProduct as dup:
            return Response(dup.as_dict(), status=status.HTTP_409_CONFLICT)
        except IntegrityError as e:
            if "uniq_product_tenant_name" in str(e):
                return Response(
                    {"detail": "已經有同名的商品"}, status=status.HTTP_409_CONFLICT
                )
            raise

    @action(detail=False, methods=["get"], url_path="resolve")
    def resolve(self, request):
        """一句叫法 → 可能是它的既有商品(進貨搜尋、新增前防重複共用)。

        跟 `?search=` 的差別:
        - 零庫存與**已停用**的都會列出來(零庫存不代表沒建檔)。
        - 每筆附「符合原因」與「差異」,讓人判斷是不是同一款。
        - `status` 只有在條碼 / 廠商料號 / 已確認別名 / 品號命中單一商品時
          才是 `existing`;特徵再像也只是 `candidates`,由人選。

        參數:q、supplier、barcode、vendor_sku、warehouse、is_secondhand、limit
        """
        params = request.query_params
        tenant = request.tenant
        supplier = None
        if params.get("supplier", "").isdigit():
            supplier = Supplier.objects.for_tenant(tenant).filter(
                id=int(params["supplier"])
            ).first()
        secondhand = {"true": True, "false": False}.get(params.get("is_secondhand", ""))
        try:
            limit = max(1, min(int(params.get("limit", 20)), 50))
        except ValueError:
            limit = 20
        found = find_candidates(
            tenant, params.get("q", ""), supplier=supplier,
            barcode=params.get("barcode", ""), vendor_sku=params.get("vendor_sku", ""),
            is_secondhand=secondhand, limit=limit,
        )
        # 鎖倉帳號的「本店庫存」一律算自己那一倉,不能靠帶別的 warehouse 參數
        # 去看他店庫存 —— 防重複搜尋不放寬鎖倉權限。
        profile = getattr(request.user, "profile", None)
        if profile and profile.is_warehouse_locked:
            # 鎖倉但沒設門市的帳號:不能因此就採信它帶來的 warehouse 參數。
            # 給一個不存在的倉 → 庫存一律顯示 0。
            self._warehouse_override = str(profile.default_warehouse_id or 0)
        products = {
            p.id: p for p in self.get_queryset().filter(pk__in=found.product_ids)
        }
        admin = is_tenant_admin(request.user)
        ctx = self.get_serializer_context()
        rows = []
        for c in found.candidates:
            p = products.get(c.product_id)
            if p is None:
                continue
            rows.append({
                "product": ProductSerializer(p, context=ctx).data,
                "level": c.level,
                "score": c.score,
                "reasons": c.reasons,
                "differences": c.differences,
                "conflict": c.conflict,
                "is_active": p.is_active,
                # 已停用的看得到但不能直接選;要先由管理員恢復
                "selectable": p.is_active,
                "can_restore": admin and not p.is_active,
            })
        status_out = found.status if rows else MatchResult.NONE
        return Response({"status": status_out, "candidates": rows})

    @action(detail=True, methods=["get"], url_path="usage")
    def usage(self, request, pk=None):
        """這個商品用過沒有(編輯表單打開時問):用過的話「需追蹤序號 / 中古機 / 虛擬商品」不能改。

        回 `{locked, reasons, fields, way_out}`;規則在 `catalog/usage.py`,存檔時伺服器會再擋一次。
        """
        from .usage import STOCK_FLAGS, product_usage

        found = product_usage(self.get_object())
        return Response({
            "locked": found.locked,
            "reasons": list(found.reasons),
            "fields": list(STOCK_FLAGS),
            "way_out": found.way_out if found.locked else "",
        })

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        """恢復已停用的商品(限公司管理員)。"""
        if not is_tenant_admin(request.user):
            return Response(
                {"detail": "恢復已停用的商品需要管理員權限"},
                status=status.HTTP_403_FORBIDDEN,
            )
        product = self.get_object()
        if not product.is_active:
            product.is_active = True
            product.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(self.get_queryset().get(pk=product.pk)).data)

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
        for p in qs.select_related("brand", "series", "phone_model"):
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

    @action(detail=False, methods=["get"], url_path="by-phone-model")
    def by_phone_model(self, request):
        """展開某個機型底下的所有 SKU,按品況(全新 / 已拆封 / 中古)分組。

        給「機型分組展開」用:機型清單一列,點開用這支載入底下 SKU,
        全新 / 中古並排,型錄不翻倍。以 model_key 比對(跨全新中古同一機型)。

        Query:
        - model_key:機型 key(必);對 Product.phone_model_key
        - warehouse_ids:逗號分隔倉 ID;空 → 該租戶所有 active 倉
        """
        tenant = request.tenant
        key = (request.query_params.get("model_key") or "").strip().lower()
        if not key:
            return Response({"detail": "缺 model_key"}, status=status.HTTP_400_BAD_REQUEST)

        raw_ids = request.query_params.get("warehouse_ids", "")
        wids = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]
        if not wids:
            wids = list(
                Warehouse.objects.for_tenant(tenant)
                .filter(is_active=True).values_list("id", flat=True)
            )

        # 撈主機 SKU,client 端已有機型欄位;這裡以 phone_model_key 比對
        cands = (
            Product.objects.for_tenant(tenant)
            .filter(accessory_type=Product.AccessoryType.NONE, is_active=True)
            .select_related("category", "condition", "series", "phone_model")
        )
        rows = [p for p in cands if p.phone_model_key == key]
        pids = [p.id for p in rows]

        serial_map = {}
        for d in (
            ProductSerial.objects.filter(
                tenant=tenant, product_id__in=pids, warehouse_id__in=wids,
                status=ProductSerial.Status.IN_STOCK,
            ).values("product_id").annotate(c=Count("id"))
        ):
            serial_map[d["product_id"]] = d["c"]
        balance_map = {}
        for d in (
            StockBalance.objects.filter(
                tenant=tenant, product_id__in=pids, warehouse_id__in=wids,
            ).values("product_id").annotate(s=Sum("qty"))
        ):
            balance_map[d["product_id"]] = d["s"] or 0

        # 依品況分組。sort_order 讓「全新 → 已拆封 → 中古」有固定順序。
        groups = {}
        for p in rows:
            cname = p.condition.name if p.condition else ("中古機" if p.is_secondhand else "全新")
            corder = p.condition.sort_order if p.condition else (99 if p.is_secondhand else 0)
            g = groups.setdefault(cname, {"condition": cname, "sort": corder,
                                          "is_secondhand": p.is_secondhand, "skus": []})
            g["skus"].append({
                "id": p.id, "sku": p.sku, "name": p.name,
                "capacity": p.capacity, "color": p.color,
                "region_version": p.region_version,
                "list_price": str(p.list_price),
                "stock_qty": serial_map.get(p.id, 0) + balance_map.get(p.id, 0),
            })
        for g in groups.values():
            g["skus"].sort(key=lambda s: (s["capacity"], s["color"]))
        return Response(sorted(groups.values(), key=lambda g: g["sort"]))

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
                .select_related("phone_model", "series")
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
            .select_related("category", "series", "phone_model")
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

    @action(detail=False, methods=["get"], url_path="trending")
    def trending(self, request):
        """銷售趨勢推送:回溫(trend_ratio>=1.2)/ 退燒(trend_ratio<=0.5)兩類。

        資料由 manage.py compute_dynamic_stock 每晚算好寫進 Product 欄位,
        這個 endpoint 只是取 + 分類。
        """
        limit = int(request.query_params.get("limit", 10))
        data = insights_trending(request.tenant, limit=limit)
        return Response(data)

    # 店裡的寫法只拿來對「描述」:品名 / 規格 / 類別。品號、條碼是整串在比的碼(上面照字面那一條會比),
    # 拆成一個字一個字去對的話,「iphone 17」的 17 會對到每一個條碼裡有 17 的 iPhone。
    SHOP_WORDING_FIELDS = ("name", "spec", "category__name")

    def _shop_wording(self, search):
        """一個字一個字比,每個字都要在品名 / 規格 / 類別裡對得上;每個字可以是店裡的另一種寫法。

        `IP17 256 黑`、`iphone 17 pro max`(= IP17PM)、`S25 ultra`(= S25U)、`16 plus`(= 16+)、`三星`(= SAM)。
        語彙表與每個字的比法在 `shop_terms.py`。
        """
        every_word = Q()
        for pattern in shop_terms.word_patterns(search):
            somewhere = Q()
            for field in self.SHOP_WORDING_FIELDS:
                # 分大小寫的比對:大小寫已經寫在比對式裡(shop_terms._portable),不靠資料庫的「不分大小寫」
                somewhere |= Q(**{f"{field}__regex": pattern})
            every_word &= somewhere
        # 沒有可以用的字(空的、太長、字太多)時是空的條件:接在別的條件後面等於沒接
        return every_word

    @action(detail=False, methods=["get"], url_path="stock-matrix")
    def stock_matrix(self, request):
        """庫存矩陣:每個商品在多個指定倉的庫存,給庫存查詢頁用。

        Query params:
        - warehouse_ids:逗號分隔的倉 ID;空白 → 該 tenant 所有 active 倉
        - search:關鍵字。整串照字面(sku/name/spec/barcode/category、設備的碼),
          加上一個字一個字比、每個字可以是店裡的另一種寫法(`_shop_wording`),再加上共用比對
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
            .select_related("category", "condition", "series", "phone_model")
            .filter(is_active=True)
        )
        # 空字元資料庫不收(整個查詢會出錯);商品清單那邊的搜尋也是先拿掉
        search = request.query_params.get("search", "").replace("\x00", "").strip()
        if search:
            cond = (
                Q(sku__icontains=search)
                | Q(name__icontains=search)
                | Q(spec__icontains=search)
                | Q(barcode__icontains=search)
                | Q(category__name__icontains=search)
                | Q(category__code__icontains=search)
                # 刷到的是某一台設備的碼(IMEI 或 SN,完全相同)→ 那一台的商品
                | Q(pk__in=ProductSerial.objects.filter(
                    pk__in=find_serial_ids(tenant, search)).values("product_id"))
            )
            # 純數字 6 碼以上:也比對碼的一部分(只記得 IMEI 末幾碼時);
            # 太短或有英文字的不比,免得「18 pro 256」這種字誤中別台的碼
            if search.isdigit() and len(search) >= 6:
                cond |= Q(pk__in=ProductSerialIdentifier.objects.filter(
                    tenant=tenant, normalized_value__contains=search,
                ).values("serial__product_id"))
            # 上面是原本的(整串字照字面),下面兩種是多的:只會多找到,不會少找到。
            cond |= self._shop_wording(search)
            # 跟商品清單同一套共用比對:用「其他叫法」叫的、寫法不同的(reno-16 / reno16)。只收每一項都對得上的。
            cond |= Q(pk__in=find_candidates(tenant, search, limit=200, with_related=False).product_ids)
            qs = qs.filter(cond)
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

        # 3. 在庫數與「有沒有貨」都在 DB 端算完,再分頁。
        #    舊版先切前 500 筆再濾零庫存,超過 500 個商品時第 501 筆以後
        #    的在庫商品會被靜默漏掉。型號精靈會依 狀態 x 容量 x 顏色 爆出
        #    大量 SKU,這個上限很快就會踩到。
        serial_qty_sub = (
            ProductSerial.objects.filter(
                tenant=tenant,
                product=OuterRef("pk"),
                warehouse_id__in=warehouse_ids,
                status=ProductSerial.Status.IN_STOCK,
            )
            .values("product")
            .annotate(c=Count("id"))
            .values("c")[:1]
        )
        balance_qty_sub = (
            StockBalance.objects.filter(
                tenant=tenant,
                product=OuterRef("pk"),
                warehouse_id__in=warehouse_ids,
            )
            .values("product")
            .annotate(s=Sum("qty"))
            .values("s")[:1]
        )
        qs = qs.annotate(
            serial_qty=Coalesce(
                Subquery(serial_qty_sub, output_field=IntegerField()), Value(0)
            ),
            balance_qty=Coalesce(
                Subquery(balance_qty_sub, output_field=IntegerField()), Value(0)
            ),
        ).annotate(stock_total_agg=F("serial_qty") + F("balance_qty"))

        # 虛擬商品(手續費等)沒有實體庫存,不列入庫存表
        qs = qs.exclude(is_virtual=True)
        in_stock_only = request.query_params.get("in_stock_only", "true") == "true"
        if in_stock_only:
            qs = qs.exclude(stock_total_agg=0)

        qs = qs.order_by("category__sort_order", "category__code", "sku")

        # 4. 分頁(預設 500 筆一頁,沿用舊行為的單頁大小)
        total = qs.count()
        try:
            page_size = int(request.query_params.get("page_size", 500))
        except (TypeError, ValueError):
            page_size = 500
        page_size = max(1, min(page_size, 1000))
        page_count = max(1, -(-total // page_size))  # ceil
        try:
            page = int(request.query_params.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        # 夾在有效範圍內。不夾的話超大頁碼會讓 OFFSET 超出 PostgreSQL bigint
        # 而丟 DataError(HTTP 500);夾住之後最壞情況只是回最後一頁。
        page = max(1, min(page, page_count))
        offset = (page - 1) * page_size
        products = list(qs[offset:offset + page_size])
        product_ids = [p.id for p in products]

        # 5. 批次抓「序號商品」每倉的在庫數
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

        # 6. 批次抓「配件」每倉 balance
        balance_data = StockBalance.objects.filter(
            tenant=tenant,
            product_id__in=product_ids,
            warehouse_id__in=warehouse_ids,
        ).values("product_id", "warehouse_id", "qty")
        balance_map = {
            (d["product_id"], d["warehouse_id"]): d["qty"] for d in balance_data
        }

        # 6.5 這一頁商品的主圖(庫存查詢點品名看照片;有照片的那一列多一個小縮圖)
        primary_photo = dict(
            ProductPhoto.objects.filter(product_id__in=product_ids, is_primary=True)
            .values_list("product_id", "pk")
        )

        # 7. 組裝。過濾已在 DB 端做完,這裡只負責攤成每倉欄位。
        products_data = []
        for p in products:
            stock_by_wh = {}
            for wid in warehouse_ids:
                qty = serial_map.get((p.id, wid), 0) + balance_map.get(
                    (p.id, wid), 0
                )
                stock_by_wh[str(wid)] = qty
            products_data.append(
                {
                    "id": p.id,
                    "sku": p.sku,
                    "name": p.name,
                    "spec": p.spec,
                    "capacity": p.capacity,
                    "color": p.color,
                    "region_version": p.region_version,
                    "condition_id": p.condition_id,
                    "condition_name": p.condition.name if p.condition else "",
                    "tracks_unit_condition": p.tracks_unit_condition,
                    "phone_model_key": p.phone_model_key,
                    "phone_model_name": p.phone_model_name,
                    "category_id": p.category_id,
                    "category_name": p.category.name if p.category else "",
                    "category_code": p.category.code if p.category else "",
                    "list_price": str(p.list_price),
                    "weighted_avg_cost": str(p.weighted_avg_cost),
                    "requires_serial": p.requires_serial,
                    "is_secondhand": p.is_secondhand,
                    "stock_by_warehouse": stock_by_wh,
                    "stock_total": sum(stock_by_wh.values()),
                    "photo_thumb": (
                        photo_urls("p", primary_photo[p.id])["thumb_url"]
                        if p.id in primary_photo else ""
                    ),
                }
            )

        return Response(
            {
                "warehouses": warehouses,
                "products": products_data,
                "total": total,
                "page": page,
                "page_size": page_size,
                "page_count": page_count,
                "has_more": offset + len(products) < total,
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
        from .usage import lock_category

        updated_ids: list[int] = []
        errors: list[dict] = []
        try:
            with transaction.atomic():
                # 鎖的順序固定(跟類別連帶改商品、進貨鎖商品同一個方向):先類別、後商品,商品照編號。
                # 要換類別的話,動任何商品之前先拿好那個類別的鎖;改到一半才拿,會跟正在把它勾成中古機類別的人互等
                target = _own_category_id(request.tenant, patch.get("category"))
                if target is not None:
                    lock_category(target)
                for p in qs.order_by("pk"):
                    ser = ProductSerializer(
                        p,
                        data=patch,
                        partial=True,
                        context={"request": request},
                    )
                    if ser.is_valid():
                        try:
                            with transaction.atomic():
                                ser.save()
                        except DuplicateProduct as dup:
                            # 例:把同一個條碼批次套到好幾個商品上
                            errors.append(
                                {"id": p.id, "name": p.name, "errors": dup.message}
                            )
                            continue
                        except DRFValidationError as blocked:
                            # 例:用過的商品不能批次改「需追蹤序號 / 中古機 / 虛擬商品」(存檔那一刻才知道)
                            errors.append(
                                {"id": p.id, "name": p.name, "errors": blocked.detail}
                            )
                            continue
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

    @action(detail=False, methods=["post"], url_path="create-phone-model")
    def create_phone_model(self, request):
        """新增手機型號 — 一次建好「狀態 × 容量 × 顏色」主機 SKU + 配件 placeholder + 維修零件 SKU。

        Payload(JSON):
            brand_id          (必)
            series_id         (選)
            generation        (選,int)
            model_suffix      (選,例 "Pro" / "Pro Max")
            main_category_id  (必,主機要掛的類別)
            list_price        (選,主機售價,字串數字)
            condition_ids     (必,要建哪些狀態 — Condition.id list)
            capacities        (必,容量字串 list,例 ["128GB","256GB"])
            colors            (必,顏色字串 list)
            region_version    (選,地區版本,例 "台版";整批一個值,不是維度)
            accessory_categories (選,配件類別字串 list,例 ["殼","貼"])
            accessory_category_id (選,配件 SKU 掛的類別,空白沿用 main_category_id)
            parts_category_id    (選,零件 SKU 掛的類別,空白沿用 main_category_id)
            template_id          (選,PartTemplate id,沒指定就只建主機 SKU)
            parts_items          (選,覆寫範本零件清單)
            dry_run              (bool,預設 false;true 只回預覽不寫 DB)

        回傳:
            { model_name, model_key, main_count, accessory_count, parts_count,
              main: [...], accessories: [...], parts: [...] }
        """
        payload = request.data or {}
        dry_run = str(payload.get("dry_run", "false")).lower() in ("true", "1", "yes")
        try:
            if dry_run:
                result = preview_phone_model_bundle(request.tenant, payload)
            else:
                result = create_phone_model_bundle(
                    request.tenant, payload, user=request.user
                )
        except DuplicateProduct as dup:
            return Response(dup.as_dict(), status=status.HTTP_409_CONFLICT)
        except ValueError as e:
            return Response(
                {"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        except IntegrityError as e:
            # service 內已先查過品名有沒有撞,但兩個人同時按「建立全部」時,
            # 兩邊都會通過檢查、其中一邊在 save() 撞唯一鍵。整批已經回滾,
            # 這裡翻成 409 讓前端顯示「有人剛建過了,重新整理再看一次」。
            if "uniq_product_tenant_name" in str(e) or "uniq_product_tenant_sku" in str(e):
                return Response(
                    {"detail": "有人剛建立了同名商品,請重新整理後再確認一次"},
                    status=status.HTTP_409_CONFLICT,
                )
            raise
        return Response(result)

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
        has_duplicate = False
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
                        try:
                            # savepoint:被擋下的那一列不影響同批其他列繼續檢查
                            with transaction.atomic():
                                instance = serializer.save(tenant=tenant)
                        except DuplicateProduct as dup:
                            # 每一列各自說明;不能整批一次按「不同款」
                            has_duplicate = True
                            errors.append({
                                "line": idx, "name": payload.get("name", ""),
                                "errors": dup.message, "duplicate": dup.as_dict(),
                            })
                            continue
                        except IntegrityError as e:
                            # 有人同時建了同名的商品:資料庫擋住了,這裡回看得懂的錯
                            if "uniq_product_tenant_name" not in str(e):
                                raise
                            has_duplicate = True
                            errors.append({
                                "line": idx, "name": payload.get("name", ""),
                                "errors": "有人剛建立了同名商品,請重新確認",
                            })
                            continue
                        created.append(ProductSerializer(instance).data)
                    else:
                        errors.append({"line": idx, "errors": serializer.errors})
                if errors:
                    raise ValueError("validation_failed")
        except ValueError:
            return Response(
                {"detail": "部分品項失敗,已全部復原", "errors": errors},
                status=(
                    status.HTTP_409_CONFLICT if has_duplicate
                    else status.HTTP_400_BAD_REQUEST
                ),
            )
        return Response(
            {"created": created, "count": len(created)},
            status=status.HTTP_201_CREATED,
        )


class BrandViewSet(viewsets.ModelViewSet):
    """品牌主檔 CRUD(per-tenant)。

    經銷商可自行新增 / 編輯 / 刪除自家的品牌與系列;
    但「批次匯入(CSV / Excel)」鎖給 platform_admin —
    由平台端統一維護市面品牌字典,確保資料一致。
    """

    serializer_class = BrandSerializer
    search_fields = ["code", "name"]
    ordering_fields = ["sort_order", "code", "name"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active"]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.action == "import_csv":
            return [IsAuthenticated(), IsPlatformAdmin()]
        return super().get_permissions()

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

    用 ?brand=<id> 過濾單一品牌的系列;
    ?product_type=<id> 篩單一類型(手機 / 平板 / 耳機 …)。
    """

    serializer_class = PhoneSeriesSerializer
    search_fields = ["code", "name"]
    ordering_fields = ["sort_order", "code", "name"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active", "brand", "product_type"]

    def get_queryset(self):
        return PhoneSeries.objects.for_tenant(
            self.request.tenant
        ).select_related("brand", "product_type")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ConditionViewSet(viewsets.ModelViewSet):
    """商品狀態主檔 CRUD(per-tenant)。

    用於建手機型號 wizard 的「狀態」維度:全新 / 已拆封 / 中古機(保固內)/ 中古機。
    Migration 自動 seed 4 個預設值,經銷商可自行增刪改。
    """

    serializer_class = ConditionSerializer
    search_fields = ["code", "name"]
    ordering_fields = ["sort_order", "code", "name"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active", "is_secondhand"]

    def get_queryset(self):
        return (
            Condition.objects.for_tenant(self.request.tenant)
            .annotate(product_count=Count("products"))
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ProductTypeViewSet(viewsets.ModelViewSet):
    """產品類型主檔 CRUD(per-tenant)。

    經銷商可自訂類型(手機 / 平板 / 耳機 / 手錶 / 智慧家電 …),
    系列建立時可指定屬於哪個類型。
    """

    serializer_class = ProductTypeSerializer
    search_fields = ["code", "name"]
    ordering_fields = ["sort_order", "code", "name"]
    ordering = ["sort_order", "code"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        return (
            ProductType.objects.for_tenant(self.request.tenant)
            .annotate(series_count=Count("series"))
        )

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
        result = bulk_create_parts(request.tenant, category_id, rows, user=request.user)
        return Response(result)
