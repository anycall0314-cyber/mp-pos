from django.db import models, transaction

from apps.core.models import TenantOwnedModel


class Category(TenantOwnedModel):
    """商品類別。code 同時作為旗下 Product 的 SKU 前綴。"""

    code = models.SlugField(
        "類別代碼",
        max_length=8,
        help_text="作為 SKU 前綴；建議 2-4 個大寫英數,例如 PH(手機)、TB(平板)、AC(配件)",
    )
    name = models.CharField("類別名稱", max_length=80)
    sort_order = models.PositiveIntegerField("排序", default=100)
    is_active = models.BooleanField("啟用", default=True)
    is_secondhand_default = models.BooleanField(
        "中古機類別",
        default=False,
        help_text="勾起時,本類別下所有新增/編輯的商品自動標為中古機(逐隻記成色 / 電池 / 自定售價)",
    )

    next_sku_seq = models.PositiveIntegerField(
        "下一流水號",
        default=1,
        editable=False,
        help_text="下一個要發出的流水號;每次發 SKU 後 +1",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_category_tenant_code"),
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_category_tenant_name"),
        ]
        ordering = ["sort_order", "code"]
        verbose_name = "商品類別"
        verbose_name_plural = "商品類別"

    def __str__(self) -> str:
        return f"[{self.code}] {self.name}"

    def save(self, *args, **kwargs):
        """偵測 is_secondhand_default 由 False → True 時,
        把底下所有商品 is_secondhand=True、requires_serial=True、is_virtual=False。
        反向(True → False)不 cascade,避免誤動既有資料。"""
        cascade_to_products = False
        if self.pk:
            try:
                prev = Category.objects.only("is_secondhand_default").get(pk=self.pk)
                if not prev.is_secondhand_default and self.is_secondhand_default:
                    cascade_to_products = True
            except Category.DoesNotExist:
                pass
        super().save(*args, **kwargs)
        if cascade_to_products:
            # 用 .update 批次跑,避免逐筆觸發 Product.save() 的其他副作用
            Product.objects.filter(category=self).update(
                is_secondhand=True,
                requires_serial=True,
                is_virtual=False,
            )

    def issue_next_sku(self) -> str:
        """原子地取下一個 SKU,回傳 `{code}-{6位流水}`。"""
        with transaction.atomic():
            row = Category.objects.select_for_update().get(pk=self.pk)
            seq = row.next_sku_seq
            row.next_sku_seq = seq + 1
            row.save(update_fields=["next_sku_seq"])
            self.next_sku_seq = row.next_sku_seq
            return f"{row.code}-{seq:06d}"


