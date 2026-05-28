from django.db import models, transaction

from apps.core.models import TenantOwnedModel


class Supplier(TenantOwnedModel):
    """供應商:進貨單的對象。"""

    code = models.SlugField(
        "供應商代碼",
        max_length=20,
        blank=True,
        editable=False,
        help_text="系統自動產生:S-{6位流水};前端不輸入",
    )
    name = models.CharField("供應商名稱", max_length=120)
    contact = models.CharField("聯絡人", max_length=60, blank=True)
    phone = models.CharField("電話", max_length=40, blank=True)
    tax_id = models.CharField("統一編號", max_length=20, blank=True)
    address = models.CharField("地址", max_length=200, blank=True)
    note = models.CharField("備註", max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(
        "排序", default=100, help_text="數字小的排前面;常用供應商往前調方便快速點選"
    )
    is_repair_vendor = models.BooleanField(
        "維修委外廠商",
        default=False,
        help_text="勾選後此供應商會出現在維修單『委外』模式的廠商清單",
    )
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_supplier_tenant_code"),
        ]
        ordering = ["sort_order", "code"]
        verbose_name = "供應商"
        verbose_name_plural = "供應商"

    def __str__(self) -> str:
        return f"{self.code} {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            if self.tenant_id is None:
                raise ValueError("建立供應商必須先指定 tenant")
            self.code = self.tenant.issue_next_supplier_code()
        super().save(*args, **kwargs)


class Carrier(TenantOwnedModel):
    """電信商:中華電信 / 台灣大 / 遠傳 / 亞太 / 台星等。"""

    code = models.SlugField("代碼", max_length=10)
    name = models.CharField("名稱", max_length=40)
    is_active = models.BooleanField("啟用", default=True)
    next_plan_seq = models.PositiveIntegerField(
        "下一方案流水", default=1, editable=False
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_carrier_tenant_code"
            ),
        ]
        ordering = ["code"]
        verbose_name = "電信商"
        verbose_name_plural = "電信商"

    def __str__(self) -> str:
        return f"{self.code} {self.name}"

    def issue_next_plan_code(self) -> str:
        """原子地取下一個方案代碼:`{carrier.code}-{6位流水}`。"""
        with transaction.atomic():
            row = Carrier.objects.select_for_update().get(pk=self.pk)
            seq = row.next_plan_seq
            row.next_plan_seq = seq + 1
            row.save(update_fields=["next_plan_seq"])
            return f"{row.code}-{seq:06d}"


class TelecomPlan(TenantOwnedModel):
    """促銷方案:(電信商 × 月租 × 綁約月數 × 類型) → 佣金。"""

    class Kind(models.TextChoices):
        NEW = "new", "新辦"
        RENEWAL = "renewal", "續約"
        PORTIN = "portin", "攜碼"

    code = models.SlugField(
        "方案代碼",
        max_length=40,
        editable=False,
        blank=True,
        help_text="系統自動產生:{電信商代碼}-{6位流水}",
    )
    name = models.CharField(
        "專案名稱",
        max_length=120,
        default="",
        help_text="使用者編排的識別名稱;同租戶內唯一",
    )
    carrier = models.ForeignKey(
        Carrier,
        on_delete=models.PROTECT,
        related_name="plans",
        verbose_name="電信商",
    )
    monthly_fee = models.PositiveIntegerField("月租")
    contract_months = models.PositiveIntegerField("綁約月數")
    kind = models.CharField(
        "類型", max_length=10, choices=Kind.choices, default=Kind.NEW
    )
    commission = models.DecimalField(
        "佣金", max_digits=14, decimal_places=2, default=0
    )
    note = models.CharField("備註", max_length=200, blank=True)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_telecomplan_tenant_code"
            ),
            models.UniqueConstraint(
                fields=["tenant", "name"], name="uniq_telecomplan_tenant_name"
            ),
        ]
        ordering = ["carrier__code", "monthly_fee", "contract_months", "kind"]
        verbose_name = "電信方案"
        verbose_name_plural = "電信方案"

    def __str__(self) -> str:
        return f"{self.code} {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            if self.carrier_id is None:
                raise ValueError("建立電信方案必須先指定 carrier")
            self.code = self.carrier.issue_next_plan_code()
        super().save(*args, **kwargs)


