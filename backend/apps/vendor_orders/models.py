"""廠商叫貨:在 POS 裡直接跟供應商叫貨(第一家是膜總裁 B2B)。

- `VendorCategory` / `Vendor`:**平台的名單,不屬於任何公司**(只有平台管理員能改):有哪些叫貨類別、招進來哪些廠商、
  每家廠商怎麼接(對方的網址…)。招到一家 = 加一筆,不用改程式。**不進公司備份**;公司的資料只記廠商的代碼(`provider`),不用外鍵指過來
  (備份檔會搬到別台,那邊的編號不一樣)。只能停用、不能刪。
- `VendorItem`:半自動廠商的**價目表**(平台幫廠商建的;所有店家看到同一份;也不進公司備份)。全自動的廠商沒有這張表的資料(商品清單是現問它的系統)。
- `VendorLink`:一家門市 × 一家廠商的串接設定(預設的付款方式、收件、發票)。**金鑰不在這張表**。
- `VendorSecret`:那把金鑰(加密過的)。另外一張表是因為它**不進公司備份**:備份檔會被帶走、搬到別台,
  外部系統的下單金鑰不該跟著走。還原之後要請管理員重新貼。
- `VendorOrder` / `VendorOrderItem`:一張叫貨單。價錢是叫貨當下廠商報的,**只是當下的牌價**;
  到貨入庫時以廠商那張單當下的明細為準。
- `VendorReceipt` / `VendorReceiptItem`:一次到貨入庫 = 一張進貨單。一張叫貨單可以分好幾次入庫(部分出貨、少到貨);
  進貨單之後被作廢,那一次就不算(那幾片回到「還沒入庫」)。
"""
from django.conf import settings
from django.db import models

from apps.core.models import TenantOwnedModel, TimestampedModel

MOCEO = "moceo"         # 第一家廠商的代碼(資料庫變更會把它放進名單)


class VendorCategory(TimestampedModel):
    """平台定的叫貨類別(保護貼、配件、維修零件…)。**只用來篩廠商**:同一家廠商掛幾個類別都是同一個入口、同一份購物車。
    停用 = 叫貨頁不顯示這個類別;要停叫貨是停廠商(紅隊 2026-10-10)。"""

    name = models.CharField("名稱", max_length=20, unique=True)
    sort_order = models.PositiveIntegerField("排序", default=0)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        verbose_name = "叫貨類別"
        verbose_name_plural = "叫貨類別"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.name


