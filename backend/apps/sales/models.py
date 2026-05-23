from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction

from apps.core.models import TenantOwnedModel


class SalesOrder(TenantOwnedModel):
    """銷貨單(單頭)。儲存即生效,沒有「過帳」中間狀態。"""

    class TaxMethod(models.TextChoices):
        TAXABLE_INCLUDED = "taxable_included", "應稅內含"
        TAXABLE_EXCLUDED = "taxable_excluded", "應稅外加"
        TAX_FREE = "tax_free", "免稅"
        ZERO_TAX = "zero_tax", "零稅"

    class SalesType(models.TextChoices):
        SALE = "sale", "一般銷售"
        ONLINE = "online", "線上訂單"
        PROMO = "promo", "促銷"

    no = models.CharField(
        "單號",
        max_length=30,
        editable=False,
        blank=True,
        help_text="系統自動產生:SO-{6位流水}",
    )
    customer = models.ForeignKey(
        "parties.Customer",
        on_delete=models.PROTECT,
        related_name="sales_orders",
        null=True,
        blank=True,
        verbose_name="客戶",
        help_text="這次交易的對象(收款/開發票對象);散客可不填",
    )
    member = models.ForeignKey(
        "parties.Customer",
        on_delete=models.PROTECT,
        related_name="member_sales_orders",
        null=True,
        blank=True,
        verbose_name="會員",
        help_text="服務對象/會員制度的歸屬;與 customer 不互斥(同行帶來的客戶可記在此)",
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="sales_orders",
        verbose_name="出貨倉",
    )
    doc_date = models.DateField("單據日期", default=date.today)
    sales_type = models.CharField(
        "銷貨類別",
        max_length=10,
        choices=SalesType.choices,
        default=SalesType.SALE,
    )
    tax_method = models.CharField(
        "課稅別",
        max_length=20,
        choices=TaxMethod.choices,
        default=TaxMethod.TAXABLE_INCLUDED,
    )
    buyer_tax_id = models.CharField(
        "買方統一編號",
        max_length=20,
        blank=True,
        help_text="應稅時填寫,免稅 / 零稅留空",
    )
    invoice_form = models.CharField(
        "發票類型",
        max_length=20,
        blank=True,
        default="",
        help_text="存 InvoiceType.code;允許空字串=未指定",
    )
    invoice_no = models.CharField(
        "發票號碼",
        max_length=20,
        blank=True,
    )
    invoice_date = models.DateField("發票日期", null=True, blank=True)
    note = models.CharField("備註", max_length=200, blank=True)
    sales_person = models.ForeignKey(
        "parties.SalesPerson",
        on_delete=models.PROTECT,
        related_name="sales_orders",
        null=True,
        blank=True,
        verbose_name="業務員",
        help_text="業績歸屬",
    )
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
    total = models.DecimalField(
        "含稅總額",
        max_digits=14,
        decimal_places=2,
        default=0,
        editable=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "no"], name="uniq_so_tenant_no"),
        ]
        ordering = ["-doc_date", "-id"]
        verbose_name = "銷貨單"
        verbose_name_plural = "銷貨單"

    def __str__(self) -> str:
        return f"{self.no}"

    def save(self, *args, **kwargs):
        if not self.no:
            with transaction.atomic():
                last = (
                    SalesOrder.objects.filter(tenant=self.tenant)
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
                self.no = f"SO-{last_seq + 1:06d}"
        super().save(*args, **kwargs)


class SalesOrderItem(TenantOwnedModel):
    """銷貨明細;一行對應一台序號(MVP 限制 requires_serial 商品)。"""

    so = models.ForeignKey(
        SalesOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="銷貨單",
    )
    line_no = models.PositiveIntegerField("行號", default=1)
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="sales_items",
        verbose_name="商品",
    )
    qty = models.PositiveIntegerField("數量", default=1)
    unit_price = models.DecimalField("單價", max_digits=14, decimal_places=2)
    amount = models.DecimalField(
        "金額",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="使用者填入的實收金額;未填則 fallback 為 數量 × 單價",
    )
    cost_at_post = models.DecimalField(
        "過帳當下單台成本",
        max_digits=14,
        decimal_places=2,
        default=0,
        editable=False,
        help_text="過帳時鎖定為 Product.weighted_avg_cost,供毛利報表用",
    )

    # 電信業欄位(MVP UI 折疊;Phase 2 才上線真正邏輯)
    sim_card = models.ForeignKey(
        "parties.SimCard",
        on_delete=models.PROTECT,
        related_name="sales_items",
        null=True,
        blank=True,
        verbose_name="SIM 卡",
    )
    msisdn = models.CharField("門號", max_length=20, blank=True)
    telecom_plan = models.ForeignKey(
        "parties.TelecomPlan",
        on_delete=models.PROTECT,
        related_name="sales_items",
        null=True,
        blank=True,
        verbose_name="電信方案",
    )
    commission = models.DecimalField(
        "業務員佣金",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="選方案後自動帶入,可手動覆寫",
    )
    activation_date = models.DateField("上線日", null=True, blank=True)

    note = models.CharField("備註", max_length=200, blank=True)

    class Meta:
        ordering = ["so", "line_no"]
        verbose_name = "銷貨明細"
        verbose_name_plural = "銷貨明細"

    def __str__(self) -> str:
        return f"{self.so.no} #{self.line_no}"

    def save(self, *args, **kwargs):
        # 未指定 amount 時自動帶入 qty × unit_price;
        # 使用者明確帶入 amount(含負數、折讓)就保留。
        if self.amount in (None, 0, Decimal("0"), Decimal("0.00")):
            self.amount = self.qty * self.unit_price
        super().save(*args, **kwargs)


