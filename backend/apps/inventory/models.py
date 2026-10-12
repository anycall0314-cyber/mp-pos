from django.conf import settings
from django.db import models

from apps.core.models import TenantOwnedModel


class Warehouse(TenantOwnedModel):
    """倉庫 / 門市。"""

    code = models.SlugField("倉庫代碼", max_length=40)
    name = models.CharField("倉庫名稱", max_length=120)
    address = models.CharField("地址", max_length=200, blank=True)
    phone = models.CharField("電話", max_length=40, blank=True)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_warehouse_tenant_code"),
        ]
        ordering = ["code"]
        verbose_name = "倉庫"
        verbose_name_plural = "倉庫"

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class ProductSerial(TenantOwnedModel):
    """單台實體機。3C 系統的真正庫存單位。"""

    class Status(models.TextChoices):
        IN_STOCK = "in_stock", "在庫"
        IN_TRANSIT = "in_transit", "調撥中"
        SOLD = "sold", "已售"
        RETURNED = "returned", "已退"
        RMA = "rma", "維修中"
        VOID = "void", "作廢"
        # 盤點時帳上在庫、現場沒有,管理員核准之後標成這個(2026-10-12)。不算在庫、不能賣;
        # **還佔著它的碼**(跟作廢不一樣:找到了可以按「找回」變回在庫,所以同一個 IMEI 不能再進一次貨)
        LOST = "lost", "盤虧"

    class ConditionGrade(models.TextChoices):
        S = "S", "S 級 媲美新機 / 拆封未使用"
        A = "A", "A 級 95%新以上 幾乎無痕"
        B = "B", "B 級 85-95%新 輕微使用痕跡"
        C = "C", "C 級 70-85%新 明顯刮痕 功能正常"
        D = "D", "D 級 功能有瑕疵或需報備"

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="serials",
        verbose_name="商品",
    )
    serial_no = models.CharField("序號 (IMEI/SN)", max_length=80)
    serial_key = models.CharField(
        "比對用的主碼", max_length=80, blank=True, default="", editable=False,
        help_text="serial_no 去掉空白 / 破折號 / 底線 / 點、轉大寫;存檔時自動算。"
                  "用碼找設備、檢查碼有沒有被用掉都比這一欄,不比原文",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="serials",
        null=True,
        blank=True,
        verbose_name="所在倉庫",
        help_text="目前位置;已售 / 作廢後可能為空",
    )
    status = models.CharField(
        "狀態",
        max_length=20,
        choices=Status.choices,
        default=Status.IN_STOCK,
    )
    purchase_unit_cost = models.DecimalField(
        "採購單位成本",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="landed cost 攤提後的真實採購單位成本",
    )
    purchase_order_item = models.ForeignKey(
        "purchasing.PurchaseOrderItem",
        on_delete=models.PROTECT,
        related_name="serials",
        null=True,
        blank=True,
        verbose_name="進貨明細",
    )

    # 中古機專用欄位 (Product.is_secondhand=True 才會填)
    condition_grade = models.CharField(
        "成色等級",
        max_length=2,
        choices=ConditionGrade.choices,
        blank=True,
        default="",
        help_text="中古機適用,新機留空",
    )
    custom_unit_price = models.DecimalField(
        "自定售價",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="中古機一機一價;銷貨時優先帶這個,空則帶 Product.list_price",
    )
    battery_health = models.PositiveSmallIntegerField(
        "電池健康度 (%)",
        null=True,
        blank=True,
        help_text="0-100;iOS 機填,Android 機可留空",
    )
    condition_note = models.CharField(
        "成色備註",
        max_length=200,
        blank=True,
        help_text="刮痕位置 / 配件齊全度 / 其他特殊狀況",
    )
    acquired_from_member = models.ForeignKey(
        "parties.Member",
        on_delete=models.PROTECT,
        related_name="acquired_serials",
        null=True,
        blank=True,
        verbose_name="收購來源會員",
        help_text="從個人會員收購的中古機,記錄賣家;廠商來源留空",
    )
    acquired_via_sales_order = models.ForeignKey(
        "sales.SalesOrder",
        on_delete=models.PROTECT,
        related_name="acquired_serials",
        null=True,
        blank=True,
        verbose_name="收購對應銷貨單",
        help_text="個人收購對應的「收購二手」銷貨單(記錄付款給賣家)",
    )

    received_at = models.DateTimeField("進貨時間", null=True, blank=True)
    sold_at = models.DateTimeField("銷售時間", null=True, blank=True)

    class Meta:
        constraints = [
            # 作廢的設備不佔碼:進貨單打錯整張作廢之後,同一批貨要能用同樣的碼重新入庫。
            # (作廢的那一筆留著 serial_no 當紀錄,識別碼表裡的登記在作廢時就拿掉了。)
            models.UniqueConstraint(
                fields=["tenant", "serial_no"], condition=~models.Q(status="void"),
                name="uniq_serial_tenant_no",
            ),
        ]
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["product", "status"]),
            models.Index(fields=["warehouse", "status"]),
            models.Index(fields=["tenant", "serial_key"]),
        ]
        verbose_name = "商品序號"
        verbose_name_plural = "商品序號"

    def __str__(self) -> str:
        return self.serial_no

    def save(self, *args, **kwargs):
        # serial_key 永遠跟著 serial_no:同一個碼不管寫成 AB12、ab-12 還是 A.B_12,比對時都是同一個。
        # (改主碼一律走 save();不要用 queryset.update(serial_no=…),那樣 serial_key 不會跟著變。)
        from apps.identity.normalize import normalize_serial

        self.serial_key = normalize_serial(self.serial_no)
        fields = kwargs.get("update_fields")
        if fields is not None and "serial_no" in fields and "serial_key" not in fields:
            kwargs["update_fields"] = [*fields, "serial_key"]
        super().save(*args, **kwargs)


