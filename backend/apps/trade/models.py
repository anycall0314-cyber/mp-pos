"""批發:這家經銷商**當賣家**的那一半(owner 2026-10-14;規格 `docs/api/買賣串接規格_v2_草稿.md`)。

買家那一半在 `apps/vendor_orders/`(開了批發的經銷商 = 叫貨頁上的一家廠商)。這裡每一張表都是**賣家那家公司的資料**,跟著公司備份走。

- `TradeSetting`:這家公司的批發設定(一家一列)。
- `TradePartner`:往來的同行(買家)。平台內的記對方公司的識別碼,**不用外鍵指到別家公司**(兩家的備份各自帶得走)。
- `TradeKey`:對外的同行(不在這套 POS 上的系統)用的金鑰(只存雜湊)。**不進公司備份**:還原之後舊的金鑰不能自己活過來,要重發。
- `TradeInvite`:給同行的一次性往來代碼(同行在叫貨頁輸入 → 變成核准的往來對象)。平台上的經銷商互相競爭,不提供「所有經銷商的名單」給人挑。
- `TradeUnit`:中古機**一台一筆**的上架(批發價是這一台的)。在不在賣 = 有上架、而且那一台現在在庫、沒有被訂走。
- `TradePriceRule`:中古機**價目表的一格**(型號 + 成色 + 電池區間 + 有沒有備註 → 一個價)。全公司符合那一格的每一台都用那個價,
  那一格改了它們跟著變、新進貨的自動跟;只有被明講**獨立定價**的(`TradeUnit.own_price`)不跟。價錢還是存在 `TradeUnit.price`
  (改一格的時候把跟著的一起改掉),下單、對外看到的都讀那一個,不用每次算。規則在 `pricing.py`。
- `TradePriceChange` / `TradePriceChangeUnit`:改價紀錄(一次改價一筆、底下是動到的每一台從多少變多少)。
- `TradeProduct`:按數量賣的商品(全新機、配件)有沒有開放批發、有沒有固定的批發價。
- `TradeOrder` / `TradeOrderLine`:收到的訂單。`holding` = 這一行還訂著某一台中古機(一台同時只會被一行訂著,資料庫擋)。
- `TradeShipment` / `TradeShipmentLine` / `TradeShipmentSerial`:一次出貨 = 一張銷貨單(庫存與成本的帳只有銷貨單那一份)。
- `TradePayment`:收到同行的一筆錢。**錢不經過平台**,這只是「誰還欠多少」的紀錄;哪一筆銷掉哪一張單不存,
  每次看的時候由舊到新算(`payments.py`)—— 出貨取消、整張銷退之後數字自己會對。
"""
from datetime import date

from django.conf import settings
from django.db import models, transaction

from apps.core.models import TenantOwnedModel
from apps.core.numbering import last_doc_seq

USER = settings.AUTH_USER_MODEL


def _by(verbose):
    return models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name=verbose)