class Product(TenantOwnedModel):
    """SKU 型號主檔。一台實體機是 inventory.ProductSerial。"""

    sku = models.CharField(
        "品號",
        max_length=60,
        editable=False,
        help_text="系統自動產生:{類別代碼}-{6位流水}",
    )
    name = models.CharField(
        "品名",
        max_length=200,
        help_text="使用者編排的商品名稱,建議含規格(例:iPhone 15 Pro 256GB 黑)",
    )
    spec = models.CharField(
        "規格",
        max_length=200,
        blank=True,
        help_text="補充規格描述,不參與唯一性",
    )
    barcode = models.CharField("條碼", max_length=80, blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="類別",
    )

    weighted_avg_cost = models.DecimalField(
        "加權平均成本",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="當下加權平均成本;每次進貨過帳時重算",
    )
    list_price = models.DecimalField(
        "建議零售價",
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    requires_serial = models.BooleanField(
        "需追蹤序號",
        default=True,
        help_text="是否逐台追蹤序號(IMEI/SN);手機/平板=True,配件=False",
    )
    allows_telecom_line = models.BooleanField(
        "可綁門號合約",
        default=False,
        help_text="銷貨時是否露出 SIM 卡 / 門號 / 促銷方案 / 上線日 欄位",
    )
    allows_commission = models.BooleanField(
        "可有業務員佣金",
        default=False,
        help_text="銷貨時是否露出佣金欄位",
    )
    is_virtual = models.BooleanField(
        "虛擬商品",
        default=False,
        help_text="無實體商品(手續費 / 折抵 / 成本回補等);銷貨時不扣庫存、不建 IMEI、不寫異動",
    )
    is_secondhand = models.BooleanField(
        "中古機",
        default=False,
        help_text="中古機主檔,序號需逐隻記成色 / 電池 / 售價 / 備註,銷貨單價以序號自定為準",
    )
    counts_cash = models.BooleanField(
        "計入現金",
        default=True,
        help_text="該品號金額是否計入現金流量",
    )
    counts_margin = models.BooleanField(
        "計入毛利",
        default=True,
        help_text="該品號金額是否計入毛利報表",
    )
    safety_stock = models.PositiveIntegerField(
        "安全庫存",
        default=0,
        help_text="跨倉總庫存低於此數時,首頁會跳警示。0 = 不提醒",
    )

    class LifecycleStatus(models.TextChoices):
        PENDING = "pending", "待補齊"  # 匯入時的初始狀態,不觸發庫存警示
        ACTIVE = "active", "主力現貨"
        REPLACING = "replacing", "即將換代"
        DISCONTINUED = "discontinued", "停產下架"
        CLEARANCE = "clearance", "清倉處理"

    lifecycle_status = models.CharField(
        "商品狀態",
        max_length=16,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.ACTIVE,
        help_text=(
            "影響庫存警示行為:"
            "active=主力現貨,低庫存會跳補貨警示;"
            "replacing=即將換代,低庫存改顯示審查提醒;"
            "discontinued/clearance=停產/清倉,不觸發補貨警示"
        ),
    )

    class AccessoryType(models.TextChoices):
        NONE = "none", "非配件"  # 手機 / 主機本身
        PHONE_SPECIFIC = "phone_specific", "機型專屬"  # 殼/保護貼
        UNIVERSAL = "universal", "通用型"  # 充電線/耳機

    accessory_type = models.CharField(
        "配件類型",
        max_length=16,
        choices=AccessoryType.choices,
        default=AccessoryType.NONE,
        help_text=(
            "機型專屬:安全庫存改用動態公式(主機日均×購買率×補貨天數);"
            "通用型:用 safety_stock 靜態欄位;"
            "非配件:商品本身是主機"
        ),
    )
    attach_rate = models.DecimalField(
        "配件購買率",
        max_digits=4,
        decimal_places=2,
        default=0.30,
        help_text="預估買主機的人有多少比例會買此配件(0.0~1.0,預設 0.30)",
    )
    replenish_days = models.PositiveSmallIntegerField(
        "補貨天數",
        default=14,
        help_text="動態安全庫存的天數因子(下次補貨能撐幾天),預設 14",
    )

    # ─── 動態庫存統計(由 manage.py compute_dynamic_stock 排程更新)──
    # 這 6 欄全由排程算出,前端 / 進貨流程不該手動填。
    velocity_ewma = models.DecimalField(
        "EWMA 日均銷量",
        max_digits=10,
        decimal_places=3,
        default=0,
        help_text="指數加權移動平均(α=0.15)的最新日均銷量",
    )
    velocity_recent_14d = models.DecimalField(
        "近 14 日均銷量",
        max_digits=10,
        decimal_places=3,
        default=0,
        help_text="最近 14 天的單純日均",
    )
    velocity_baseline_90d = models.DecimalField(
        "90 日基準日均",
        max_digits=10,
        decimal_places=3,
        default=0,
        help_text="過去 90 天的日均,當做趨勢比較基準",
    )
    trend_ratio = models.DecimalField(
        "銷售趨勢比",
        max_digits=5,
        decimal_places=2,
        default=1,
        help_text=">1.2 銷售回溫;<0.5 銷售退燒;1 表示穩定",
    )
    dynamic_safety_stock = models.PositiveIntegerField(
        "動態安全庫存",
        default=0,
        help_text="由銷量 / 主機帶動算出的補貨點。0 = 系統判定不需補貨",
    )
    dynamic_stats_updated_at = models.DateTimeField(
        "動態統計更新時間",
        null=True,
        blank=True,
    )

    # 以下 5 欄僅在 accessory_type=none(主機本身)時有意義
    brand = models.ForeignKey(
        "catalog.Brand",
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="品牌",
        null=True,
        blank=True,
        help_text="僅主機需填(從品牌主檔挑)",
    )
    series = models.ForeignKey(
        "catalog.PhoneSeries",
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="產品系列",
        null=True,
        blank=True,
        help_text="同品牌底下的系列(從產品系列主檔挑)",
    )
    generation = models.PositiveIntegerField(
        "世代序號",
        null=True,
        blank=True,
        help_text="同系列第幾代;例:iPhone 15 → 15、Galaxy S26 → 26",
    )
    model_suffix = models.CharField(
        "型號後綴",
        max_length=30,
        blank=True,
        default="",
        help_text=(
            "型號的尾段差異化標記;例:Pro / Pro Max / Plus / Ultra / +。"
            "拼出完整機型名稱:系列名稱 + 世代 + 後綴"
        ),
    )
    is_variant = models.BooleanField(
        "規格變體",
        default=False,
        help_text=(
            "勾選代表此商品為同代不同容量/顏色的變體,"
            "後續系統的『下一代上市自動換代』判斷會略過此筆"
        ),
    )

    # 倉別:商品倉(銷貨用)vs 零件倉(維修用),預設 product
    class WarehouseType(models.TextChoices):
        PRODUCT = "product", "商品倉"  # 一般銷售商品 / 配件
        PARTS = "parts", "零件倉"  # 維修用零件(螢幕 / 電池 等)

    warehouse_type = models.CharField(
        "倉別",
        max_length=16,
        choices=WarehouseType.choices,
        default=WarehouseType.PRODUCT,
        help_text="商品倉=銷貨用、安全庫存動態算;零件倉=維修用、靜態安全庫存",
    )
    # 零件倉專用:是否可對外調貨給同行
    is_externally_sellable = models.BooleanField(
        "可對外銷售",
        default=False,
        help_text="零件可對同行調貨;銷貨單能挑,異動原因標『零件調貨』",
    )
    external_sale_price = models.DecimalField(
        "對外售價",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="零件對同行調貨的標準售價",
    )
    min_sale_price = models.DecimalField(
        "最低售價",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="防呆下限;銷貨時手動調整不可低於此值",
    )

    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "sku"], name="uniq_product_tenant_sku"),
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_product_tenant_name"),
        ]
        ordering = ["sku"]
        indexes = [
            models.Index(fields=["tenant", "is_active"]),
            models.Index(fields=["category"]),
            models.Index(fields=["barcode"]),
        ]
        verbose_name = "商品"
        verbose_name_plural = "商品"

    def __str__(self) -> str:
        return f"{self.sku} {self.name}"

    def save(self, *args, **kwargs):
        if not self.sku:
            if self.category_id is None:
                raise ValueError("建立商品必須先指定 category")
            self.sku = self.category.issue_next_sku()
        # 類別標記為「中古機類別」時自動把商品帶成中古機
        # (使用者不用每筆都勾,新增 / 型號展開 / 批次匯入皆生效)
        if self.category_id and not self.is_secondhand:
            try:
                cat = self.category
            except Category.DoesNotExist:
                cat = None
            if cat and cat.is_secondhand_default:
                self.is_secondhand = True
        # 中古機一定追蹤序號 / 不能是虛擬商品(跟 ProductForm UI 行為一致)
        if self.is_secondhand:
            self.requires_serial = True
            self.is_virtual = False
        super().save(*args, **kwargs)

    @property
    def phone_model_name(self) -> str:
        """機型名稱:用於配件 - 主機相容性綁定(跨同款 SKU)。
        實作在 phone_model.py。
        """
        from .phone_model import compute_phone_model_name

        return compute_phone_model_name(self)

    @property
    def phone_model_key(self) -> str:
        from .phone_model import compute_phone_model_key

        return compute_phone_model_key(self)


