from datetime import date

from django.db import models

from apps.core.models import TenantOwnedModel


class PettyExpense(TenantOwnedModel):
    """店頭雜支單。

    記錄每家門市的零星支出(房租/水電/餐飲/雜物等),日後彙整到「營業日報」算
    每日現金流動。儲存即生效;要取消用 is_void。
    自動編號:EX-{5 位流水}(每 tenant 獨立)。
    """

    class Category(models.TextChoices):
        RENT = "rent", "房租"
        UTILITY = "utility", "水電網路"
        MEAL = "meal", "餐飲"
        SUPPLIES = "supplies", "雜物 / 文具"
        OTHER = "other", "其他"

    no = models.CharField(
        "單號",
        max_length=20,
        editable=False,
        blank=True,
        help_text="系統自動產生:EX-{5位流水}",
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="petty_expenses",
        verbose_name="門市",
        help_text="記在哪家門市的帳上",
    )
    doc_date = models.DateField("單據日期", default=date.today)
    category = models.CharField(
        "類別",
        max_length=20,
        choices=Category.choices,
        default=Category.OTHER,
    )
    amount = models.DecimalField(
        "金額",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="支出金額(整數元)",
    )
    payment_method = models.ForeignKey(
        "tenants.PaymentMethod",
        on_delete=models.PROTECT,
        related_name="petty_expenses",
        verbose_name="付款方式",
        help_text="預設現金;若是匯款則不影響店頭備用金",
    )
    payee = models.CharField(
        "收款對象",
        max_length=120,
        blank=True,
        help_text="例:房東 / 7-11 / 中華電信",
    )
    note = models.CharField("備註", max_length=200, blank=True)
    is_void = models.BooleanField("作廢", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "no"], name="uniq_petty_expense_no"
            ),
        ]
        ordering = ["-doc_date", "-id"]
        verbose_name = "雜支單"
        verbose_name_plural = "雜支單"

    def __str__(self) -> str:
        return f"{self.no} {self.get_category_display()} {self.amount}"

    def save(self, *args, **kwargs):
        if not self.no:
            if self.tenant_id is None:
                raise ValueError("建立雜支單必須先指定 tenant")
            self.no = self.tenant.issue_next_expense_no()
        super().save(*args, **kwargs)