class TradeSetting(TenantOwnedModel):
    class Rule(models.TextChoices):
        PRICE_MINUS = "price_minus", "門市售價減固定金額"
        PRICE_PERCENT = "price_percent", "門市售價打幾折"
        COST_PLUS = "cost_plus", "收購價加固定金額"

    # 總開關:關著 = 沒有人看得到這家在批發、不能下新單(已經收到的單照樣出得了貨)
    is_open = models.BooleanField("開放批發", default=False)
    # 中古機的批發價怎麼算(每一台自動算好,可以個別改)。打幾折的 value 是百分比(90 = 九折)
    unit_rule = models.CharField("中古機批發價的算法", max_length=20, choices=Rule.choices, default=Rule.PRICE_MINUS)
    unit_value = models.DecimalField("減多少 / 幾折 / 加多少", max_digits=14, decimal_places=2, default=0)
    auto_list_units = models.BooleanField("中古機進貨就上架", default=True)
    # 平台販售(owner 2026-10-14):平台上每一家同行都看得到、訂得到中古機;關掉 = 只給核准的同行
    units_to_all = models.BooleanField("中古機給平台上所有同行看", default=True)
    auto_accept = models.BooleanField("同行下單就算接單", default=True)
    show_qty = models.BooleanField("讓同行看到可以訂的數量", default=False)
    # 新的同行預設的條件(每一個同行可以個別改)
    default_percent = models.PositiveSmallIntegerField("新同行的折數(門市價的 %)", default=100)
    default_terms = models.CharField("新同行的付款方式", max_length=20, default="匯款")
    # 給買家看的:錢怎麼給(匯款帳號…)、怎麼聯絡。平台不經手錢
    pay_note = models.CharField("收款資訊", max_length=200, blank=True, default="")
    contact = models.CharField("聯絡方式", max_length=120, blank=True, default="")
    updated_by = _by("改的人")

    class Meta:
        verbose_name = "批發設定"
        verbose_name_plural = "批發設定"
        constraints = [models.UniqueConstraint(fields=["tenant"], name="uniq_trade_setting_tenant")]


class TradePartner(TenantOwnedModel):
    class Kind(models.TextChoices):
        PLATFORM = "platform", "平台內"
        EXTERNAL = "external", "對外(金鑰)"

    class Status(models.TextChoices):
        # 沒有核准過、但訂過這家平台販售的中古機:只看得到中古機
        GUEST = "guest", "未核准"
        APPROVED = "approved", "往來中"
        BLOCKED = "blocked", "不往來"

    kind = models.CharField("接法", max_length=10, choices=Kind.choices, default=Kind.PLATFORM)
    # 平台內的買家 = 對方公司的識別碼(`Tenant.backup_uuid`:換一台伺服器也不會變)
    buyer_uuid = models.UUIDField("買家公司的識別碼", null=True, blank=True)
    name = models.CharField("名稱", max_length=120)
    status = models.CharField("往來", max_length=10, choices=Status.choices, default=Status.GUEST)
    # 全新機與配件的價錢 = 門市售價 × 這個百分比(商品自己有固定批發價的用那個)
    percent = models.PositiveSmallIntegerField("折數(門市價的 %)", default=100)
    terms = models.CharField("付款方式", max_length=20, default="匯款")
    # 出貨開的銷貨單記在哪一個客戶底下(第一次出貨時自動建一筆「同業」)
    customer = models.ForeignKey(
        "parties.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="+", verbose_name="客戶")
    note = models.CharField("備註", max_length=200, blank=True, default="")
    # 對外的同行才填:怎麼聯絡(電話、LINE)。單上只有這個名字與這一格認得出是誰(紅隊 2026-10-14)
    contact = models.CharField("聯絡方式", max_length=120, blank=True, default="", db_default="")
    updated_by = _by("改的人")

    class Meta:
        verbose_name = "往來的同行"
        verbose_name_plural = "往來的同行"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "buyer_uuid"], condition=models.Q(buyer_uuid__isnull=False), name="uniq_trade_partner_buyer"),
        ]

    def __str__(self) -> str:
        return self.name


class TradeKey(TenantOwnedModel):
    """對外的同行的金鑰。原文只在發的那一次回給畫面;這裡只有雜湊(認得出是誰)與前幾碼(給管理員認是哪一把)。
    一個同行同時只有一把:換一把 = 舊的立刻失效。"""

    partner = models.OneToOneField(TradePartner, on_delete=models.CASCADE, related_name="key", verbose_name="同行")
    key_hash = models.CharField("金鑰的雜湊", max_length=64, unique=True)
    hint = models.CharField("前幾碼", max_length=12)
    # 每分鐘最多幾次:這一分鐘從什麼時候算起、已經幾次(`keys.hit` 一句更新)
    window_start = models.DateTimeField("這一分鐘的開始", null=True, blank=True)
    window_count = models.PositiveIntegerField("這一分鐘幾次", default=0)
    last_used_at = models.DateTimeField("最後一次用", null=True, blank=True)
    created_by = _by("發的人")

    class Meta:
        verbose_name = "對外金鑰"
        verbose_name_plural = "對外金鑰"


