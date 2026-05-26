from datetime import date

from django.conf import settings
from django.db import models, transaction

from apps.core.models import TenantOwnedModel


class PurchaseOrderCategory(TenantOwnedModel):
    """進貨單別。例如:一般進貨、員工換貨、轉入進等。"""

    code = models.CharField("代碼", max_length=10)
    name = models.CharField("名稱", max_length=50)
    sort_order = models.PositiveIntegerField("排序", default=0)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_po_category_tenant_code"
            ),
        ]
        ordering = ["sort_order", "code"]
        verbose_name = "進貨單別"
        verbose_name_plural = "進貨單別"

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class PurchaseOrder(TenantOwnedModel):
    """進貨單(單頭)。儲存即生效,沒有「過帳」中間狀態。"""

    class TaxMethod(models.TextChoices):
        TAXABLE_INCLUDED = "taxable_included", "應稅內含"
        TAXABLE_EXCLUDED = "taxable_excluded", "應稅外加"
        UNTAXED = "untaxed", "未稅"
        # 舊資料相容(已不在 UI 顯示):
        TAX_FREE = "tax_free", "免稅"
        ZERO_TAX = "zero_tax", "零稅"

    no = models.CharField(
        "單號",
        max_length=30,
        editable=False,
        blank=True,
        help_text="系統自動產生:PO-{6位流水}",
    )
    supplier = models.ForeignKey(
        "parties.Supplier",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        verbose_name="供應商",
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        verbose_name="入庫倉",
    )
    doc_date = models.DateField("單據日期", default=date.today)
    category = models.ForeignKey(
        PurchaseOrderCategory,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        null=True,
        blank=True,
        verbose_name="進貨單別",
    )
    tax_method = models.CharField(
        "課稅別",
        max_length=20,
        choices=TaxMethod.choices,
        default=TaxMethod.TAXABLE_INCLUDED,
    )
    invoice_form = models.CharField(
        "發票類型",
        max_length=20,
        blank=True,
        default="",
        help_text="存 InvoiceType.code",
    )
    invoice_no = models.CharField("發票號碼", max_length=20, blank=True)
    invoice_date = models.DateField("發票日期", null=True, blank=True)
    payment_method = models.ForeignKey(
        "tenants.PaymentMethod",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        null=True,
        blank=True,
        verbose_name="付款方式",
        help_text="cash=從店頭備用金扣;transfer/non_cash=不動店頭現金",
    )
    note = models.CharField("備註", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        verbose_name="作業者",
    )

    is_void = models.BooleanField("作廢", default=False)

    subtotal = models.DecimalField(
        "未稅小計",
        max_digits=14,
        decimal_places=2,
        default=0,
        editable=False,
    )
    tax_amount = models.DecimalField(
        "稅額",
        max_digits=14,
        decimal_places=2,
        default=0,
        editable=False,
    )
    total_cost = models.DecimalField(
        "含稅總額",
        max_digits=14,
        decimal_places=2,
        default=0,
        editable=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "no"], name="uniq_po_tenant_no"),
        ]
        ordering = ["-doc_date", "-id"]
        verbose_name = "進貨單"
        verbose_name_plural = "進貨單"

    def __str__(self) -> str:
        return f"{self.no} {self.supplier_id}"

    def save(self, *args, **kwargs):
        if not self.no:
            with transaction.atomic():
                last = (
                    PurchaseOrder.objects.filter(tenant=self.tenant)
                    .order_by("-id")
                    .first()
                )
                if last and last.no:
                    try:
                        last_seq = int(last.no.split("-")[-1])
                    except (ValueError, IndexError):
                        last_seq = 0
                else:
                    last_seq = 0
                self.no = f"PO-{last_seq + 1:06d}"
        super().save(*args, **kwargs)


class PurchaseOrderItem(TenantOwnedModel):
    """進貨單明細;每筆對應一個 SKU 與該 SKU 的多台序號。"""

    po = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="進貨單",
    )
    line_no = models.PositiveIntegerField("行號", default=1)
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="purchase_items",
        verbose_name="商品",
    )
    qty = models.PositiveIntegerField(
        "進貨數量",
        help_text="實際入庫數量(含贈品)",
    )
    billed_qty = models.PositiveIntegerField(
        "計價數量",
        default=0,
        help_text="實際計價的數量(贈品/試用品不計價);未設定 → 等於進貨數量",
    )
    unit_price = models.DecimalField("單價", max_digits=14, decimal_places=2)
    amount = models.DecimalField(
        "金額",
        max_digits=14,
        decimal_places=2,
        default=0,
        editable=False,
        help_text="數量 × 單價,系統計算",
    )

    serial_numbers = models.JSONField(
        "序號列表",
        default=list,
        blank=True,
        help_text="逐台 IMEI / SN 字串清單;長度需等於數量",
    )

    unit_landed_cost = models.DecimalField(
        "單台落地成本(未稅)",
        max_digits=14,
        decimal_places=2,
        default=0,
        editable=False,
        help_text="含稅單時 = unit_price / 1.05;其他 = unit_price",
    )

    class Meta:
        ordering = ["po", "line_no"]
        verbose_name = "進貨明細"
        verbose_name_plural = "進貨明細"

    def __str__(self) -> str:
        return f"{self.po.no} #{self.line_no} {self.product_id}"

    def save(self, *args, **kwargs):
        # billed_qty 預設 = qty(無贈品的常態)
        if not self.billed_qty:
            self.billed_qty = self.qty
        self.amount = self.billed_qty * self.unit_price
        super().save(*args, **kwargs)
