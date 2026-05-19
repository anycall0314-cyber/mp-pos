from django.db import models

from apps.core.models import TenantOwnedModel


class Warehouse(TenantOwnedModel):
    """倉庫 / 門市。"""

    code = models.SlugField("倉庫代碼", max_length=40)
    name = models.CharField("倉庫名稱", max_length=120)
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
        "parties.Customer",
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


class StockMovement(TenantOwnedModel):
    """庫存異動軌跡。每次序號狀態 / 位置變動都寫一筆。"""

    class MovementType(models.TextChoices):
        PURCHASE_IN = "purchase_in", "進貨入庫"
        TRADE_IN = "trade_in", "中古收購入庫"
        SALE_OUT = "sale_out", "銷貨出庫"
        TRANSFER_OUT = "transfer_out", "調撥出庫"
        TRANSFER_IN = "transfer_in", "調撥入庫"
        RETURN_IN = "return_in", "退貨入庫"
        ADJUST = "adjust", "盤點調整"
        VOID = "void", "作廢"

    serial = models.ForeignKey(
        ProductSerial,
        on_delete=models.PROTECT,
        related_name="movements",
        verbose_name="序號",
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