class TradeInvite(TenantOwnedModel):
    """一次性的往來代碼(只存雜湊)。同行在叫貨頁輸入 → 變成核准的往來對象。"""

    code_hash = models.CharField("代碼的雜湊", max_length=64, unique=True)
    hint = models.CharField("前兩碼", max_length=4)
    percent = models.PositiveSmallIntegerField("折數(門市價的 %)", default=100)
    terms = models.CharField("付款方式", max_length=20, default="匯款")
    expires_at = models.DateTimeField("到什麼時候")
    used_at = models.DateTimeField("用掉的時間", null=True, blank=True)
    partner = models.ForeignKey(
        TradePartner, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="用的人")
    created_by = _by("發的人")

    class Meta:
        verbose_name = "往來代碼"
        verbose_name_plural = "往來代碼"
        ordering = ["-id"]


class TradeUnit(TenantOwnedModel):
    serial = models.OneToOneField(
        "inventory.ProductSerial", on_delete=models.CASCADE, related_name="trade_unit", verbose_name="那一台")
    price = models.DecimalField("批發價", max_digits=14, decimal_places=2)
    # 賣掉(含批發出貨)之後自動變成沒上架:之後退回來不會自己回到批發清單
    is_listed = models.BooleanField("上架", default=True)
    listed_at = models.DateTimeField("上架時間", null=True, blank=True)
    listed_by = _by("上架的人")
    # 獨立定價(owner:全選之後取消勾選的那幾台獨立定價):價目表怎麼改都不動它。要人明講才會是 True ——
    # 沒有明講的,只要價目表上有符合它的一格就用那一格的價(同型號同機況不會有人以為同價、其實不同價)
    own_price = models.BooleanField("獨立定價", default=False, db_default=False)

    class Meta:
        verbose_name = "中古機上架"
        verbose_name_plural = "中古機上架"
        ordering = ["-id"]
        indexes = [models.Index(fields=["tenant", "is_listed"])]


class TradePriceRule(TenantOwnedModel):
    """中古機價目表的一格:這個型號、這個成色(空的 = 不分)、電池在這個區間(0–100 = 不限)、有沒有備註(空的 = 不分)賣多少。"""

    class Noted(models.TextChoices):
        ANY = "", "不分"
        NO = "no", "沒備註"
        YES = "yes", "有備註"

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="trade_price_rules", verbose_name="型號")
    grade = models.CharField("成色", max_length=2, blank=True, default="", db_default="")
    battery_min = models.PositiveSmallIntegerField("電池最低", default=0, db_default=0)
    battery_max = models.PositiveSmallIntegerField("電池最高", default=100, db_default=100)
    # 備註 = 特殊狀況(owner:特殊狀況特殊價):「沒備註的 A 級 12,000」是一格,有備註的不在這一格裡
    noted = models.CharField("有沒有備註", max_length=3, choices=Noted.choices, blank=True, default="", db_default="")
    price = models.DecimalField("批發價", max_digits=14, decimal_places=2)
    updated_by = _by("改的人")

    class Meta:
        verbose_name = "中古機價目"
        verbose_name_plural = "中古機價目"
        ordering = ["product_id", "grade", "battery_min"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "product", "grade", "battery_min", "battery_max", "noted"], name="uniq_trade_price_rule_cell"),
            models.CheckConstraint(condition=models.Q(battery_min__lte=models.F("battery_max"), battery_max__lte=100),
                                   name="trade_price_rule_battery_range"),
        ]