class SimCard(TenantOwnedModel):
    """SIM 卡。隸屬廠商,有押金,出卡 → 開通 → 押金歸還的生命週期。"""

    class Status(models.TextChoices):
        IN_STOCK = "in_stock", "在庫"
        ISSUED = "issued", "已出卡"
        ACTIVATED = "activated", "已開通"
        RETURNED = "returned", "退回廠商"
        VOID = "void", "作廢"

    card_no = models.CharField("卡號 (ICCID)", max_length=25)
    vendor = models.ForeignKey(
        Carrier,
        on_delete=models.PROTECT,
        related_name="sim_cards",
        verbose_name="廠商",
    )
    deposit = models.DecimalField(
        "押金",
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="廠商收取的押金;開通後或還卡時歸還",
    )
    deposit_refunded = models.BooleanField(
        "押金已歸還",
        default=False,
        help_text="上線開通或還卡退款後勾選",
    )
    status = models.CharField(
        "狀態",
        max_length=20,
        choices=Status.choices,
        default=Status.IN_STOCK,
    )
    issued_at = models.DateTimeField("出卡時間", null=True, blank=True)
    activated_at = models.DateTimeField("開通時間", null=True, blank=True)
    returned_at = models.DateTimeField("退回時間", null=True, blank=True)
    note = models.CharField("備註", max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "card_no"], name="uniq_simcard_tenant_card_no"
            ),
        ]
        ordering = ["vendor__code", "card_no"]
        verbose_name = "SIM 卡"
        verbose_name_plural = "SIM 卡"

    def __str__(self) -> str:
        return f"{self.card_no} ({self.vendor.code})"


class SalesPerson(TenantOwnedModel):
    """業務員。銷貨單透過此 FK 記業績歸屬;經手人欄位也指這。

    若綁了 user(OneToOne),登入後表單的「經手人」會預設帶這位。
    """

    code = models.SlugField("業務員代號", max_length=20)
    name = models.CharField("姓名", max_length=120)
    phone = models.CharField("電話", max_length=40, blank=True)
    note = models.CharField("備註", max_length=200, blank=True)
    is_active = models.BooleanField("啟用", default=True)
    user = models.OneToOneField(
        "auth.User",
        on_delete=models.SET_NULL,
        related_name="sales_person",
        null=True,
        blank=True,
        verbose_name="登入帳號",
        help_text="綁定後該帳號操作時,表單經手人自動預設帶此業務員",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                name="uniq_salesperson_tenant_code",
            ),
        ]
        ordering = ["code"]
        verbose_name = "業務員"
        verbose_name_plural = "業務員"

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class Customer(TenantOwnedModel):
    """客戶。記錄銷貨單的「歸屬對象」:個人/同業/企業/其他。

    識別:code 為系統自動產生的編號 (C-{5 位流水});phone 為選填(同業/企業可不填)。
    會員(Member)是獨立的「人」主檔,可掛在任意客戶底下消費,不在這張表。
    """

    class Kind(models.TextChoices):
        INDIVIDUAL = "individual", "個人"
        PEER = "peer", "同業 / 盤商"
        CORPORATE = "corporate", "企業"
        OTHER = "other", "其他"

    code = models.SlugField(
        "客戶編號",
        max_length=20,
        blank=True,
        editable=False,
        help_text="系統自動產生:C-{5位流水};前端不顯示也不輸入",
    )
    phone = models.CharField("電話", max_length=40, blank=True)
    name = models.CharField("姓名 / 名稱", max_length=120)
    kind = models.CharField(
        "客戶類別",
        max_length=20,
        choices=Kind.choices,
        default=Kind.INDIVIDUAL,
        help_text="客戶來源類型;同業/盤商指其他通訊行批發轉售",
    )
    tax_id = models.CharField("統一編號", max_length=20, blank=True)
    address = models.CharField("地址", max_length=200, blank=True)
    note = models.CharField("備註", max_length=200, blank=True)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                name="uniq_customer_tenant_code",
            ),
        ]
        ordering = ["code"]
        verbose_name = "客戶"
        verbose_name_plural = "客戶"

    def __str__(self) -> str:
        return f"{self.code} {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            if self.tenant_id is None:
                raise ValueError("建立客戶必須先指定 tenant")
            self.code = self.tenant.issue_next_customer_code()
        super().save(*args, **kwargs)


class Member(TenantOwnedModel):
    """會員(人)。可掛在任何客戶底下消費,跟 Customer 各自獨立。

    識別:code 為系統自動產生的編號 (M-{5 位流水});phone 為選填但建議填。
    與 Customer 不互斥 - 同一個人可同時是 Customer 又是 Member,系統不強制連結。
    """

    code = models.SlugField(
        "會員編號",
        max_length=20,
        blank=True,
        editable=False,
        help_text="系統自動產生:M-{5位流水};前端不顯示也不輸入",
    )
    name = models.CharField("姓名", max_length=120)
    phone = models.CharField("電話", max_length=40, blank=True)
    national_id = models.CharField("身分證字號", max_length=20, blank=True)
    birthday = models.DateField("生日", null=True, blank=True)
    address = models.CharField("地址", max_length=200, blank=True)
    note = models.CharField("備註", max_length=200, blank=True)
    is_active = models.BooleanField("啟用", default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                name="uniq_member_tenant_code",
            ),
        ]
        ordering = ["code"]
        verbose_name = "會員"
        verbose_name_plural = "會員"

    def __str__(self) -> str:
        return f"{self.code} {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            if self.tenant_id is None:
                raise ValueError("建立會員必須先指定 tenant")
            self.code = self.tenant.issue_next_member_code()
        super().save(*args, **kwargs)
