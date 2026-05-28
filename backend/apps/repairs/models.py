"""維修模組 model。

- RepairItem:維修項目模板(螢幕更換 / 電池更換 等)
- RepairItemModel:項目綁定的機型 keys(跨同款 SKU)
- RepairItemPart:項目預設所需零件清單 + 數量
- RepairOrder:維修單(自修 / 委外 雙模式)
- RepairOrderPart:維修單實際領用零件(完工扣庫存依據)
"""
from decimal import Decimal

from django.db import models

from apps.catalog.models import Product
from apps.core.models import TenantOwnedModel
from apps.inventory.models import Warehouse
from apps.parties.models import Customer, SalesPerson, Supplier


class RepairItem(TenantOwnedModel):
    """維修項目模板:預先設定每個機型可做的維修項目 + 對應零件。"""

    name = models.CharField("項目名稱", max_length=80)
    default_labor_fee = models.DecimalField(
        "預設工資",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
    )
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "維修項目"
        verbose_name_plural = "維修項目"

    def __str__(self) -> str:
        return self.name


class RepairItemModel(TenantOwnedModel):
    """維修項目綁定的機型 key(跨同款 SKU)。"""

    repair_item = models.ForeignKey(
        RepairItem,
        on_delete=models.CASCADE,
        related_name="model_bindings",
    )
    host_model_key = models.CharField(
        "機型 key",
        max_length=128,
        db_index=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "repair_item", "host_model_key"],
                name="uniq_repair_item_model",
            )
        ]


class RepairItemPart(TenantOwnedModel):
    """維修項目預設所需零件 + 數量。"""

    repair_item = models.ForeignKey(
        RepairItem,
        on_delete=models.CASCADE,
        related_name="parts",
    )
    part_product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        verbose_name="零件商品",
        help_text="必須是零件倉的 Product(warehouse_type=parts)",
    )
    default_qty = models.PositiveIntegerField("預設數量", default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "repair_item", "part_product"],
                name="uniq_repair_item_part",
            )
        ]


class RepairOrder(TenantOwnedModel):
    """維修單。自修 / 委外 雙模式共用此 model。"""

    class Mode(models.TextChoices):
        IN_HOUSE = "in_house", "自修"
        EXTERNAL = "external", "委外"

    class UnlockMethod(models.TextChoices):
        NONE = "none", "無"
        PASSWORD = "password", "密碼"
        PATTERN = "pattern", "圖形鎖"

    class Status(models.TextChoices):
        PENDING = "pending", "待評估"
        QUOTING = "quoting", "報價中"
        IN_REPAIR = "in_repair", "維修中"
        SENT_EXTERNAL = "sent_external", "已送外廠"
        READY_PICKUP = "ready_pickup", "待取件"
        COMPLETED = "completed", "完成"

    no = models.CharField("維修單號", max_length=20, blank=True, editable=False)
    mode = models.CharField(
        "維修方式",
        max_length=16,
        choices=Mode.choices,
        default=Mode.IN_HOUSE,
    )

    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, verbose_name="客戶"
    )
    host_model_key = models.CharField(
        "機型 key", max_length=128, blank=True, db_index=True,
    )
    host_model_name = models.CharField(
        "機型名稱(snapshot)", max_length=128, blank=True
    )
    device_serial = models.CharField(
        "機身序號 / IMEI", max_length=64, blank=True,
    )
    defect_description = models.TextField("故障描述", blank=True)
    unlock_method = models.CharField(
        "手機解鎖方式",
        max_length=16,
        choices=UnlockMethod.choices,
        default=UnlockMethod.NONE,
    )
    unlock_password = models.CharField(
        "解鎖密碼",
        max_length=64,
        blank=True,
        help_text="僅供維修使用,列印收據不會印出",
    )
    unlock_pattern = models.CharField(
        "解鎖圖形(九宮格)",
        max_length=32,
        blank=True,
        help_text="例:1-5-9-6-3",
    )
    is_return_visit = models.BooleanField(
        "返修",
        default=False,
        help_text="此單為先前維修的後續處理",
    )
    previous_repair_order = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="return_visits",
        verbose_name="關聯原維修單",
    )
    internal_note = models.TextField(
        "內部備註",
        blank=True,
        help_text="師傅 / 經手人內部記事(不顯示給客戶)",
    )
    received_date = models.DateField("收件日期")
    expected_complete_date = models.DateField(
        "預計完修日期", null=True, blank=True
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, verbose_name="收件門市"
    )
    sales_person = models.ForeignKey(
        SalesPerson,
        on_delete=models.PROTECT,
        verbose_name="經手人",
        null=True,
        blank=True,
    )
    status = models.CharField(
        "狀態",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # 自修欄位
    repair_item = models.ForeignKey(
        RepairItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="維修項目",
    )
    labor_fee = models.DecimalField(
        "工資", max_digits=14, decimal_places=2, default=Decimal("0")
    )
    suggested_quote = models.DecimalField(
        "建議報價", max_digits=14, decimal_places=2, default=Decimal("0")
    )
    final_quote = models.DecimalField(
        "實際報價", max_digits=14, decimal_places=2, default=Decimal("0")
    )

    # 委外欄位
    external_vendor = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        verbose_name="委外廠商",
        null=True,
        blank=True,
        related_name="repair_orders",
    )
    external_quote_estimated = models.DecimalField(
        "委外預估費用",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
    )
    external_quote_actual = models.DecimalField(
        "委外實際費用",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
    )
    sent_external_at = models.DateField(
        "送出外廠日期", null=True, blank=True
    )
    external_expected_pickup = models.DateField(
        "預計取回日期", null=True, blank=True
    )

    # 結算欄位
    customer_paid_amount = models.DecimalField(
        "客戶實付金額",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
    )
    completed_at = models.DateTimeField("完工時間", null=True, blank=True)
    is_void = models.BooleanField("作廢", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "no"], name="uniq_repair_no"),
        ]
        ordering = ["-received_date", "-id"]
        verbose_name = "維修單"
        verbose_name_plural = "維修單"

    def __str__(self) -> str:
        return f"{self.no} {self.customer.name if self.customer_id else ''}"

    def save(self, *args, **kwargs):
        if not self.no and self.tenant_id:
            self.no = self.tenant.issue_next_repair_no()
        super().save(*args, **kwargs)


class RepairOrderPart(TenantOwnedModel):
    """維修單實際領用的零件(完工依此扣零件倉庫存)。"""

    repair_order = models.ForeignKey(
        RepairOrder,
        on_delete=models.CASCADE,
        related_name="parts",
    )
    part_product = models.ForeignKey(
        Product, on_delete=models.PROTECT, verbose_name="零件"
    )
    qty = models.PositiveIntegerField("數量", default=1)
    unit_cost = models.DecimalField(
        "單位成本",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
    )

    class Meta:
        ordering = ["id"]