class TradePriceChange(TenantOwnedModel):
    """一次改價(一群一起改算一次):什麼時候、誰、哪一群、幾台、從多少改成多少。底下 `units` 是動到的每一台。"""

    class What(models.TextChoices):
        RULE = "rule", "改價目"
        PRICE = "price", "改價"
        LIST = "list", "上架"
        UNLIST = "unlist", "下架"
        DROP = "drop", "刪價目"

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="+", verbose_name="型號")
    what = models.CharField("做了什麼", max_length=10, choices=What.choices)
    scope = models.CharField("哪一群", max_length=120, blank=True, default="")
    count = models.PositiveIntegerField("幾台", default=0)
    old_low = models.DecimalField("原本最低", max_digits=14, decimal_places=2, null=True, blank=True)
    old_high = models.DecimalField("原本最高", max_digits=14, decimal_places=2, null=True, blank=True)
    new_low = models.DecimalField("改成最低", max_digits=14, decimal_places=2, null=True, blank=True)
    new_high = models.DecimalField("改成最高", max_digits=14, decimal_places=2, null=True, blank=True)
    by = _by("誰")

    class Meta:
        verbose_name = "改價紀錄"
        verbose_name_plural = "改價紀錄"
        ordering = ["-id"]
        indexes = [models.Index(fields=["tenant", "product", "-id"])]


class TradePriceChangeUnit(TenantOwnedModel):
    change = models.ForeignKey(TradePriceChange, on_delete=models.CASCADE, related_name="units", verbose_name="哪一次")
    serial = models.ForeignKey("inventory.ProductSerial", on_delete=models.CASCADE, related_name="+", verbose_name="那一台")
    # 空的 = 之前沒有價(沒上過架)/ 之後沒有價(下架)
    old_price = models.DecimalField("原本", max_digits=14, decimal_places=2, null=True, blank=True)
    new_price = models.DecimalField("改成", max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "改價紀錄的一台"
        verbose_name_plural = "改價紀錄的一台"
        indexes = [models.Index(fields=["tenant", "serial"])]


class TradeProduct(TenantOwnedModel):
    product = models.OneToOneField(
        "catalog.Product", on_delete=models.CASCADE, related_name="trade_product", verbose_name="商品")
    is_listed = models.BooleanField("開放批發", default=True)
    # 有填 = 每一個同行都是這個價錢;空的 = 門市售價 × 那個同行的折數
    price = models.DecimalField("固定批發價", max_digits=14, decimal_places=2, null=True, blank=True)
    updated_by = _by("改的人")

    class Meta:
        verbose_name = "批發商品"
        verbose_name_plural = "批發商品"
        ordering = ["-id"]
        indexes = [models.Index(fields=["tenant", "is_listed"])]


class TradeOrder(TenantOwnedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "待接單"
        ACCEPTED = "accepted", "已接單"          # 還有沒出的(出過一部分也是這個;給買家看的「部分出貨」是算出來的)
        SHIPPED = "shipped", "已出貨"            # 沒有還要出的了(其餘的出完了或取消了)
        REJECTED = "rejected", "已拒絕"
        CANCELLED = "cancelled", "已取消"        # 一個都沒出就整張取消

    no = models.CharField("單號", max_length=20, blank=True, editable=False)
    partner = models.ForeignKey(TradePartner, on_delete=models.PROTECT, related_name="orders", verbose_name="同行")
    buyer_store = models.CharField("買家的門市", max_length=120, blank=True, default="")
    # 買家每張單自己產的鑰匙:同一把再送回同一張(不會變成兩張)
    buyer_key = models.CharField("買家的鑰匙", max_length=100)
    status = models.CharField("狀況", max_length=10, choices=Status.choices, default=Status.PENDING)
    payment_method = models.CharField("付款方式", max_length=20, blank=True, default="")
    delivery_method = models.CharField("取貨方式", max_length=20, blank=True, default="")
    ship_name = models.CharField("收件人", max_length=60, blank=True, default="")
    ship_phone = models.CharField("收件電話", max_length=40, blank=True, default="")
    ship_address = models.CharField("收件地址", max_length=200, blank=True, default="")
    invoice_type = models.CharField("發票", max_length=10, blank=True, default="")
    buyer_tax_id = models.CharField("統一編號", max_length=20, blank=True, default="")
    buyer_name = models.CharField("發票抬頭", max_length=120, blank=True, default="")
    invoice_email = models.CharField("發票信箱", max_length=200, blank=True, default="")
    note = models.CharField("買家的備註", max_length=200, blank=True, default="")
    accepted_at = models.DateTimeField("接單時間", null=True, blank=True)
    closed_at = models.DateTimeField("結束時間", null=True, blank=True)
    closed_by_buyer = models.BooleanField("買家取消的", default=False)
    close_reason = models.CharField("拒絕 / 取消的原因", max_length=200, blank=True, default="")
    is_test = models.BooleanField("測試單", default=False)
    # 買家看「這個時間之後有變動的單」用;每一次這張單對買家看得到的內容有變就更新
    changed_at = models.DateTimeField("最後變動", auto_now_add=True)

    class Meta:
        verbose_name = "批發單"
        verbose_name_plural = "批發單"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "no"], name="uniq_trade_order_no"),
            models.UniqueConstraint(fields=["tenant", "partner", "buyer_key"], name="uniq_trade_order_buyer_key"),
        ]
        indexes = [models.Index(fields=["tenant", "status", "-id"])]

    def __str__(self) -> str:
        return self.no

    def save(self, *args, **kwargs):
        if not self.no:
            with transaction.atomic():
                self.no = f"TO-{last_doc_seq(TradeOrder, self.tenant, 'TO') + 1:06d}"
        super().save(*args, **kwargs)


