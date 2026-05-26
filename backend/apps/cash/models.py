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
    handled_by = models.ForeignKey(
        "parties.SalesPerson",
        on_delete=models.PROTECT,
        related_name="petty_expenses_handled",
        null=True,
        blank=True,
        verbose_name="經手人",
        help_text="實際支出的執行人(從業務員主檔挑);用於老闆對帳",
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


class CashAdjustment(TenantOwnedModel):
    """現金調整單。

    用途:
    - direction=in:老闆下錢進店頭備用金(零用金不夠時補)
    - direction=out:從店頭領現金去存銀行 / 拿回家
    - 期初校正(現場盤點現金 vs 系統不符,記一筆把帳調平)

    自動編號:CA-{5 位流水}。
    """

    class Direction(models.TextChoices):
        IN = "in", "存入(老闆補錢)"
        OUT = "out", "提取(領出 / 存銀行)"

    class Reason(models.TextChoices):
        REFILL = "refill", "補充備用金"
        DEPOSIT = "deposit", "領現存銀行"
        OWNER_TAKE = "owner_take", "老闆領用"
        ADJUSTMENT = "adjustment", "盤點校正"
        OTHER = "other", "其他"

    no = models.CharField(
        "單號",
        max_length=20,
        editable=False,
        blank=True,
        help_text="系統自動產生:CA-{5位流水}",
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="cash_adjustments",
        verbose_name="門市",
    )
    doc_date = models.DateField("單據日期", default=date.today)
    direction = models.CharField(
        "方向",
        max_length=10,
        choices=Direction.choices,
        default=Direction.IN,
    )
    reason = models.CharField(
        "事由",
        max_length=20,
        choices=Reason.choices,
        default=Reason.REFILL,
    )
    amount = models.DecimalField(
        "金額",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="正數,方向由 direction 決定 + / -",
    )
    handled_by = models.ForeignKey(
        "parties.SalesPerson",
        on_delete=models.PROTECT,
        related_name="cash_adjustments_handled",
        null=True,
        blank=True,
        verbose_name="經手人",
        help_text="實際執行調整的人(從業務員主檔挑);用於老闆對帳",
    )
    note = models.CharField("備註", max_length=200, blank=True)
    is_void = models.BooleanField("作廢", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "no"], name="uniq_cash_adjustment_no"
            ),
        ]
        ordering = ["-doc_date", "-id"]
        verbose_name = "現金調整"
        verbose_name_plural = "現金調整"

    def __str__(self) -> str:
        return f"{self.no} {self.get_direction_display()} {self.amount}"

    def save(self, *args, **kwargs):
        if not self.no:
            if self.tenant_id is None:
                raise ValueError("建立現金調整必須先指定 tenant")
            self.no = self.tenant.issue_next_cash_adj_no()
        super().save(*args, **kwargs)


class PhoneBillCollection(TenantOwnedModel):
    """代收電話費單。

    店家代收客戶繳的電信費(中華 / 台星 / 遠傳 ...),純現金收入。
    儲存即生效,要取消用 is_void。
    自動編號:PB-{5 位流水}。
    收費歸到 warehouse(門市)當日現金櫃流水。
    member 是選填:若 phone_no 對到會員主檔則自動帶入,沒對到就 null。
    """

    no = models.CharField(
        "單號",
        max_length=20,
        editable=False,
        blank=True,
        help_text="系統自動產生:PB-{5位流水}",
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="phone_bills",
        verbose_name="門市",
        help_text="收費歸到哪家門市的現金櫃",
    )
    doc_date = models.DateField("單據日期", default=date.today)
    carrier = models.ForeignKey(
        "parties.Carrier",
        on_delete=models.PROTECT,
        related_name="phone_bills",
        verbose_name="電信業者",
    )
    phone_no = models.CharField(
        "電話號碼",
        max_length=20,
        help_text="繳費對應的完整電話號碼",
    )
    amount = models.DecimalField(
        "金額",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="繳費金額(整數元)",
    )
    id_no = models.CharField(
        "身分證字號",
        max_length=20,
        help_text="收據顯示時會做隱碼處理",
    )
    handled_by = models.ForeignKey(
        "parties.SalesPerson",
        on_delete=models.PROTECT,
        related_name="phone_bills_handled",
        verbose_name="經手人",
    )
    member = models.ForeignKey(
        "parties.Member",
        on_delete=models.SET_NULL,
        related_name="phone_bills",
        null=True,
        blank=True,
        verbose_name="會員",
        help_text="phone_no 對到會員主檔時自動掛上",
    )
    is_void = models.BooleanField("作廢", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "no"], name="uniq_phone_bill_no"
            ),
        ]
        ordering = ["-doc_date", "-id"]
        verbose_name = "代收話費"
        verbose_name_plural = "代收話費"

    def __str__(self) -> str:
        return f"{self.no} {self.phone_no} {self.amount}"

    def save(self, *args, **kwargs):
        if not self.no:
            if self.tenant_id is None:
                raise ValueError("建立代收話費單必須先指定 tenant")
            self.no = self.tenant.issue_next_phone_bill_no()
        super().save(*args, **kwargs)