class SalesOrderItemSerial(TenantOwnedModel):
    """銷貨明細出貨序號(一對多)。

    requires_serial 商品銷貨時,每台對應一筆。
    虛擬 / 不追序號商品不會有任何 row。
    """

    item = models.ForeignKey(
        SalesOrderItem,
        on_delete=models.CASCADE,
        related_name="serials",
        verbose_name="銷貨明細",
    )
    serial = models.ForeignKey(
        "inventory.ProductSerial",
        on_delete=models.PROTECT,
        related_name="sales_item_serials",
        verbose_name="序號",
    )
    line_pos = models.PositiveIntegerField("位序", default=0)

    class Meta:
        ordering = ["item", "line_pos", "id"]
        # 故意不在 serial 上加 unique:允許「賣→作廢→重賣」歷史軌跡。
        # service 層會檢查目前 serial.status == in_stock 才能新增,
        # 避免活躍中的雙重銷售。
        verbose_name = "銷貨明細序號"
        verbose_name_plural = "銷貨明細序號"

    def __str__(self) -> str:
        return f"{self.item_id}::{self.serial_id}"


class SalesOrderPayment(TenantOwnedModel):
    """銷貨單付款明細。允許 N 筆(現金 + 刷卡 + LinePay + ...)。

    sum(amounts) 必須等於 SalesOrder.total(含稅);commit_sales_order 會檢查。
    method 存 PaymentMethod.code,讓使用者在系統設定自由擴充付款通路。
    """

    so = models.ForeignKey(
        SalesOrder,
        on_delete=models.CASCADE,
        related_name="payments",
        verbose_name="銷貨單",
    )
    method = models.CharField(
        "付款方式",
        max_length=20,
        help_text="對應 tenants.PaymentMethod.code",
    )
    amount = models.DecimalField(
        "金額",
        max_digits=14,
        decimal_places=2,
    )
    note = models.CharField(
        "備註",
        max_length=100,
        blank=True,
        help_text="例:卡號末 4 碼 / 收據編號",
    )
    line_no = models.PositiveIntegerField("行號", default=1)

    class Meta:
        ordering = ["so", "line_no", "id"]
        verbose_name = "銷貨付款"
        verbose_name_plural = "銷貨付款"

    def __str__(self) -> str:
        return f"{self.so_id}::{self.method}:{self.amount}"
