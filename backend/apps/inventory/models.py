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
            models.UniqueConstraint(fields=["tenant", "serial_no"], name="uniq_serial_tenant_no"),
        ]
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["product", "status"]),
            models.Index(fields=["warehouse", "status"]),
        ]
        verbose_name = "商品序號"
        verbose_name_plural = "商品序號"

    def __str__(self) -> str:
        return self.serial_no


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
        ]
        verbose_name = "庫存異動"
        verbose_name_plural = "庫存異動"

    def __str__(self) -> str:
        return f"{self.movement_type} {self.serial_id} @ {self.created_at:%Y-%m-%d %H:%M}"