class Vendor(TimestampedModel):
    """平台招進來的一家廠商。"""

    class Protocol(models.TextChoices):
        # 全自動:對方有下單系統,照「標準格式」(膜總裁 B2B 對外下單 API v1 那一套)講話 —— 見 standard.py
        STANDARD = "standard", "全自動(標準格式)"
        # 半自動:廠商沒有可以接的系統(多半是租來的進銷存,沒有串接功能)。商品與參考價由平台建價目表;
        # 叫貨單在 POS 自己成立、由人傳給廠商(複製貼 LINE / 寄信);進度靠人記;到貨照店家叫的那張單入庫。廠商那邊什麼都不用改。
        MANUAL = "manual", "半自動(人工傳單)"

    # 代碼建了不能改:公司的串接、叫貨單、料號對照都靠它認
    code = models.SlugField("代碼", max_length=20, unique=True)
    name = models.CharField("名稱", max_length=40)
    categories = models.ManyToManyField(VendorCategory, blank=True, related_name="vendors", verbose_name="類別")
    protocol = models.CharField("怎麼接", max_length=20, choices=Protocol.choices, default=Protocol.STANDARD)
    # 對方系統的網址。**金鑰只會送到這個網址**,所以只有平台管理員能改、而且一定要 https(API 那一層檢查)
    api_base = models.CharField("對方的網址", max_length=200, blank=True, default="")
    # 這家的金鑰固定的開頭(有填才檢查):擋掉貼錯的東西(別的密碼)被送去問廠商
    key_prefix = models.CharField("金鑰的開頭", max_length=20, blank=True, default="")
    # 半自動的廠商用:接單信箱(有填才寄信;沒填就只靠店員複製貼給廠商)、給店員看的聯絡方式(例:LINE @xxx)
    order_email = models.CharField("接單信箱", max_length=200, blank=True, default="")
    contact = models.CharField("聯絡方式", max_length=120, blank=True, default="")
    # 停用:不能叫新的貨、不能貼新金鑰;已經叫的單照樣看得到、照樣可以重送與到貨入庫
    is_active = models.BooleanField("啟用", default=True)
    sort_order = models.PositiveIntegerField("排序", default=0)

    class Meta:
        verbose_name = "叫貨廠商"
        verbose_name_plural = "叫貨廠商"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class VendorItem(TimestampedModel):
    """半自動廠商價目表上的一項(平台的資料)。只能停用、不能刪:各家門市的叫貨單與料號對照靠 `sku` 認它。
    `ref_price` 是**參考價**:實際付多少以到貨入庫時填的為準(廠商沒有系統可以對)。可以是空的(沒報價也可以叫)。"""

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="items", verbose_name="廠商")
    # 料號建了不能改;平台沒填就由系統給一個(N0001…)
    sku = models.CharField("料號", max_length=80)
    name = models.CharField("品名", max_length=200)
    spec = models.CharField("規格", max_length=120, blank=True, default="")
    kind = models.CharField("種類", max_length=40, blank=True, default="")
    unit = models.CharField("單位", max_length=10, blank=True, default="")
    pack_qty = models.PositiveIntegerField("一包幾個", default=1)
    ref_price = models.DecimalField("參考單價", max_digits=14, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField("啟用", default=True)
    sort_order = models.PositiveIntegerField("排序", default=0)

    class Meta:
        verbose_name = "廠商價目"
        verbose_name_plural = "廠商價目"
        ordering = ["sort_order", "id"]
        constraints = [models.UniqueConstraint(fields=["vendor", "sku"], name="uniq_vendor_item_sku")]

    def __str__(self) -> str:
        return f"{self.vendor_id} {self.sku} {self.name}"


class VendorLink(TenantOwnedModel):
    provider = models.CharField("廠商代碼", max_length=20)          # = Vendor.code
    warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.PROTECT, related_name="vendor_links", verbose_name="門市",
    )
    # 叫貨時預設帶的;收件與發票店員不能改(改得到的話,貨可以寄到任何地方)
    payment_method = models.CharField("付款方式", max_length=20, default="月結")
    delivery_method = models.CharField("取貨方式", max_length=20, default="宅配")
    ship_name = models.CharField("收件人", max_length=60, blank=True, default="")
    ship_phone = models.CharField("收件電話", max_length=40, blank=True, default="")
    ship_address = models.CharField("收件地址", max_length=200, blank=True, default="")
    invoice_type = models.CharField("發票", max_length=10, default="個人")
    buyer_tax_id = models.CharField("統一編號", max_length=20, blank=True, default="")
    buyer_name = models.CharField("發票抬頭", max_length=120, blank=True, default="")
    invoice_email = models.CharField("發票信箱", max_length=200, blank=True, default="")
    # 到貨入庫開的進貨單記在哪一個供應商底下(店裡自己的那一筆);沒指定過就自動用 / 建一筆跟廠商同名的
    supplier = models.ForeignKey(
        "parties.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+", verbose_name="供應商",
    )
    # 運費要不要算進入庫成本:每家門市固定一種做法,由管理員定(不是入庫的人每次勾 ——
    # 不然同一家店的成本一下含運費、一下不含,只差誰按;紅隊 2026-10-10)
    freight_into_cost = models.BooleanField("運費算進成本", default=True)
    # 這家門市的店員能不能跟這家廠商叫貨(管理員一律可以)。員工帳號的「廠商叫貨」是總開關,這一格是每家廠商各自的:
    # 不然開通高單價的零件廠之後,要嘛店員也能跟它下大單,要嘛連保護貼都不能叫(紅隊 2026-10-10)
    clerk_ordering = models.BooleanField("店員也可以叫貨", default=True)
    # 半自動的廠商沒有金鑰:管理員按了「開通」這家門市才叫得了(全自動的看的是有沒有金鑰,這一格不看)
    opened = models.BooleanField("開通(半自動的廠商)", default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = "叫貨串接"
        verbose_name_plural = "叫貨串接"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "provider", "warehouse"], name="uniq_vendor_link_store"),
        ]


class VendorSecret(TenantOwnedModel):
    """加密過的金鑰。**不進公司備份**(registry:EXCLUDED + 還原前清掉)。任何 API 都不回這張表的內容。"""

    link = models.OneToOneField(VendorLink, on_delete=models.CASCADE, related_name="secret")
    wrapped = models.TextField("加密過的金鑰")
    hint = models.CharField("前幾碼", max_length=20)                 # 給管理員認是哪一把
    fingerprint = models.CharField("指紋", max_length=64)            # 看兩把是不是同一把(不能逆推)
    # 廠商說這一把是不是沙盒(測試)金鑰;None = 廠商沒有講。存的時候問一次,之後每次跟廠商要清單時跟著更新
    sandbox = models.BooleanField("沙盒金鑰", null=True, blank=True)
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = "叫貨金鑰"
        verbose_name_plural = "叫貨金鑰"