class ProductSerialIdentifier(TenantOwnedModel):
    """一台裝置的多組識別碼(IMEI / IMEI2 / EID / SN)。

    `ProductSerial.serial_no` 存依政策選出的主序號;這裡保存完整識別碼清單,
    支援雙 SIM / eSIM。整租戶內識別碼值不重複。
    """

    class Kind(models.TextChoices):
        PRIMARY_SERIAL = "primary_serial", "主序號"
        IMEI = "imei", "IMEI"
        IMEI2 = "imei2", "IMEI2"
        EID = "eid", "EID"
        SN = "sn", "SN"

    serial = models.ForeignKey(
        ProductSerial, on_delete=models.CASCADE, related_name="identifiers",
        verbose_name="商品序號",
    )
    kind = models.CharField("類型", max_length=16, choices=Kind.choices)
    value = models.CharField("原始值", max_length=80)
    normalized_value = models.CharField("比對鍵", max_length=80, db_index=True)
    is_primary = models.BooleanField("主識別碼", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "normalized_value"], name="uniq_serial_identifier_value"
            ),
        ]
        indexes = [models.Index(fields=["tenant", "normalized_value"])]
        ordering = ["serial", "-is_primary", "kind"]
        verbose_name = "序號識別碼"
        verbose_name_plural = "序號識別碼"

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}"


class ProductSerialCodeChange(TenantOwnedModel):
    """設備的 IMEI / SN 事後被補登或修改的紀錄(誰、什麼時候、從什麼改成什麼)。

    只增不改。改碼等於改這一台「是哪一台」,沒有紀錄的話換機、冒用查不出來。
    操作的人存當下的帳號名稱(不是外鍵):帳號之後被刪、或還原到別的環境,紀錄都還看得懂。
    """

    serial = models.ForeignKey(
        ProductSerial, on_delete=models.CASCADE, related_name="code_changes",
        verbose_name="商品序號",
    )
    before_imei = models.CharField("原 IMEI", max_length=80, blank=True)
    before_sn = models.CharField("原 SN", max_length=80, blank=True)
    after_imei = models.CharField("新 IMEI", max_length=80, blank=True)
    after_sn = models.CharField("新 SN", max_length=80, blank=True)
    changed_by = models.CharField("操作帳號", max_length=150, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["serial", "-created_at"])]
        verbose_name = "序號修改紀錄"
        verbose_name_plural = "序號修改紀錄"

    def __str__(self) -> str:
        return f"{self.serial_id}:{self.before_imei}/{self.before_sn}→{self.after_imei}/{self.after_sn}"


