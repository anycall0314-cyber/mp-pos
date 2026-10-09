from django.conf import settings
from django.db import models, transaction

from apps.core.models import TenantOwnedModel
from apps.core.staff_cost import PRODUCT_MODES


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

    needs_host_model = models.BooleanField(
        "需要掛相容機型",
        default=True,
        help_text=(
            "這個類別的商品要不要掛「相容哪些機型」(ProductRelation)。"
            "主機本身(手機 / 平板 / 手錶)不用掛;線材、吊飾、家電這種跟機型無關的也不用。"
            "關掉之後這類商品不會出現在「待補相容機型」的待辦裡"
        ),
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
        """`is_secondhand_default` 由 False → True 時,把底下所有商品 is_secondhand=True、requires_serial=True、is_virtual=False。
        反向(True → False)不連動,避免誤動既有資料。

        底下有**用過**的商品會被連帶改到 → 不能改(`usage.py`;作廢 / 退貨時庫存是照這幾個屬性加減回去的)。
        畫面那一條路在序列化器先擋、回得出好懂的訊息;這裡是最後一道(後台、指令也過不去),
        而且**鎖著這個類別**做完「看以前是不是 → 檢查 → 存 → 連動」:這段時間別人不能把商品移進來。
        只存部分欄位、而且沒有要寫 `is_secondhand_default` 的存檔不連動(那個值沒有真的被寫進去)。
        """
        from .usage import (
            StockFlagsLocked,
            cascade_message,
            cascade_targets,
            category_cascade_blockers,
            lock_category,
            lock_category_products,
            save_arguments,
        )

        # 參數換成整理過、全部用關鍵字的那一份再往下傳(見 save_arguments)
        fields, kwargs = save_arguments(args, kwargs)
        writes_default = fields is None or "is_secondhand_default" in fields
        if not (self.pk and writes_default and self.is_secondhand_default):
            return super().save(**kwargs)
        with transaction.atomic():
            cascade_to_products = lock_category(self.pk) is False
            if cascade_to_products:
                # 先把底下**全部**的商品照編號鎖住(等正在存檔的做完),才看哪些要改、哪些用過
                lock_category_products(self)
                blockers = category_cascade_blockers(self)
                if blockers.exists():
                    raise StockFlagsLocked(cascade_message(blockers))
            super().save(**kwargs)
            if cascade_to_products:
                # 只改還不是那樣的(都已經鎖在手上)。用 .update 批次跑,避免逐筆觸發 Product.save() 的其他副作用
                cascade_targets(self).update(
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
    # 業務員成本(算獎金看的毛利用的成本):這個商品自己的設定;空的 = 照全公司的那一條。
    # 只是另外算的一個數字,不會寫回上面的實際成本。規則在 apps/core/staff_cost.py
    staff_cost_mode = models.CharField(
        "業務員成本算法", max_length=10, blank=True, default="", choices=PRODUCT_MODES,
        help_text="空的 = 照全公司的設定",
    )
    staff_cost_value = models.DecimalField(
        "業務員成本數值", max_digits=14, decimal_places=2, default=0,
        help_text="固定金額 = 每一件幾元;加固定額 = 成本加幾元;加百分比 = 成本加幾 %",
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
    condition = models.ForeignKey(
        "Condition",
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="商品狀態",
        null=True,
        blank=True,
        help_text=(
            "全新 / 已拆封 / 中古機(保固內)/ 中古機 …"
            "由「新增手機型號」wizard 一鍵帶入;舊資料未指定為 NULL,沿用 is_secondhand 旗標判斷"
        ),
    )
    style_code = models.CharField(
        "款式碼",
        max_length=20,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "無品牌配件的穩定款式編號(例:042)。店員不用自己想名字,"
            "容易撞名的款式用「透明磁吸防摔殼 042」這樣區分"
        ),
    )
    phone_model = models.ForeignKey(
        "PhoneModel",
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
        verbose_name="機型",
        help_text=(
            "穩定的機型身分。舊資料為 NULL 時退回 phone_model_key 那個"
            "算出來的字串,行為不變"
        ),
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

    # 進貨識別用的結構化屬性(識別引擎的「衝突檢查」靠這三欄站穩:
    # 容量/顏色/版本不同 → 一定是不同商品,禁止自動對應)。
    # 舊資料留白不會出錯,只會讓比對信心變低 → 落到待確認區由人確認,永不誤對。
    capacity = models.CharField(
        "容量",
        max_length=20,
        blank=True,
        default="",
        help_text="結構化容量,例:128GB / 256GB / 1TB。用於避免 128G 被誤對成 256G",
    )
    color = models.CharField(
        "顏色",
        max_length=30,
        blank=True,
        default="",
        help_text="結構化顏色,例:黑 / 藍 / 原色鈦金屬",
    )
    region_version = models.CharField(
        "地區版本",
        max_length=30,
        blank=True,
        default="",
        help_text="例:台版 / 港版 / 美版 / 陸版。不同版本視為不同商品",
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
        # 類別標記為「中古機類別」時自動把商品帶成中古機(使用者不用每筆都勾,新增 / 型號展開 / 批次匯入皆生效);
        # 中古機一定追蹤序號 / 不能是虛擬商品(跟 ProductForm UI 行為一致)。規則只有 usage.flags_after_save 一份
        from .usage import (
            STOCK_FLAGS,
            category_is_secondhand,
            check_stock_flags,
            flags_after_save,
            lock_category,
            save_arguments,
            stored_flags,
        )

        # 參數換成整理過、全部用關鍵字的那一份再往下傳(見 save_arguments)
        fields, kwargs = save_arguments(args, kwargs)
        # 這一次真的會寫進去的那幾個屬性(只存部分欄位時,沒列到的不會被寫,記憶體裡改了什麼都不算)
        written = tuple(f for f in STOCK_FLAGS if fields is None or f in fields)
        writes_category = fields is None or "category" in fields or "category_id" in fields
        # 用過的商品不能改這三個屬性(見 usage.py);檢查只有這一份,畫面、批次修改、匯入、指令都過這裡。
        # 既有的商品(看資料庫裡有沒有這一筆,不看這個物件是不是剛 new 出來的)、而且這次會寫到屬性或類別才需要;
        # 只寫別的欄位(例:只更新加權平均成本)的存檔不會動到它們,不用鎖也不用查
        before = stored_flags(self) if (written or writes_category) else None
        if before is None:
            category_secondhand = False
            if self.category_id and not self.is_secondhand:
                try:
                    category_secondhand = bool(self.category.is_secondhand_default)
                except Category.DoesNotExist:
                    category_secondhand = False
            self._apply_stock_flags(flags_after_save(
                category_secondhand=category_secondhand,
                is_secondhand=self.is_secondhand,
                requires_serial=self.requires_serial,
                is_virtual=self.is_virtual,
            ))
            return super().save(**kwargs)
        with transaction.atomic():
            # 鎖的順序固定:先類別(只有換類別才拿)、後商品這一列。
            # 移進另一個類別:鎖住那個類別、重讀它**現在**是不是中古機類別 ——
            # 同一時間有人正把它勾成中古機類別的話,兩邊排隊做,不會一個剛檢查完、另一個就把用過的商品移進來。
            # 沒有換類別:不拿類別的鎖(見 lock_category 的說明)
            moving = writes_category and before["category_id"] != self.category_id
            category_now = lock_category(self.category_id) if moving else None
            # 鎖住這一列再讀一次:屬性「有沒有變」比的是這一份(鎖到的當下),不是剛剛沒鎖時讀的
            current = stored_flags(self, lock=True)
            if current and writes_category and not moving and current["category_id"] != self.category_id:
                # 剛剛讀的時候還在這個類別、鎖到時已經被別人移走了(同一個商品三個人同時改才會):
                # 這一次存檔等於把它移回來,一樣要拿類別的鎖
                moving = True
                category_now = lock_category(self.category_id)
            if not moving:
                category_now = category_is_secondhand(self.category_id)
            flags = flags_after_save(
                category_secondhand=bool(category_now) and not self.is_secondhand,
                is_secondhand=self.is_secondhand,
                requires_serial=self.requires_serial,
                is_virtual=self.is_virtual,
            )
            self._apply_stock_flags(flags)
            check_stock_flags(self, flags, written, current)
            return super().save(**kwargs)

    def _apply_stock_flags(self, flags):
        for name, value in flags.items():
            setattr(self, name, value)

    @property
    def tracks_unit_condition(self) -> bool:
        """進貨時要不要逐台記成色 / 電池 / 個別售價 / 備註。

        以品況主檔為準(全新不記,已拆封與中古都記)。舊商品沒掛品況時
        退回舊行為(只有中古機記),既有資料的表現不變。

        **中古機一律為 True**,不看品況旗標。因為中古機的成色與每台成本
        本來就是必填,關掉會讓進貨卡死(欄位藏起來卻仍被要求填成色);
        而且「中古機類別」會把商品自動設成 is_secondhand=True,品況卻可能
        還掛著全新,這條 or 讓那種組合也不會出事。

        注意:這只管「機況資料」。每隻獨立成本仍只看 `is_secondhand`,
        成本政策不跟著放寬。
        """
        if self.is_secondhand:
            return True
        if self.condition_id is not None:
            condition = self.condition
            if condition is not None:
                return condition.tracks_unit_condition
        return False

    @property
    def phone_model_name(self) -> str:
        """機型名稱:用於配件 - 主機相容性綁定(跨同款 SKU)。

        掛了機型主檔就用它(穩定,改品名不會讓關聯散掉);
        舊資料沒掛的退回 phone_model.py 那套算出來的字串,行為不變。
        """
        if self.phone_model_id:
            return self.phone_model.name
        from .phone_model import compute_phone_model_name

        return compute_phone_model_name(self)

    @property
    def phone_model_key(self) -> str:
        if self.phone_model_id:
            return self.phone_model.match_key
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


class Condition(TenantOwnedModel):
    """商品狀態主檔(per-tenant)。

    用於建手機型號時的狀態維度:全新 / 已拆封 / 中古機(保固內)/ 中古機 …
    `is_secondhand=True` 的狀態下建立的 SKU 會自動 `Product.is_secondhand=True`,
    沿用中古機「每隻獨立 purchase_unit_cost」邏輯。

    系統建議的 4 個預設值由 migration 自動 seed,經銷商可自行 CRUD。
    """

    code = models.SlugField("代碼", max_length=20)
    name = models.CharField("顯示名稱", max_length=40)
    is_secondhand = models.BooleanField(
        "視為中古機",
        default=False,
        help_text=(
            "勾選後此狀態下建立的 SKU 自動 is_secondhand=True,"
            "觸發中古機成本邏輯(每隻獨立 purchase_unit_cost)"
        ),
    )
    tracks_unit_condition = models.BooleanField(
        "逐台記機況",
        default=True,
        help_text=(
            "勾選後,進貨時這個狀態的每一台都可以記成色 / 電池 / 個別售價 / 備註。"
            "與「視為中古機」分開:已拆封不是中古機,但一樣要逐台記。"
            "成本政策仍只看「視為中古機」"
        ),
    )
    sort_order = models.PositiveIntegerField("排序", default=0)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_condition_tenant_code"
            ),
            models.UniqueConstraint(
                fields=["tenant", "name"], name="uniq_condition_tenant_name"
            ),
            # 中古機一定要逐台記機況。save() 已經會修正,這條是最後防線
            # (bulk_update / queryset.update / 原生 SQL 都繞不過)。
            models.CheckConstraint(
                check=~models.Q(is_secondhand=True, tracks_unit_condition=False),
                name="condition_secondhand_tracks_unit",
            ),
        ]
        ordering = ["sort_order", "code"]
        verbose_name = "商品狀態"
        verbose_name_plural = "商品狀態"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        # 中古機的成色與每台成本本來就必填,不允許關掉逐台記機況,
        # 否則進貨畫面會把欄位藏起來卻仍要求填成色,直接卡死。
        if not (self.is_secondhand and not self.tracks_unit_condition):
            return super().save(*args, **kwargs)
        self.tracks_unit_condition = True
        # save(update_fields=["is_secondhand"]) 只會寫指定欄位,不一起帶上
        # 這個修正就不會進 DB(接著會撞 CheckConstraint)。
        # update_fields 可能走位置參數(Django 5.1 的 save 簽章仍接受
        # force_insert, force_update, using, update_fields 四個位置參數)。
        positional = len(args) >= 4
        update_fields = args[3] if positional else kwargs.get("update_fields")
        # None = 寫全部欄位,不用動;
        # 空集合 = 呼叫端明確表示「什麼都不要寫」,那個語意要保留,
        #          不能擴充成非空(會變成真的去寫,未存檔物件還會拋 ValueError)。
        if update_fields:
            merged = set(update_fields) | {"tracks_unit_condition"}
            if positional:
                args = args[:3] + (merged,) + args[4:]
            else:
                kwargs["update_fields"] = merged
        return super().save(*args, **kwargs)


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
    """機型範本 / 零件範本:定義「一種機型類別建單時要產出哪些東西」。

    原本只覆蓋維修零件清單(items),Phase 2 擴充為「機型範本」:
    - default_capacities:預設容量清單,例 ["128G","256G","512G","1TB"]
    - default_colors:預設顏色清單,例 ["黑","白","鈦原色"]
    - default_accessory_categories:預設配件類別清單,例 ["殼","貼"]
    - items(沿用):維修零件種類清單

    新增手機型號 wizard 套用此範本後,會用「狀態主檔 × 預設容量 × 預設顏色」
    產生主機 SKU,並依「預設配件類別」建配件 placeholder、依 items 建零件 SKU。
    舊範本三個 JSON 欄位都是空,wizard 套用時就只建主機 SKU,不影響相容性。
    """

    name = models.CharField("範本名稱", max_length=80)
    note = models.CharField("備註", max_length=200, blank=True)
    is_active = models.BooleanField("啟用", default=True)

    default_capacities = models.JSONField(
        "預設容量清單",
        default=list,
        blank=True,
        help_text="例:[\"128GB\",\"256GB\",\"512GB\",\"1TB\"];wizard 第 2 步當作預設勾選項",
    )
    default_colors = models.JSONField(
        "預設顏色清單",
        default=list,
        blank=True,
        help_text="例:[\"黑\",\"白\",\"鈦原色\"];wizard 第 2 步當作預設勾選項",
    )
    default_accessory_categories = models.JSONField(
        "預設配件類別",
        default=list,
        blank=True,
        help_text="例:[\"殼\",\"貼\"];線 / 充走通用配件不綁機型,不放這裡",
    )
    default_accessory_brands = models.JSONField(
        "常用配件品牌",
        default=list,
        blank=True,
        help_text=(
            "例:[\"imos\",\"HODA\",\"JTLEGEND\"];"
            "「+ 新增配件」wizard 套此範本時,會列出這些品牌讓使用者一個個建商品線。"
            "純參考用,不直接建 SKU"
        ),
    )

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


class SupplierProduct(TenantOwnedModel):
    """供應商商品對照 —— 「這家廠商的這個商品頁 / 這個變體」對到我的哪個品號。

    跟 `identity.ProductAlias` 的分工:
    - ProductAlias 管「一個字串(品名 / 料號 / 條碼)」→ 商品,給識別引擎比對用。
    - 這張表管「一個來源商品」→ 商品,記的是來源本身(平台、商品頁、選到哪個
      變體、連結、一箱幾入)。淘寶同一個網址底下會有不同機型 / 顏色 / 材質 /
      包裝,光靠網址對不到店內商品,要連變體一起記才算數。

    一個商品可以有多個已確認來源(同一顆玻璃貼跟三家買)。
    供應商改版或重用料號時,把舊的停用、建新的,歷史留著。
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="supplier_products",
        verbose_name="對應商品",
    )
    supplier = models.ForeignKey(
        "parties.Supplier",
        on_delete=models.PROTECT,
        related_name="supplier_products",
        verbose_name="供應商",
    )
    platform = models.CharField(
        "平台", max_length=40, blank=True, default="",
        help_text="例:淘寶 / 蝦皮 / 官網 / 電話下單",
    )
    page_id = models.CharField(
        "商品頁 ID", max_length=120, blank=True, default="", db_index=True,
        help_text="平台上的商品編號;同一頁可能有多個變體",
    )
    variant = models.CharField(
        "選到的變體", max_length=200, blank=True, default="",
        help_text="顏色 / 機型 / 材質 / 包裝,例:透明-iPhone15Pro-10入",
    )
    vendor_sku = models.CharField(
        "廠商料號", max_length=80, blank=True, default="", db_index=True,
        help_text="**變體層**的料號(對到一個實際可下單的規格),不是父商品料號",
    )
    vendor_sku_key = models.CharField(
        "料號比對鍵", max_length=200, blank=True, default="", db_index=True,
        help_text=(
            "vendor_sku 正規化後的字,系統自動算。查重與唯一鍵都用它 —— "
            "用原字的話 ABC-01 / abc-01 / ＡＢＣ－０１ 會被當成三個不同料號,"
            "跟別名表(它用正規化鍵)對不起來"
        ),
    )
    source_name_key = models.CharField(
        "來源品名比對鍵", max_length=200, blank=True, default="", db_index=True,
        help_text="source_name 正規化後的字,系統自動算;沒有料號時靠它去重",
    )
    source_name = models.CharField(
        "來源品名", max_length=300, blank=True, default="",
        help_text="廠商自己的叫法,原樣保留;不要拿來當店內品名",
    )
    url = models.URLField("連結", max_length=500, blank=True, default="")
    pack_qty = models.PositiveIntegerField(
        "一單位幾入", default=1,
        help_text="來源一件等於店內幾個計量單位(一盒 10 片就填 10)",
    )
    note = models.CharField("備註", max_length=200, blank=True, default="")
    is_active = models.BooleanField("啟用", default=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_supplier_products",
        verbose_name="確認人",
    )
    confirmed_at = models.DateTimeField("確認時間", null=True, blank=True)

    class Meta:
        constraints = [
            # 同一家廠商的同一個料號不重複(只管啟用中的,停用的留著當歷史)
            models.UniqueConstraint(
                fields=["tenant", "supplier", "vendor_sku_key"],
                condition=models.Q(is_active=True) & ~models.Q(vendor_sku_key=""),
                name="uniq_supplier_product_vendor_sku",
            ),
            # 沒有料號也沒有商品頁的自動紀錄:同一家 + 同一個商品 + 同一個
            # 來源品名只留一筆。先查再新增擋不住併發(尚不存在的列鎖不住),
            # 要靠唯一鍵兜底。不套到有料號 / 有商品頁的正式來源。
            models.UniqueConstraint(
                fields=["tenant", "supplier", "product", "source_name_key"],
                condition=(
                    models.Q(is_active=True)
                    & models.Q(vendor_sku_key="")
                    & models.Q(page_id="")
                    & ~models.Q(source_name_key="")
                ),
                name="uniq_supplier_product_auto_source",
            ),
            # 同一家廠商、同一個平台、同一個商品頁 + 同一個變體不重複。
            # 一定要帶平台:page_id 只在該平台內唯一,淘寶的 123 跟蝦皮的 123
            # 是兩回事。也一定要 variant 非空:空字串是「變體還不知道」,
            # 不是「同一個變體」,拿它當鍵會把同頁的不同變體擋掉。
            models.UniqueConstraint(
                fields=["tenant", "supplier", "platform", "page_id", "variant"],
                condition=(
                    models.Q(is_active=True)
                    & ~models.Q(page_id="")
                    & ~models.Q(variant="")
                ),
                name="uniq_supplier_product_page_variant",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "product"])]
        ordering = ["supplier", "product"]
        verbose_name = "供應商商品對照"
        verbose_name_plural = "供應商商品對照"

    def save(self, *args, **kwargs):
        from apps.identity.normalize import alias_key

        self.vendor_sku_key = alias_key(self.vendor_sku)[:200]
        self.source_name_key = alias_key(self.source_name)[:200]
        # save(update_fields=["source_name"]) 只會寫指定欄位,不一起帶上
        # 這兩個算出來的 key 就會留著舊值,查重從此對不到。
        update_fields = kwargs.get("update_fields")
        if update_fields:
            merged = set(update_fields)
            if "vendor_sku" in merged:
                merged.add("vendor_sku_key")
            if "source_name" in merged:
                merged.add("source_name_key")
            kwargs["update_fields"] = merged
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        bits = [self.supplier.name, self.vendor_sku or self.page_id or self.source_name]
        return f"[{' '.join(b for b in bits if b)}] → {self.product_id}"


class PhoneModel(TenantOwnedModel):
    """機型主檔 —— 租戶內穩定的「一款手機」。

    在這之前,「同一款手機」是靠 `Product.phone_model_key` 這個**算出來的字串**
    連在一起的:有品牌系列就用「系列+世代+後綴」,沒有就 regex 解析品名。
    字串一改(改品名、補系列、改後綴)關聯就散掉,而且沒辦法在上面掛任何東西。

    這張表給它一個穩定的 id。`match_key` 保留那個算出來的字串,只當作「把舊資料
    對進來」與「新商品自動歸位」的依據,不再是身分本身。

    刻意不做的事:不在這個階段改寫任何單據的外鍵,也不動 `host_model_key`
    那些欄位(它們會被同步維護),避免一次動太多。
    """

    code = models.SlugField("代碼", max_length=40)
    name = models.CharField("機型名稱", max_length=128)
    match_key = models.CharField(
        "比對鍵",
        max_length=128,
        db_index=True,
        help_text="lowercase 機型名稱;舊資料對應與新商品自動歸位用,不是身分",
    )
    brand = models.ForeignKey(
        "Brand",
        on_delete=models.PROTECT,
        related_name="phone_models",
        null=True,
        blank=True,
        verbose_name="品牌",
    )
    series = models.ForeignKey(
        "PhoneSeries",
        on_delete=models.PROTECT,
        related_name="phone_models",
        null=True,
        blank=True,
        verbose_name="系列",
    )
    generation = models.PositiveIntegerField("世代", null=True, blank=True)
    model_suffix = models.CharField("型號後綴", max_length=30, blank=True, default="")
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_phone_model_tenant_code"
            ),
            models.UniqueConstraint(
                fields=["tenant", "match_key"],
                name="uniq_phone_model_tenant_match_key",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "is_active"])]
        ordering = ["name"]
        verbose_name = "機型"
        verbose_name_plural = "機型"

    def __str__(self) -> str:
        return self.name


class ProductRelation(TenantOwnedModel):
    """商品關聯 — 配件 ↔ 主機機型 的對應。

    一個配件可同時相容多個機型(例:玻璃貼可同時適配 iPhone 15 / 15 Pro);
    一個機型涵蓋該款的所有 SKU 變體(不同容量/顏色/中古機都共用同一關聯)。

    主鍵層級:`host_model_key`(機型 key,跨 SKU)。
    `host_product` 保留作為代表 SKU(用於 UI 顯示某機型範例 SKU),但邏輯上以 key 為準。
    """

    host_model = models.ForeignKey(
        "PhoneModel",
        on_delete=models.CASCADE,
        related_name="accessory_relations",
        null=True,
        blank=True,
        verbose_name="主機機型",
        help_text="穩定的機型身分;舊資料為 NULL 時以 host_model_key 為準",
    )
    host_product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        related_name="accessory_relations",
        null=True,
        blank=True,
        verbose_name="主機代表 SKU",
        help_text=(
            "該機型的代表 SKU(任一),只用於 UI 顯示範例。"
            "刪掉這支 SKU 不該讓整組相容關係跟著消失,所以是 SET_NULL 不是 CASCADE"
        ),
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
        # host_product 現在可以是 NULL(代表 SKU 被刪掉了),不能直接取 .name
        host = self.host_model_key
        if not host and self.host_model_id:
            host = self.host_model.name
        if not host and self.host_product_id:
            host = self.host_product.name
        return f"{self.accessory_product.name} → {host or '(未指定機型)'}"

    def save(self, *args, **kwargs):
        # host_model_key 為空時自動推:優先用機型主檔(穩定),
        # 沒有才退回代表 SKU 算出來的字串(舊行為)
        if not self.host_model_key:
            if self.host_model_id:
                self.host_model_key = self.host_model.match_key
            elif self.host_product_id:
                self.host_model_key = self.host_product.phone_model_key
        super().save(*args, **kwargs)