class VendorOrder(TenantOwnedModel):
    class State(models.TextChoices):
        SENDING = "sending", "送出中"
        PLACED = "placed", "已成立"
        # 送出去了但沒有拿到明確的答覆(斷線、逾時、對方出錯):不知道有沒有成立。
        # 只能用同一把鑰匙再送一次 —— 成立過會拿到同一個單號,不會變成兩張。
        UNKNOWN = "unknown", "不確定"

    class Source(models.TextChoices):
        POS = "pos", "從這裡叫的"
        # 不是從 POS 叫的(電話、LINE、廠商後台代下):貨到了要入庫時才認進來,明細一律跟廠商要
        OUTSIDE = "outside", "不是從這裡叫的"

    provider = models.CharField("廠商代碼", max_length=20)          # = Vendor.code
    link = models.ForeignKey(VendorLink, on_delete=models.PROTECT, related_name="orders")
    source = models.CharField("哪裡叫的", max_length=10, choices=Source.choices, default=Source.POS)
    # 到貨時對不上的事(送錯規格、少一包…):這幾行先不入庫,記一句讓老闆看得到
    issue_note = models.CharField("到貨問題", max_length=300, blank=True, default="")
    warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.PROTECT, related_name="vendor_orders", verbose_name="門市",
    )
    # 畫面每開一張新的叫貨單自己產生;送給廠商的那一把(vendor_key)由它固定算出來,
    # 所以這一列萬一沒留下,畫面拿同一把再送,廠商那邊仍然認得是同一張。
    request_key = models.CharField("畫面的鑰匙", max_length=50)
    vendor_key = models.CharField("送給廠商的鑰匙", max_length=100)
    # 第一次送出時用的是哪一把金鑰:廠商的防重複是「同一把金鑰 + 同一把鑰匙」,金鑰換過就不能再用重送來確認
    key_fingerprint = models.CharField("送出時的金鑰指紋", max_length=64, blank=True, default="")
    state = models.CharField("狀況", max_length=12, choices=State.choices, default=State.SENDING)
    sending_since = models.DateTimeField("開始送出", null=True, blank=True)
    problem = models.CharField("不確定的原因", max_length=300, blank=True, default="")

    vendor_order_no = models.CharField("廠商單號", max_length=40, blank=True, default="", db_index=True)
    total_amount = models.DecimalField("廠商算的總額", max_digits=14, decimal_places=2, null=True, blank=True)
    shipping_fee = models.DecimalField("運費", max_digits=14, decimal_places=2, null=True, blank=True)
    expected_goods = models.DecimalField("叫貨當下的貨款", max_digits=14, decimal_places=2, default=0)
    # 廠商回的總額 − 運費 是不是等於叫貨當下的貨款;對不上代表廠商那邊的價錢跟畫面看到的不一樣
    amount_matches = models.BooleanField("金額對得上", null=True, blank=True)
    # 廠商說這張是測試單(沙盒金鑰下的:不預留庫存、不進廠商的報表);None = 廠商沒有講
    is_test = models.BooleanField("測試單", null=True, blank=True)

    payment_method = models.CharField("付款方式", max_length=20)
    delivery_method = models.CharField("取貨方式", max_length=20)
    ship_name = models.CharField("收件人", max_length=60, blank=True, default="")
    ship_phone = models.CharField("收件電話", max_length=40, blank=True, default="")
    ship_address = models.CharField("收件地址", max_length=200, blank=True, default="")
    invoice_type = models.CharField("發票", max_length=10)
    buyer_tax_id = models.CharField("統一編號", max_length=20, blank=True, default="")
    buyer_name = models.CharField("發票抬頭", max_length=120, blank=True, default="")
    invoice_email = models.CharField("發票信箱", max_length=200, blank=True, default="")
    note = models.CharField("備註", max_length=200, blank=True, default="")

    # 廠商那邊的進度(原樣顯示,不翻譯);按「更新進度」才會換
    vendor_status = models.CharField("訂單狀態", max_length=40, blank=True, default="")
    vendor_payment_status = models.CharField("收款狀況", max_length=40, blank=True, default="")
    vendor_logistics_status = models.CharField("物流狀況", max_length=60, blank=True, default="")
    vendor_shipping_method = models.CharField("物流", max_length=40, blank=True, default="")
    vendor_tracking_no = models.CharField("託運單號", max_length=60, blank=True, default="")
    vendor_ordered_at = models.DateTimeField("廠商收單時間", null=True, blank=True)
    status_checked_at = models.DateTimeField("進度更新時間", null=True, blank=True)

    # 這張單是 POS 自己成立的(半自動的廠商):沒有送給任何系統,單號是 POS 編的;明細、進度、到貨都以 POS 這邊記的為準。
    # 記在單上、不是每次去看廠商現在怎麼接:廠商之後改成全自動,這些舊單還是照人工的那一套走
    manual = models.BooleanField("POS 自己成立的(半自動)", default=False)
    # ── 半自動廠商的叫貨單才用的三件事 ──
    # 傳給廠商了沒:這張單是 POS 自己成立的,要有人把內容貼給 / 寄給廠商才算數(沒傳的在紀錄上標出來)
    sent_at = models.DateTimeField("傳給廠商的時間", null=True, blank=True)
    sent_how = models.CharField("怎麼傳的", max_length=10, blank=True, default="")      # manual = 人按的 / email = 系統寄的
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="傳的人",
    )
    # 進度靠人記一句(廠商沒有系統可以查)
    progress_note = models.CharField("進度備註", max_length=200, blank=True, default="")
    # 取消只是 POS 這邊的標記(要自己跟廠商講);可以恢復;貨還是到了照樣入得了庫
    cancelled_at = models.DateTimeField("取消的時間", null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="取消的人",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name="叫貨的人",
    )

    class Meta:
        verbose_name = "叫貨單"
        verbose_name_plural = "叫貨單"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "request_key"], name="uniq_vendor_order_request_key"),
            # 廠商的同一張單在這家公司只會有一筆(兩家門市共用金鑰時,不能各認一次、各入一次庫)
            models.UniqueConstraint(
                fields=["tenant", "provider", "vendor_order_no"], condition=~models.Q(vendor_order_no=""),
                name="uniq_vendor_order_no",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "warehouse", "-id"])]


