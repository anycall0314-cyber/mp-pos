from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from apps.core.models import TenantOwnedModel, TimestampedModel


class Tenant(TimestampedModel):
    name = models.CharField("名稱", max_length=120)
    code = models.SlugField("代碼", max_length=40, unique=True)
    is_active = models.BooleanField("啟用", default=True)
    next_supplier_seq = models.PositiveIntegerField(
        "下一供應商流水", default=1, editable=False
    )
    next_customer_seq = models.PositiveIntegerField(
        "下一客戶流水", default=1, editable=False
    )
    next_member_seq = models.PositiveIntegerField(
        "下一會員流水", default=1, editable=False
    )
    next_expense_seq = models.PositiveIntegerField(
        "下一雜支單流水", default=1, editable=False
    )
    next_cash_adj_seq = models.PositiveIntegerField(
        "下一現金調整流水", default=1, editable=False
    )
    next_phone_bill_seq = models.PositiveIntegerField(
        "下一代收話費流水", default=1, editable=False
    )
    next_repair_seq = models.PositiveIntegerField(
        "下一維修單流水", default=1, editable=False
    )

    class Meta:
        ordering = ["id"]
        verbose_name = "租戶"
        verbose_name_plural = "租戶"

    def __str__(self) -> str:
        return self.name

    def issue_next_supplier_code(self) -> str:
        """原子地取下一個供應商代碼:`S-{6位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update().get(pk=self.pk)
            seq = row.next_supplier_seq
            row.next_supplier_seq = seq + 1
            row.save(update_fields=["next_supplier_seq"])
            self.next_supplier_seq = row.next_supplier_seq
            return f"S-{seq:06d}"

    def issue_next_customer_code(self) -> str:
        """原子地取下一個客戶代碼:`C-{5位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update().get(pk=self.pk)
            seq = row.next_customer_seq
            row.next_customer_seq = seq + 1
            row.save(update_fields=["next_customer_seq"])
            self.next_customer_seq = row.next_customer_seq
            return f"C-{seq:05d}"

    def issue_next_member_code(self) -> str:
        """原子地取下一個會員代碼:`M-{5位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update().get(pk=self.pk)
            seq = row.next_member_seq
            row.next_member_seq = seq + 1
            row.save(update_fields=["next_member_seq"])
            self.next_member_seq = row.next_member_seq
            return f"M-{seq:05d}"

    def issue_next_expense_no(self) -> str:
        """原子地取下一張雜支單號:`EX-{5位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update().get(pk=self.pk)
            seq = row.next_expense_seq
            row.next_expense_seq = seq + 1
            row.save(update_fields=["next_expense_seq"])
            self.next_expense_seq = row.next_expense_seq
            return f"EX-{seq:05d}"

    def issue_next_cash_adj_no(self) -> str:
        """原子地取下一張現金調整單號:`CA-{5位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update().get(pk=self.pk)
            seq = row.next_cash_adj_seq
            row.next_cash_adj_seq = seq + 1
            row.save(update_fields=["next_cash_adj_seq"])
            self.next_cash_adj_seq = row.next_cash_adj_seq
            return f"CA-{seq:05d}"

    def issue_next_phone_bill_no(self) -> str:
        """原子地取下一張代收話費單號:`PB-{5位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update().get(pk=self.pk)
            seq = row.next_phone_bill_seq
            row.next_phone_bill_seq = seq + 1
            row.save(update_fields=["next_phone_bill_seq"])
            self.next_phone_bill_seq = row.next_phone_bill_seq
            return f"PB-{seq:05d}"

    def issue_next_repair_no(self) -> str:
        """原子地取下一張維修單號:`R-{6位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update().get(pk=self.pk)
            seq = row.next_repair_seq
            row.next_repair_seq = seq + 1
            row.save(update_fields=["next_repair_seq"])
            self.next_repair_seq = row.next_repair_seq
            return f"R-{seq:06d}"


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


class UserProfile(TimestampedModel):
    """Django User 的延伸:綁定 tenant + 角色 + 預設倉。

    三種角色:
    - platform_admin:不屬於任何 tenant,可看 / 管理所有經銷商
    - tenant_admin:屬於一個 tenant,該 tenant 內全權限、不鎖倉、可看所有報表
    - tenant_user:屬於一個 tenant,被鎖在 default_warehouse,只能操作自己倉
    """

    class Role(models.TextChoices):
        PLATFORM_ADMIN = "platform_admin", "平台管理員"
        TENANT_ADMIN = "tenant_admin", "經銷商管理員"
        TENANT_USER = "tenant_user", "店員"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="user_profiles",
        null=True,
        blank=True,
        verbose_name="所屬經銷商",
        help_text="platform_admin 留空,其他必填",
    )
    role = models.CharField(
        "角色",
        max_length=20,
        choices=Role.choices,
        default=Role.TENANT_USER,
    )
    default_warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_profiles",
        verbose_name="預設門市",
    )
    is_warehouse_locked = models.BooleanField(
        "鎖定門市",
        default=True,
        help_text="True 時只能操作 default_warehouse;管理員角色預設 False",
    )

    class Meta:
        verbose_name = "使用者設定"
        verbose_name_plural = "使用者設定"

    def __str__(self) -> str:
        return f"{self.user.username} ({self.get_role_display()})"

    def clean(self):
        if self.role == self.Role.PLATFORM_ADMIN and self.tenant_id is not None:
            raise ValidationError("平台管理員不可指定 tenant")
        if self.role != self.Role.PLATFORM_ADMIN and self.tenant_id is None:
            raise ValidationError("此角色必須指定 tenant")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