class TradeOrderLine(TenantOwnedModel):
    order = models.ForeignKey(TradeOrder, on_delete=models.CASCADE, related_name="lines", verbose_name="批發單")
    line_no = models.PositiveIntegerField("行號", default=1)
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+", verbose_name="商品")
    # 中古機:訂的是哪一台。其他商品是空的
    unit = models.ForeignKey(
        "inventory.ProductSerial", null=True, blank=True, on_delete=models.PROTECT, related_name="trade_lines",
        verbose_name="訂的那一台")
    # 下單當下的品號、品名、這一台的機況(之後商品改名、那一台改備註,這張單不跟著變)
    sku = models.CharField("品號", max_length=60)
    name = models.CharField("品名", max_length=200)
    unit_label = models.CharField("這一台的機況", max_length=120, blank=True, default="")
    qty = models.PositiveIntegerField("數量")
    unit_price = models.DecimalField("單價", max_digits=14, decimal_places=2)
    shipped_qty = models.PositiveIntegerField("已出", default=0)
    cancelled_qty = models.PositiveIntegerField("不出", default=0)
    # 買家回報到現在為止收進庫存幾個(買家每次入庫 / 作廢進貨單之後報整張單現在的樣子)。
    # 買家收進去的貨,賣家不能取消出貨、不能整張銷退(同一批貨不能兩家都在庫;複審第一輪)
    received_qty = models.PositiveIntegerField("買家已收", default=0)
    # 這一行現在還訂著 `unit` 那一台(還沒出、沒取消)。規則在 `orders.py`;一台同時只有一行是 True
    holding = models.BooleanField("訂著那一台", default=False)

    class Meta:
        verbose_name = "批發單明細"
        verbose_name_plural = "批發單明細"
        ordering = ["line_no", "id"]
        constraints = [
            models.UniqueConstraint(fields=["unit"], condition=models.Q(holding=True), name="uniq_trade_line_holding_unit"),
            models.CheckConstraint(
                check=models.Q(qty__gte=models.F("shipped_qty") + models.F("cancelled_qty")), name="trade_line_qty_covers"),
        ]

    @property
    def open_qty(self) -> int:
        return self.qty - self.shipped_qty - self.cancelled_qty