class VendorOrderItem(TenantOwnedModel):
    order = models.ForeignKey(VendorOrder, on_delete=models.CASCADE, related_name="items")
    line_no = models.PositiveIntegerField("行號", default=1)
    sku = models.CharField("廠商料號", max_length=80)
    spec_id = models.IntegerField("規格編號", null=True, blank=True)
    spec_label = models.CharField("規格", max_length=120, blank=True, default="")
    name = models.CharField("廠商品名", max_length=200)
    unit = models.CharField("單位", max_length=10, blank=True, default="")
    pack_qty = models.PositiveIntegerField("一包幾個")
    packs = models.PositiveIntegerField("包數")
    qty = models.PositiveIntegerField("數量")            # = 包數 × 一包幾個;送給廠商的是這個
    # 半自動廠商的是參考價,可以是空的(沒報價也可以叫;實際單價到貨入庫時填)
    unit_price = models.DecimalField("叫貨當下的單價", max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "叫貨明細"
        verbose_name_plural = "叫貨明細"
        ordering = ["line_no", "id"]


class VendorReceipt(TenantOwnedModel):
    """一次到貨入庫。它開出來的進貨單才是庫存與成本的帳;這裡只記「這張叫貨單的哪幾行、這一次入了幾個」。"""

    order = models.ForeignKey(VendorOrder, on_delete=models.PROTECT, related_name="receipts")
    purchase_order = models.ForeignKey(
        "purchasing.PurchaseOrder", on_delete=models.PROTECT, related_name="+", verbose_name="進貨單",
    )
    # 畫面每開一次入庫產生一把:連按兩下、斷線重送不會入兩次
    request_key = models.CharField("畫面的鑰匙", max_length=50)
    freight = models.DecimalField("這一次算進成本的運費", max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name="入庫的人",
    )

    class Meta:
        verbose_name = "到貨入庫"
        verbose_name_plural = "到貨入庫"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "request_key"], name="uniq_vendor_receipt_request_key"),
        ]


class VendorReceiptItem(TenantOwnedModel):
    receipt = models.ForeignKey(VendorReceipt, on_delete=models.CASCADE, related_name="items")
    sku = models.CharField("廠商料號", max_length=80)
    spec_id = models.IntegerField("規格編號", null=True, blank=True)
    is_reissue = models.BooleanField("瑕疵補發(免費)", default=False)
    name = models.CharField("廠商品名", max_length=200, blank=True, default="")
    qty = models.PositiveIntegerField("這一次入庫幾個")
    unit_price = models.DecimalField("廠商的單價", max_digits=14, decimal_places=2)      # 不含運費
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+", verbose_name="入到哪個品號")

    class Meta:
        verbose_name = "到貨入庫明細"
        verbose_name_plural = "到貨入庫明細"
        ordering = ["id"]
