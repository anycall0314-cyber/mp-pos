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
        super().save(*args, **kwargs)