class StockBalance(TenantOwnedModel):
    """非序號商品(配件)的倉別庫存餘額。每個 (商品, 倉庫) 一筆。

    序號商品的庫存仍以 ProductSerial 為單位,不寫這個表。
    """

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="balances",
        verbose_name="商品",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="balances",
        verbose_name="倉庫",
    )
    qty = models.PositiveIntegerField("在庫數量", default=0)
    weighted_avg_cost = models.DecimalField(
        "加權平均成本(未稅)",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="本倉本商品的加權平均;進貨累計,銷貨/調撥不重算",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "product", "warehouse"],
                name="uniq_stockbalance_product_warehouse",
            ),
        ]
        ordering = ["product__sku", "warehouse__code"]
        indexes = [
            models.Index(fields=["tenant", "product"]),
            models.Index(fields=["tenant", "warehouse"]),
        ]
        verbose_name = "庫存餘額"
        verbose_name_plural = "庫存餘額"

    def __str__(self) -> str:
        return f"{self.product_id}@{self.warehouse_id}:{self.qty}"


class StockMovement(TenantOwnedModel):
    """庫存異動軌跡。每次序號狀態 / 位置變動都寫一筆。"""

    class MovementType(models.TextChoices):
        PURCHASE_IN = "purchase_in", "進貨入庫"
        TRADE_IN = "trade_in", "中古收購入庫"
        SALE_OUT = "sale_out", "銷貨出庫"
        TRANSFER_OUT = "transfer_out", "調撥出庫"
        TRANSFER_IN = "transfer_in", "調撥入庫"
        RETURN_IN = "return_in", "退貨入庫"
        REPAIR_USAGE = "repair_usage", "維修領用"
        PARTS_TRANSFER = "parts_transfer", "零件調貨"
        ADJUST = "adjust", "盤點調整"
        VOID = "void", "作廢"

    serial = models.ForeignKey(
        ProductSerial,
        on_delete=models.PROTECT,
        related_name="movements",
        null=True,
        blank=True,
        verbose_name="序號",
        help_text="序號商品填這欄;配件批量異動留空",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="batch_movements",
        null=True,
        blank=True,
        verbose_name="商品",
        help_text="配件批量異動填這欄;序號商品由 serial 帶出可留空",
    )
    qty = models.PositiveIntegerField(
        "數量",
        default=1,
        help_text="序號商品=1;配件=該次批量",
    )
    movement_type = models.CharField("異動類型", max_length=20, choices=MovementType.choices)
    from_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        verbose_name="來源倉",
    )
    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        verbose_name="目的倉",
    )
    ref_doc_type = models.CharField(
        "來源單據類型",
        max_length=40,
        blank=True,
        help_text="purchase_order / sales_order / transfer_order ...",
    )
    ref_doc_id = models.BigIntegerField("來源單據 ID", null=True, blank=True)
    note = models.CharField("備註", max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["serial", "-created_at"]),
            models.Index(fields=["ref_doc_type", "ref_doc_id"]),
            # 進銷存表、異動查詢:照公司、照時間找(期間內的每一筆)
            models.Index(fields=["tenant", "created_at"], name="stockmove_tenant_time"),
        ]
        verbose_name = "庫存異動"
        verbose_name_plural = "庫存異動"

    def __str__(self) -> str:
        return f"{self.movement_type} {self.serial_id} @ {self.created_at:%Y-%m-%d %H:%M}"


class StockCount(TenantOwnedModel):
    """盤點單:一家門市盤一次(可以只盤幾個類別)。規則在 `stockcount.py`。

    owner 2026-10-12 定的三條:差異要管理員調整與核准(盤的人只記數到的,**核准才動庫存**);
    帶序號的逐台刷;盤點中可以繼續開單(所以每一列記的是「輸入那一刻」的帳上數量)。
    """

    class Status(models.TextChoices):
        COUNTING = "counting", "盤點中"
        SUBMITTED = "submitted", "待核准"
        APPROVED = "approved", "已核准"
        VOID = "void", "已作廢"

    no = models.CharField("盤點單號", max_length=20, blank=True, editable=False)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+", verbose_name="門市")
    status = models.CharField("狀態", max_length=12, choices=Status.choices, default=Status.COUNTING)
    note = models.CharField("備註", max_length=200, blank=True)
    # 送出的人有沒有表明「這個範圍的手機全部刷完了」。有才算手機少了哪幾台;沒有 = 手機這次只是刷了一部分,
    # 沒刷到的是「沒盤」不是「少了」(動手前紅隊第 1 條:只刷了櫃台、保險櫃沒刷就送出,不能整櫃都變盤虧)
    phones_done = models.BooleanField("手機全部刷完了", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="開單的人")
    submitted_at = models.DateTimeField("送出時間", null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="送出的人")
    approved_at = models.DateTimeField("核准時間", null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="核准的人")

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "no"], name="uniq_stockcount_no"),
            # 同一家門市同時只有一張還沒結束的(盤點中 / 待核准):兩個人同時開也只會成一張
            models.UniqueConstraint(
                fields=["tenant", "warehouse"], condition=models.Q(status__in=["counting", "submitted"]),
                name="uniq_stockcount_open_per_warehouse"),
        ]
        verbose_name = "盤點單"
        verbose_name_plural = "盤點單"

    def __str__(self) -> str:
        return self.no or f"盤點單#{self.pk}"


