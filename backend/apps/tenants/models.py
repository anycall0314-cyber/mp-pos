from django.db import models

from apps.core.models import TenantOwnedModel, TimestampedModel


class Tenant(TimestampedModel):
    name = models.CharField("名稱", max_length=120)
    code = models.SlugField("代碼", max_length=40, unique=True)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "租戶"
        verbose_name_plural = "租戶"

    def __str__(self) -> str:
        return self.name


class InvoiceType(TenantOwnedModel):
    """發票類型主檔(系統設定)。

    code 為穩定識別,業務單據 invoice_form 欄位存的就是這個 code。
    seeded 6 種:e_invoice / ev_dup / ev_tri / hand_dup / hand_tri / none
    使用者只能切換 is_active / is_default / 修改 name,不可改 code。
    """

    code = models.CharField("代碼", max_length=20)
    name = models.CharField("顯示名稱", max_length=50)
    sort_order = models.PositiveIntegerField("排序", default=0)
    is_active = models.BooleanField("啟用", default=True)
    is_default = models.BooleanField("預設", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_invoice_type_tenant_code"
            ),
        ]
        ordering = ["sort_order", "code"]
        verbose_name = "發票類型"
        verbose_name_plural = "發票類型"

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class InvoiceTrack(TenantOwnedModel):
    """發票字軌:每期(雙月)申請的發票號碼區段。

    銷貨建單時依 invoice_type 自動取下一張號碼。
    範例:AB 字軌 12345678 ~ 12345887(200 張)。
    """

    invoice_type = models.ForeignKey(
        InvoiceType,
        on_delete=models.PROTECT,
        related_name="tracks",
        verbose_name="發票類型",
    )
    period_label = models.CharField(
        "期別",
        max_length=30,
        blank=True,
        help_text="例:115年5-6月",
    )
    prefix = models.CharField("字軌", max_length=4)
    range_start = models.PositiveIntegerField("起號")
    range_end = models.PositiveIntegerField("迄號")
    next_number = models.PositiveIntegerField(
        "下一張號碼",
        help_text="開檔時 = 起號;每開一張遞增 1",
    )
    is_active = models.BooleanField("啟用", default=True)
    note = models.CharField("備註", max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "prefix", "range_start"],
                name="uniq_invoice_track_prefix_start",
            ),
            models.CheckConstraint(
                check=models.Q(range_end__gte=models.F("range_start")),
                name="invoice_track_end_gte_start",
            ),
        ]
        ordering = ["-id"]
        verbose_name = "發票字軌"
        verbose_name_plural = "發票字軌"

    def __str__(self) -> str:
        return f"{self.prefix} {self.range_start}-{self.range_end}"

    @property
    def is_depleted(self) -> bool:
        return self.next_number > self.range_end

    def format_number(self, n: int) -> str:
        return f"{self.prefix}{n:08d}"


class PaymentMethod(TenantOwnedModel):
    """付款方式主檔。

    kind 用於統計分類:
    - cash:現金,計入當日營業現金
    - transfer:匯款,不計入當日現金
    - non_cash:非現金支付(刷卡 / LinePay / 街口 / 全支付 ...),不計入當日現金
    """

    class Kind(models.TextChoices):
        CASH = "cash", "現金"
        TRANSFER = "transfer", "匯款"
        NON_CASH = "non_cash", "非現金"

    code = models.CharField("代碼", max_length=20)
    name = models.CharField("顯示名稱", max_length=50)
    kind = models.CharField(
        "分類",
        max_length=20,
        choices=Kind.choices,
    )
    sort_order = models.PositiveIntegerField("排序", default=0)
    is_active = models.BooleanField("啟用", default=True)
    is_default = models.BooleanField("預設", default=False)
    note = models.CharField("備註", max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                name="uniq_payment_method_tenant_code",
            ),
        ]
        ordering = ["sort_order", "code"]
        verbose_name = "付款方式"
        verbose_name_plural = "付款方式"

    def __str__(self) -> str:
        return f"{self.code} {self.name}"
