from rest_framework import serializers

from apps.core import staff_cost
from apps.core.manager_fields import ManagerOnlyFieldsMixin
from apps.core.tenant_fields import TenantScopedRelatedFieldsMixin
from rest_framework.exceptions import PermissionDenied

from .models import (
    Brand,
    Category,
    Condition,
    PartTemplate,
    PartTemplateItem,
    PhoneModel,
    PhoneSeries,
    Product,
    ProductRelation,
    ProductType,
)


class BrandSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    """中文 / 英文兩格選填、至少一格(owner 2026-10-17);只送 `name` 的(舊的呼叫端)照 `brand_names.split` 拆。
    跟別的品牌的中文、英文、顯示名稱撞到的不給存(同一個廠牌請用合併)。代碼沒給就自動產。"""

    series_count = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    code = serializers.SlugField(max_length=20, required=False, allow_blank=True)

    def validate(self, attrs):
        from . import brand_names

        attrs = super().validate(attrs)
        inst = self.instance
        if "name_zh" in attrs or "name_en" in attrs:
            zh = brand_names.tidy(attrs.get("name_zh", inst.name_zh if inst else ""))
            en = brand_names.tidy(attrs.get("name_en", inst.name_en if inst else ""))
        elif "name" in attrs:
            zh, en = brand_names.split(attrs["name"])
        elif inst is not None:
            return attrs                          # 只改排序 / 啟用:名字不動,不重新檢查
        else:
            zh = en = ""
        if not (zh or en):
            raise serializers.ValidationError({"name_zh": "中文、英文至少填一個"})
        if inst is not None and (zh, en) == (inst.name_zh, inst.name_en):
            attrs.pop("name_zh", None), attrs.pop("name_en", None), attrs.pop("name", None)
            return attrs                          # 畫面連沒改的名字一起送(只改排序 / 啟用):不重新檢查(複審 P2)
        if len(brand_names.join(zh, en)) > Brand._meta.get_field("name").max_length:
            raise serializers.ValidationError({"name_en": "中文加英文太長"})
        if inst is not None and inst.name_en and not en and (inst.series.exists() or inst.phone_models.exists()):
            # 型號庫(每天自動新增新機)照英文找這家店的品牌;拿掉英文會多建一個,同一支手機拆兩邊
            raise serializers.ValidationError({"name_en": "手機品牌要留英文名稱"})
        tenant = self.context["request"].tenant
        for text in (brand_names.join(zh, en), zh, en):
            other = brand_names.find_brand(tenant, text, exclude_id=inst.pk if inst else None) if text else None
            if other is not None:
                raise serializers.ValidationError(
                    {"name_zh" if text == zh else "name_en": f"「{text}」已經是品牌「{other.name}」,同一個廠牌請用合併"})
        attrs["name_zh"], attrs["name_en"], attrs["name"] = zh, en, brand_names.join(zh, en)
        if inst is None and not (attrs.get("code") or "").strip():
            attrs["code"] = brand_names.unique_code(tenant, en or zh)
        return attrs

    class Meta:
        model = Brand
        fields = [
            "id",
            "code",
            "name",
            "name_zh",
            "name_en",
            "sort_order",
            "is_active",
            "series_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "series_count", "created_at", "updated_at"]


class ConditionSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    product_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Condition
        fields = [
            "id",
            "code",
            "name",
            "is_secondhand",
            "tracks_unit_condition",
            "sort_order",
            "is_active",
            "product_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "product_count", "created_at", "updated_at"]


class ProductTypeSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    series_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProductType
        fields = [
            "id",
            "code",
            "name",
            "sort_order",
            "is_active",
            "series_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "series_count", "created_at", "updated_at"]


class PhoneSeriesSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    brand_code = serializers.CharField(source="brand.code", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    product_type_code = serializers.CharField(
        source="product_type.code", read_only=True, default=""
    )
    product_type_name = serializers.CharField(
        source="product_type.name", read_only=True, default=""
    )

    class Meta:
        model = PhoneSeries
        fields = [
            "id",
            "brand",
            "brand_code",
            "brand_name",
            "product_type",
            "product_type_code",
            "product_type_name",
            "code",
            "name",
            "sort_order",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "brand_code",
            "brand_name",
            "product_type_code",
            "product_type_name",
            "created_at",
            "updated_at",
        ]


class PartTemplateItemSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = PartTemplateItem
        fields = [
            "id",
            "name",
            "code",
            "sort_order",
            "default_cost",
            "default_safety_stock",
            "shared_across_models",
        ]


class PartTemplateSerializer(TenantScopedRelatedFieldsMixin, serializers.ModelSerializer):
    items = PartTemplateItemSerializer(many=True, read_only=True)
    items_input = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True
    )

    class Meta:
        model = PartTemplate
        fields = [
            "id",
            "name",
            "note",
            "is_active",
            "default_capacities",
            "default_colors",
            "default_accessory_categories",
            "default_accessory_brands",
            "items",
            "items_input",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "items", "created_at", "updated_at"]

    def create(self, validated_data):
        items = validated_data.pop("items_input", None) or []
        instance = super().create(validated_data)
        self._sync_items(instance, items)
        return instance

    def update(self, instance, validated_data):
        items = validated_data.pop("items_input", None)
        instance = super().update(instance, validated_data)
        if items is not None:
            self._sync_items(instance, items)
        return instance

    def _sync_items(self, template, items):
        existing = {it.id: it for it in template.items.all()}
        seen = set()
        for idx, row in enumerate(items):
            item_id = row.get("id")
            if item_id and item_id in existing:
                it = existing[item_id]
                it.name = row.get("name", it.name)
                it.code = row.get("code", it.code)
                it.sort_order = row.get("sort_order", idx)
                it.default_cost = row.get("default_cost", it.default_cost)
                it.default_safety_stock = row.get(
                    "default_safety_stock", it.default_safety_stock
                )
                it.shared_across_models = bool(
                    row.get("shared_across_models", it.shared_across_models)
                )
                it.save()
                seen.add(item_id)
            else:
                PartTemplateItem.objects.create(
                    tenant=template.tenant,
                    template=template,
                    name=row.get("name", ""),
                    code=row.get("code", ""),
                    sort_order=row.get("sort_order", idx),
                    default_cost=row.get("default_cost", 0),
                    default_safety_stock=row.get("default_safety_stock", 0),
                    shared_across_models=bool(
                        row.get("shared_across_models", False)
                    ),
                )
        for itid, it in existing.items():
            if itid not in seen:
                it.delete()


class _TenantUniqueMixin:
    """檢查 per-tenant 唯一性的小 helper。"""

    def _tenant_unique(self, queryset, field_name: str, value):
        request = self.context.get("request")
        if request is None:
            return value
        qs = queryset.for_tenant(request.tenant).filter(**{field_name: value})
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("已存在相同值")
        return value


class CategorySerializer(TenantScopedRelatedFieldsMixin, _TenantUniqueMixin, serializers.ModelSerializer):
    # 三種走法(主機 / 配件 / 一般);寫的時候換成 holds_devices + needs_host_model。新增類別一定要選(紅隊第 3 條)
    kind = serializers.ChoiceField(choices=Category.Kind.choices, required=False)
    # 類別底下的品牌(中項),照排序
    brands = serializers.SerializerMethodField()
    # 配件共用實際跟著哪一個("screen" / "body" / "";shares_by 空的時候照名稱判斷,規則在 device_share.part_of)
    shares_part = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            "id",
            "code",
            "name",
            "sort_order",
            "is_active",
            "is_secondhand_default",
            "needs_host_model",
            "holds_devices",
            "kind",
            "brands",
            "shares_by",
            "shares_part",
            "next_sku_seq",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "needs_host_model", "holds_devices", "next_sku_seq", "created_at", "updated_at"]

    def get_shares_part(self, obj) -> str:
        from .device_share import part_of

        return part_of(obj)

    def get_brands(self, obj) -> list:
        return [{"id": link.brand_id, "name": link.brand.name}
                for link in obj.brand_links.select_related("brand").order_by("sort_order", "id")]

    def validate(self, attrs):
        from .category_template import flags_of

        kind = attrs.pop("kind", None)
        if kind:
            attrs.update(flags_of(kind))
        elif self.instance is None:
            raise serializers.ValidationError({"detail": "要選這個類別是主機、配件還是一般"})
        return super().validate(attrs)

    def validate_code(self, value):
        return self._tenant_unique(Category.objects, "code", value)

    def validate_name(self, value):
        return self._tenant_unique(Category.objects, "name", value)

    def update(self, instance, validated_data):
        from .usage import StockFlagsLocked

        try:
            return super().update(instance, validated_data)
        except StockFlagsLocked as locked:
            # 勾「中古機類別」會把底下所有商品一起改成中古機:底下有用過的商品就不能勾(規則見 `catalog/usage.py`)。
            # 檢查只有模型存檔那一份(`Category.save`:鎖著這個類別做完檢查、存、連動);這裡只負責講成 400。
            # 放在 detail:畫面的錯誤訊息只認這一格(放在欄位名底下會顯示成「400 Bad Request」)
            raise serializers.ValidationError({"detail": str(locked)}) from locked


class ProductSerializer(ManagerOnlyFieldsMixin, TenantScopedRelatedFieldsMixin, _TenantUniqueMixin, serializers.ModelSerializer):
    # 業務員成本怎麼算是績效的基準:只有管理員拿得到設定、改得動;算出來的數字(staff_cost)大家都看得到
    manager_only_fields = ("staff_cost_mode", "staff_cost_value")
    # 一件的業務員成本(照現在的平均成本與規則算;沒有規則 = 平均成本)。成交時記在單上的以那一刻為準
    staff_cost = serializers.SerializerMethodField()
    stock_qty = serializers.IntegerField(read_only=True)
    category_code = serializers.CharField(source="category.code", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    # Brand / Series 顯示用(read-only label)
    brand_code = serializers.CharField(source="brand.code", read_only=True, default="")
    brand_name = serializers.CharField(source="brand.name", read_only=True, default="")
    series_name = serializers.CharField(source="series.name", read_only=True, default="")
    phone_model_name = serializers.CharField(read_only=True)
    phone_model_key = serializers.CharField(read_only=True)
    telecom_carrier_name = serializers.CharField(source="telecom_carrier.name", read_only=True, default="")
    # 品況(全新 / 已拆封 / 中古機 …)。is_secondhand 只是非黑即白,
    # 分不出「全新」跟「已拆封」,前端要靠 condition 才認得出來。
    condition_name = serializers.CharField(
        source="condition.name", read_only=True, default=""
    )
    condition_code = serializers.CharField(
        source="condition.code", read_only=True, default=""
    )
    # 進貨畫面要不要開「成色 / 電池 / 售價 / 備註」那幾欄
    tracks_unit_condition = serializers.BooleanField(read_only=True)
    # 商品照片:有幾張、主圖的縮圖網址(清單、搜尋結果、開單明細用來顯示「有照片」與小縮圖)
    photo_count = serializers.SerializerMethodField()
    photo_thumb = serializers.SerializerMethodField()
    last_purchase_price = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, allow_null=True
    )
    # (舊)配件 → 主機 id 清單;保留作向後相容,新前端請改用 related_host_keys
    related_host_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
        help_text="(deprecated)請用 related_host_keys 改以機型 key 為單位",
    )
    # 防重複關卡說「可能相同」時,要寫下哪裡不同才能建(見 identity/dedup.py)
    distinct_reason = serializers.CharField(
        required=False, allow_blank=True, write_only=True, max_length=200,
    )
    # (新)配件 → 機型 key 清單,以機型為單位涵蓋該款所有 SKU 變體
    related_host_keys = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        write_only=True,
        help_text="配件相容的機型 key 清單",
    )

    def get_staff_cost(self, obj) -> str:
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) or obj.tenant
        return str(staff_cost.shown_unit_cost(obj, tenant))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        self._check_telecom_carrier(attrs)
        if "staff_cost_mode" in attrs or "staff_cost_value" in attrs:
            # 帶序號的商品先不做業務員成本(owner 2026-10-10):送來的設定不留(批次修改勾到手機時不擋、也不存)
            # 「存檔之後帶不帶序號」跟 Product.save 用同一份算法(放進中古機類別的商品會被連帶改成帶序號)
            from .usage import flags_after_save

            def after(name, default):
                return attrs.get(name, getattr(self.instance, name, default))

            category = after("category", None)
            serial = flags_after_save(
                category_secondhand=bool(category is not None and category.is_secondhand_default),
                is_secondhand=after("is_secondhand", False),
                requires_serial=after("requires_serial", True),
                is_virtual=after("is_virtual", False),
            )["requires_serial"]
            if serial and not staff_cost.SERIAL_GOODS_TOO:
                attrs["staff_cost_mode"], attrs["staff_cost_value"] = "", 0
                return attrs
            mode = attrs.get("staff_cost_mode", getattr(self.instance, "staff_cost_mode", ""))
            if "staff_cost_mode" in attrs:
                # 換算法的時候數字要一起送(畫面一定一起送);沒送不沿用原本的
                value = attrs.get("staff_cost_value")
            else:
                value = attrs["staff_cost_value"]
            problem = staff_cost.check(mode, value, staff_cost.PRODUCT_MODES)
            if problem:
                raise serializers.ValidationError({"detail": f"業務員成本{problem}"})
            if not mode:
                attrs["staff_cost_value"] = 0          # 照全公司:自己的數值不留
        return attrs

    def _check_telecom_carrier(self, attrs):
        """門號商品(虛擬 + 可綁門號)一定要選電信商;不能綁門號的不留電信商。
        改既有商品時只在動到這三格才檢查(以前建的門號商品還沒設,改別的欄位不擋;開單時另外擋)。"""
        keys = ("allows_telecom_line", "is_virtual", "telecom_carrier")
        if self.instance is not None and not any(k in attrs for k in keys):
            return

        def after(name, default):
            return attrs.get(name, getattr(self.instance, name, default) if self.instance else default)

        if not after("allows_telecom_line", False):
            if after("telecom_carrier", None) is not None:
                attrs["telecom_carrier"] = None
            return
        if after("is_virtual", False) and after("telecom_carrier", None) is None:
            raise serializers.ValidationError({"telecom_carrier": "門號商品要選電信商"})

    def get_photo_count(self, obj) -> int:
        # 清單查詢已經算好(photo_count_n);單筆(剛建好那一筆)才另外查
        n = getattr(obj, "photo_count_n", None)
        return n if n is not None else obj.photos.count()

    def get_photo_thumb(self, obj) -> str:
        from apps.photos.services import photo_urls

        if hasattr(obj, "primary_photo_id"):
            pid = obj.primary_photo_id
        else:
            pid = obj.photos.filter(is_primary=True).values_list("pk", flat=True).first()
        return photo_urls("p", pid)["thumb_url"] if pid else ""

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "spec",
            "barcode",
            "capacity",
            "color",
            "region_version",
            "style_code",
            "phone_model",
            "category",
            "category_code",
            "category_name",
            "weighted_avg_cost",
            "staff_cost",
            "staff_cost_mode",
            "staff_cost_value",
            "list_price",
            "last_purchase_price",
            "requires_serial",
            "allows_telecom_line",
            "telecom_carrier",
            "telecom_carrier_name",
            "allows_commission",
            "is_virtual",
            "is_secondhand",
            "counts_cash",
            "counts_margin",
            "safety_stock",
            "lifecycle_status",
            "accessory_type",
            "attach_rate",
            "replenish_days",
            "brand",
            "brand_code",
            "brand_name",
            "series",
            "series_name",
            "generation",
            "model_suffix",
            "phone_model_name",
            "phone_model_key",
            "condition",
            "condition_name",
            "condition_code",
            "tracks_unit_condition",
            "photo_count",
            "photo_thumb",
            "is_variant",
            "warehouse_type",
            "is_externally_sellable",
            "external_sale_price",
            "min_sale_price",
            "related_host_ids",
            "related_host_keys",
            "distinct_reason",
            "is_active",
            "stock_qty",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "sku",
            "weighted_avg_cost",
            "last_purchase_price",
            "stock_qty",
            "category_code",
            "category_name",
            # 品況先唯讀。改品況要走「逐台重分類」,不能直接改主檔把同 SKU
            # 的其他新機一起變成拆封機;那條流程另外做。
            "condition",
            "condition_name",
            "condition_code",
            "tracks_unit_condition",
            "style_code",
            "created_at",
            "updated_at",
        ]

    # 品名同名不在這裡擋:交給防重複關卡(identity/dedup.py),它會指出是哪一筆
    # 既有商品並回候選;資料庫的唯一約束仍然是最後一道。

    def validate_phone_model(self, value):
        """機型是 per-tenant 主檔,不能指到別的租戶的機型。

        DRF 的 ModelSerializer 預設會用 `PhoneModel.objects.all()` 當 queryset,
        不擋的話 API 可以把商品掛到別家的機型上。
        """
        request = self.context.get("request")
        if value is None or request is None:
            return value
        if value.tenant_id != request.tenant.id:
            raise serializers.ValidationError("找不到指定的機型")
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # 把目前關聯的「機型」也輸出(以 host_model_key 為單位 group)
        rels = list(
            instance.host_relations.select_related(
                "host_product", "host_product__phone_model", "host_product__series",
                "host_model",
            ).all()
        )
        seen: dict[str, dict] = {}
        for r in rels:
            key = r.host_model_key or (
                r.host_product.phone_model_key if r.host_product_id else ""
            )
            if not key or key in seen:
                continue
            host = r.host_product
            seen[key] = {
                "model_key": key,
                # 沒有代表商品的關係(掛在機型主檔上):用主檔的名稱,不要顯示成小寫的 key
                "model_name": (
                    host.phone_model_name if host
                    else r.host_model.name if r.host_model_id else key
                ),
                "sample_sku_id": host.id if host else None,
                "sample_sku_name": host.name if host else "",
                "lifecycle_status": host.lifecycle_status if host else "",
            }
        data["related_hosts"] = list(seen.values())
        return data

    def create(self, validated_data):
        from apps.identity.dedup import guard_new_product, record_distinct_decision

        host_keys = validated_data.pop("related_host_keys", None)
        host_ids = validated_data.pop("related_host_ids", None)
        reason = validated_data.pop("distinct_reason", "")
        # 所有走這個 serializer 的新增(單筆 / 批次 / 直接打 API)都過同一道關卡。
        # 擋下時丟 DuplicateProduct,由 view 轉成 409 + 候選。
        tenant = validated_data["tenant"]
        category = validated_data.get("category")
        similar = guard_new_product(
            tenant,
            name=validated_data.get("name", ""),
            spec=validated_data.get("spec", ""),
            color=validated_data.get("color", ""),
            capacity=validated_data.get("capacity", ""),
            barcode=validated_data.get("barcode", ""),
            is_secondhand=bool(
                validated_data.get("is_secondhand")
                or (category is not None and category.is_secondhand_default)
            ),
            distinct_reason=reason,
        )
        instance = super().create(validated_data)
        request = self.context.get("request")
        record_distinct_decision(
            tenant, instance, similar, reason, getattr(request, "user", None)
        )
        if host_keys is not None:
            self._sync_host_relations_by_keys(instance, host_keys)
        elif host_ids is not None:
            self._sync_host_relations_by_ids(instance, host_ids)
        return instance

    def update(self, instance, validated_data):
        # 恢復已停用的商品限公司管理員。停用後再啟用等於讓它重新出現在
        # 進貨 / 銷貨可選清單,不能由任何人順手勾回來。
        if validated_data.get("is_active") and not instance.is_active:
            from apps.tenants.permissions import is_tenant_admin

            request = self.context.get("request")
            if request is not None and not is_tenant_admin(request.user):
                raise PermissionDenied("恢復已停用的商品需要管理員權限")
        from apps.identity.dedup import guard_new_product, record_distinct_decision

        host_keys = validated_data.pop("related_host_keys", None)
        host_ids = validated_data.pop("related_host_ids", None)
        reason = validated_data.pop("distinct_reason", "")
        # 改到「這是哪個商品」的欄位才檢查(改售價、狀態不會多問)。
        # 自己不算;條碼只在有改條碼時查。
        new = lambda k: validated_data.get(k, getattr(instance, k))  # noqa: E731
        identity_changed = any(
            k in validated_data and validated_data[k] != getattr(instance, k)
            for k in ("name", "spec", "color", "capacity")
        )
        barcode_changed = (
            "barcode" in validated_data and validated_data["barcode"] != instance.barcode
        )
        similar = []
        if identity_changed or barcode_changed:
            similar = guard_new_product(
                instance.tenant,
                name=new("name") if identity_changed else "",
                spec=new("spec") if identity_changed else "",
                color=new("color") if identity_changed else "",
                capacity=new("capacity") if identity_changed else "",
                barcode=new("barcode") if barcode_changed else "",
                is_secondhand=bool(new("is_secondhand")),
                distinct_reason=reason,
                exclude_id=instance.id,
            )
        from .usage import StockFlagsLocked

        try:
            instance = super().update(instance, validated_data)
        except StockFlagsLocked as locked:
            # 用過的商品不能改「需追蹤序號 / 中古機 / 虛擬商品」(規則見 `catalog/usage.py`)。
            # 檢查只有模型存檔那一份(`Product.save`:鎖著類別、看類別現在的設定、比存檔之後實際的值,
            # 所以換到「中古機類別」連帶的變動也擋得到);這裡只負責把它講成 400 與一句話。
            # 放在 detail:畫面的錯誤訊息只認這一格
            raise serializers.ValidationError({"detail": str(locked)}) from locked
        request = self.context.get("request")
        record_distinct_decision(
            instance.tenant, instance, similar, reason, getattr(request, "user", None)
        )
        if host_keys is not None:
            self._sync_host_relations_by_keys(instance, host_keys)
        elif host_ids is not None:
            self._sync_host_relations_by_ids(instance, host_ids)
        return instance

    def _sync_host_relations_by_keys(self, accessory, host_keys):
        """同步配件 → 機型關聯(以 model_key 為單位,涵蓋該款所有 SKU 變體)。

        **先確認每一個新的機型都對得到東西,才動資料。** 對得到 = 有啟用中的主機商品(拿它當代表),
        或機型主檔裡有(關係直接掛在主檔上,不需要代表商品)。有對不到的就整筆退回、講是哪幾個 ——
        以前是先刪掉不在清單裡的舊關係、再把對不到的默默跳過、照樣回成功:批次「覆寫」會刪了舊的、新的又沒建。
        """
        tenant = accessory.tenant
        target_keys = {k.strip().lower() for k in host_keys if k and k.strip()}
        existing = {r.host_model_key: r for r in accessory.host_relations.all()}
        new_keys = target_keys - set(existing)
        if accessory.accessory_type == Product.AccessoryType.NONE and accessory.is_active:
            # 這個商品自己就是主機:不跟自己的機型建關係(照舊不建、也不算錯)
            new_keys.discard(accessory.phone_model_key)
        hosts, models = {}, {}
        if new_keys:
            # 代表 SKU:任一個啟用中的主機商品(只用來在畫面上舉例)
            for p in Product.objects.for_tenant(tenant).filter(
                accessory_type=Product.AccessoryType.NONE, is_active=True,
            ).exclude(pk=accessory.pk).select_related("phone_model", "series").order_by("pk"):
                key = p.phone_model_key
                if key in new_keys and key not in hosts:
                    hosts[key] = p
            for m in PhoneModel.objects.for_tenant(tenant).filter(match_key__in=new_keys - set(hosts)):
                models[m.match_key] = m
            unknown = sorted(new_keys - set(hosts) - set(models))
            if unknown:
                names = "、".join(unknown[:5]) + (f" 等 {len(unknown)} 個" if len(unknown) > 5 else "")
                # 放在 detail:畫面的錯誤訊息只認這一格
                raise serializers.ValidationError({
                    "detail": f"找不到這幾個機型:{names}。相容機型請從清單選;清單裡沒有的,要先有那個機型(新增手機型號)才能綁。"
                })
        for key, rel in existing.items():
            if key not in target_keys:
                rel.delete()
        for key in sorted(new_keys):
            host = hosts.get(key)
            ProductRelation.objects.create(
                tenant=tenant,
                host_product=host,
                host_model=host.phone_model if host is not None else models[key],
                host_model_key=key,
                accessory_product=accessory,
            )

    def _sync_host_relations_by_ids(self, accessory, host_ids):
        """(legacy)接收 host SKU id 清單,內部轉成 model_key 同步。"""
        tenant = accessory.tenant
        ids = [hid for hid in host_ids if hid != accessory.id]
        hosts = list(
            Product.objects.for_tenant(tenant)
            .filter(id__in=ids)
            .select_related("phone_model", "series")
        )
        keys = [h.phone_model_key for h in hosts if h.phone_model_key]
        self._sync_host_relations_by_keys(accessory, keys)