class Brand(TenantOwnedModel):
    """品牌主檔(per-tenant)。

    Phase 1:取代 Product.brand CharField,改用 FK 控制詞彙。
    code 為穩定識別(slug:apple / samsung / xiaomi …),name 是顯示名(可繁體中文)。
    """

    code = models.SlugField("代碼", max_length=20)
    name = models.CharField("顯示名稱", max_length=80)
    sort_order = models.PositiveIntegerField("排序", default=0)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_brand_tenant_code"
            ),
            models.UniqueConstraint(
                fields=["tenant", "name"], name="uniq_brand_tenant_name"
            ),
        ]
        ordering = ["sort_order", "code"]
        verbose_name = "品牌"
        verbose_name_plural = "品牌"

    def __str__(self) -> str:
        return self.name


class ProductType(TenantOwnedModel):
    """產品類型主檔(per-tenant)。

    用於標示「系列屬於哪一類產品」:手機 / 平板 / 耳機 / 手錶 / 智慧家電 …
    可自訂。平台管理員可預先匯入固定範本給經銷商當起手式。
    """

    code = models.SlugField("代碼", max_length=20)
    name = models.CharField("顯示名稱", max_length=40)
    sort_order = models.PositiveIntegerField("排序", default=0)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_product_type_tenant_code"
            ),
            models.UniqueConstraint(
                fields=["tenant", "name"], name="uniq_product_type_tenant_name"
            ),
        ]
        ordering = ["sort_order", "code"]
        verbose_name = "產品類型"
        verbose_name_plural = "產品類型"

    def __str__(self) -> str:
        return self.name