class TradeShipment(TenantOwnedModel):
    order = models.ForeignKey(TradeOrder, on_delete=models.PROTECT, related_name="shipments", verbose_name="批發單")
    no = models.CharField("出貨單號", max_length=30)
    warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT, related_name="+", verbose_name="出貨門市")
    sales_order = models.ForeignKey("sales.SalesOrder", on_delete=models.PROTECT, related_name="trade_shipments", verbose_name="銷貨單")
    # 畫面每開一次出貨產生一把:連按兩下、斷線重送不會出兩次
    request_key = models.CharField("畫面的鑰匙", max_length=50)
    doc_date = models.DateField("出貨日", default=date.today)
    shipping_method = models.CharField("物流", max_length=40, blank=True, default="")
    tracking_no = models.CharField("託運單號", max_length=60, blank=True, default="")
    shipping_fee = models.DecimalField("運費", max_digits=14, decimal_places=2, default=0)
    goods_amount = models.DecimalField("貨款", max_digits=14, decimal_places=2, default=0)
    # 取消出貨:銷貨單跟著作廢、貨回到庫存、那幾行回到還沒出
    is_void = models.BooleanField("取消了", default=False)
    voided_at = models.DateTimeField("取消的時間", null=True, blank=True)
    created_by = _by("出貨的人")

    class Meta:
        verbose_name = "批發出貨"
        verbose_name_plural = "批發出貨"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "request_key"], name="uniq_trade_shipment_request_key"),
            models.UniqueConstraint(fields=["tenant", "no"], name="uniq_trade_shipment_no"),
        ]


class TradeShipmentLine(TenantOwnedModel):
    shipment = models.ForeignKey(TradeShipment, on_delete=models.CASCADE, related_name="lines", verbose_name="出貨")
    line = models.ForeignKey(TradeOrderLine, on_delete=models.PROTECT, related_name="shipped", verbose_name="批發單明細")
    qty = models.PositiveIntegerField("這一次出幾個")

    class Meta:
        verbose_name = "批發出貨明細"
        verbose_name_plural = "批發出貨明細"
        ordering = ["id"]


class TradeShipmentSerial(TenantOwnedModel):
    """這一次出貨的每一台(出貨當下的碼與機況;買家收貨時照這個入庫)。"""

    shipment_line = models.ForeignKey(TradeShipmentLine, on_delete=models.CASCADE, related_name="serials", verbose_name="出貨明細")
    serial = models.ForeignKey("inventory.ProductSerial", on_delete=models.PROTECT, related_name="+", verbose_name="那一台")
    imei = models.CharField("IMEI", max_length=80, blank=True, default="")
    sn = models.CharField("SN", max_length=80, blank=True, default="")
    grade = models.CharField("成色", max_length=2, blank=True, default="")
    battery = models.PositiveSmallIntegerField("電池", null=True, blank=True)
    note = models.CharField("備註", max_length=200, blank=True, default="")
    received = models.BooleanField("買家已收", default=False)        # 買家回報這一台已經入庫

    class Meta:
        verbose_name = "批發出貨序號"
        verbose_name_plural = "批發出貨序號"
        ordering = ["id"]


class TradePayment(TenantOwnedModel):
    partner = models.ForeignKey(TradePartner, on_delete=models.PROTECT, related_name="payments", verbose_name="同行")
    amount = models.DecimalField("收到多少", max_digits=14, decimal_places=2)
    received_on = models.DateField("哪一天收到", default=date.today)
    method = models.CharField("怎麼收的", max_length=20, blank=True, default="")
    note = models.CharField("備註", max_length=200, blank=True, default="")
    # 畫面每記一筆產生一把:連按兩下不會記兩筆
    request_key = models.CharField("畫面的鑰匙", max_length=50)
    is_void = models.BooleanField("作廢", default=False)
    created_by = _by("記的人")

    class Meta:
        verbose_name = "批發收款"
        verbose_name_plural = "批發收款"
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["tenant", "request_key"], name="uniq_trade_payment_request_key")]