class StockCountCategory(TenantOwnedModel):
    """這張盤點單只盤這個類別(一列一個;一列都沒有 = 這家門市全部的類別)。
    自己一張表、帶著公司那一欄:公司備份才帶得走(Django 自動產生的多對多關聯表不會被備份)。"""

    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="scope", verbose_name="盤點單")
    category = models.ForeignKey("catalog.Category", on_delete=models.PROTECT, related_name="+", verbose_name="類別")

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["count", "category"], name="uniq_stockcountcategory")]
        verbose_name = "盤點範圍"
        verbose_name_plural = "盤點範圍"


class StockCountLine(TenantOwnedModel):
    """配件一個商品一列:數到幾個、輸入那一刻帳上幾個。核准時管理員可以改調整量或先不調。"""

    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines", verbose_name="盤點單")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+", verbose_name="商品")
    counted_qty = models.PositiveIntegerField("數到的數量")
    # 輸入的那一刻帳上是多少(盤點中照常開單,之後賣掉的是正常的異動,不算差異)
    book_qty = models.PositiveIntegerField("當時帳上的數量")
    counted_at = models.DateTimeField("輸入時間")
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="盤的人")
    # 核准時定下來的:實際調了多少(可以跟「數到的 − 當時帳上的」不一樣)、這一列先不調、原因、當下的平均成本
    adjust_qty = models.IntegerField("調整的數量", null=True, blank=True)
    skipped = models.BooleanField("先不調", default=False)
    reason = models.CharField("原因", max_length=100, blank=True)
    unit_cost = models.DecimalField("核准當下的平均成本", max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["count", "product"], name="uniq_stockcountline_product")]
        verbose_name = "盤點明細"
        verbose_name_plural = "盤點明細"


class StockCountScan(TenantOwnedModel):
    """手機逐台刷到的碼(一個碼一列)。記下刷的那一刻那一台在帳上是什麼樣子。"""

    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="scans", verbose_name="盤點單")
    code = models.CharField("刷到的碼", max_length=80)
    code_key = models.CharField("比對鍵", max_length=80)
    # 系統認得的那一台;不認得(打錯、沒有進過貨)= 空的
    serial = models.ForeignKey(
        ProductSerial, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="序號")
    # 刷的那一刻:那一台帳上是不是就在這家門市(在庫 / 已退待處理)。不是的就是「多出來的」,只列出來不自動處理
    here = models.BooleanField("當時帳上在這家門市", default=False)
    state = models.CharField("當時的狀態", max_length=16, blank=True)
    scanned_at = models.DateTimeField("刷的時間")
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="刷的人")

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["count", "code_key"], name="uniq_stockcountscan_code")]
        verbose_name = "盤點刷碼"
        verbose_name_plural = "盤點刷碼"


class StockCountMissing(TenantOwnedModel):
    """送出時算出來的「帳上在這家門市在庫、但沒刷到」的手機。管理員決定調不調;核准之後找到了可以找回。"""

    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="missing", verbose_name="盤點單")
    serial = models.ForeignKey(ProductSerial, on_delete=models.PROTECT, related_name="+", verbose_name="序號")
    skipped = models.BooleanField("先不調", default=False)
    reason = models.CharField("原因", max_length=100, blank=True)
    # 核准時真的改成盤虧了(核准當下已經不在庫的不會改)
    applied = models.BooleanField("已標成盤虧", default=False)
    found_at = models.DateTimeField("找回時間", null=True, blank=True)
    found_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="找回的人")

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["count", "serial"], name="uniq_stockcountmissing_serial")]
        verbose_name = "盤虧序號"
        verbose_name_plural = "盤虧序號"