class PhoneSeries(TenantOwnedModel):
    """產品系列主檔,掛在 Brand 底下(per-tenant)。

    例:Samsung 底下有 Galaxy S / Galaxy A / Galaxy Z / Galaxy Note / Galaxy FE …
    Apple 底下有 iPhone / iPad / Watch …
    每個系列可指定「產品類型」(手機 / 平板 / 耳機 / 手錶 …),
    讓同品牌底下混放不同類型的系列。
    """

    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="series",
        verbose_name="品牌",
    )
    product_type = models.ForeignKey(
        ProductType,
        on_delete=models.SET_NULL,
        related_name="series",
        verbose_name="產品類型",
        null=True,
        blank=True,
    )
    code = models.SlugField("代碼", max_length=20)
    name = models.CharField("顯示名稱", max_length=80)
    sort_order = models.PositiveIntegerField("排序", default=0)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "brand", "code"],
                name="uniq_phone_series_brand_code",
            ),
        ]
        ordering = ["sort_order", "code"]
        verbose_name = "產品系列"
        verbose_name_plural = "產品系列"

    def __str__(self) -> str:
        return f"{self.brand.name} {self.name}"


class PartTemplate(TenantOwnedModel):
    """零件範本:定義「一種機型類別有哪些零件種類」。

    例:智慧型手機(標準) = 螢幕總成 / 電池 / 後蓋 / 充電孔排線 / 喇叭 / 聽筒 / Home 鍵 / 指紋模組
    範本建好可重複套用至多款機型,批次建立 SKU。
    """

    name = models.CharField("範本名稱", max_length=80)
    note = models.CharField("備註", max_length=200, blank=True)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"], name="uniq_part_template_name"
            ),
        ]
        ordering = ["name"]
        verbose_name = "零件範本"
        verbose_name_plural = "零件範本"

    def __str__(self) -> str:
        return self.name


class PartTemplateItem(TenantOwnedModel):
    """零件範本內的零件種類條目。"""

    template = models.ForeignKey(
        PartTemplate, on_delete=models.CASCADE, related_name="items"
    )
    name = models.CharField("零件種類名稱", max_length=80, help_text="例:螢幕總成")
    code = models.CharField(
        "零件代碼",
        max_length=10,
        help_text="用於組品號的後綴(例:SCR / BAT / BACK)",
    )
    sort_order = models.PositiveIntegerField("排序", default=0)
    default_cost = models.DecimalField(
        "預設成本", max_digits=14, decimal_places=2, default=0
    )
    default_safety_stock = models.PositiveIntegerField("預設安全庫存", default=0)
    shared_across_models = models.BooleanField(
        "跨機型共用",
        default=False,
        help_text=(
            "勾選後,此零件在批次建立時不會逐機型展開,而是每個品牌建立一筆共用 SKU,"
            "相容多個選定機型。常見於電池等少數可共用的零件;螢幕/後蓋等請保持不勾"
        ),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["template", "code"], name="uniq_part_template_item_code"
            ),
        ]
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class ProductRelation(TenantOwnedModel):
    """商品關聯 — 配件 ↔ 主機機型 的對應。

    一個配件可同時相容多個機型(例:玻璃貼可同時適配 iPhone 15 / 15 Pro);
    一個機型涵蓋該款的所有 SKU 變體(不同容量/顏色/中古機都共用同一關聯)。

    主鍵層級:`host_model_key`(機型 key,跨 SKU)。
    `host_product` 保留作為代表 SKU(用於 UI 顯示某機型範例 SKU),但邏輯上以 key 為準。
    """

    host_product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="accessory_relations",
        verbose_name="主機代表 SKU",
        help_text="該機型的代表 SKU(任一);邏輯比對以 host_model_key 為準",
    )
    host_model_key = models.CharField(
        "機型 key",
        max_length=128,
        default="",
        blank=True,
        db_index=True,
        help_text="lowercase 機型名稱,從 host_product 推導(品名去變體 / series+generation)",
    )
    accessory_product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="host_relations",
        verbose_name="配件商品",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "host_model_key", "accessory_product"],
                name="uniq_product_relation_by_model",
            ),
            models.CheckConstraint(
                check=~models.Q(host_product=models.F("accessory_product")),
                name="product_relation_not_self",
            ),
        ]
        verbose_name = "商品關聯"
        verbose_name_plural = "商品關聯"

    def __str__(self):
        return (
            f"{self.accessory_product.name} → {self.host_model_key or self.host_product.name}"
        )

    def save(self, *args, **kwargs):
        # host_model_key 為空時自動從 host_product 推
        if not self.host_model_key and self.host_product_id:
            self.host_model_key = self.host_product.phone_model_key
        super().save(*args, **kwargs)
