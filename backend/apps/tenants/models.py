import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from apps.core.models import TenantOwnedModel, TimestampedModel
from apps.core.staff_cost import COMPANY_MODES


class Tenant(TimestampedModel):
    name = models.CharField("名稱", max_length=120)
    code = models.SlugField("代碼", max_length=40, unique=True)
    is_active = models.BooleanField("啟用", default=True)
    # 公司的穩定身分,備份檔靠它認「這是哪一家的資料」。名稱與代碼可以改、
    # 數字 id 換一台伺服器就不一樣,所以另外給一個不會變的。一般畫面不能改它。
    # 注意:uuid 相同只代表「是同一家的備份」,不是授權證明。
    backup_uuid = models.UUIDField(
        "公司識別碼", default=uuid.uuid4, unique=True, editable=False
    )
    next_supplier_seq = models.PositiveIntegerField(
        "下一供應商流水", default=1, editable=False
    )
    next_customer_seq = models.PositiveIntegerField(
        "下一客戶流水", default=1, editable=False
    )
    next_member_seq = models.PositiveIntegerField(
        "下一會員流水", default=1, editable=False
    )
    next_style_seq = models.PositiveIntegerField(
        "下一款式碼流水", default=1, editable=False
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
    repair_warranty_days = models.PositiveIntegerField(
        "維修保固天數",
        default=90,
        help_text="返修保固判定基準(自完修日起算)",
    )
    contract_remind_months = models.PositiveSmallIntegerField(
        "門號合約到期前幾個月提醒",
        default=3,
        help_text="門號合約到期前幾個月開始出現在「合約到期」的待聯絡名單",
    )
    # 業務員成本(算獎金看的毛利用的成本)全公司的那一條;商品自己有設的用商品的。規則在 apps/core/staff_cost.py
    staff_cost_mode = models.CharField(
        "業務員成本算法", max_length=10, blank=True, default="", choices=COMPANY_MODES,
        help_text="空的 = 尚未設定(業務員成本 = 實際成本)",
    )
    staff_cost_value = models.DecimalField(
        "業務員成本加多少", max_digits=14, decimal_places=2, default=0,
        help_text="加固定額 = 每一件加幾元;加百分比 = 加幾 %",
    )
    # 平台的設定(平台管理員在「經銷商」勾;不跟著公司備份):型號庫自動加了新機,就照展開的規則建成這家的品號(catalog/device_watch.py)
    auto_device_models = models.BooleanField("新機自動建品號", default=False, db_default=False)

    class Meta:
        ordering = ["id"]
        verbose_name = "租戶"
        verbose_name_plural = "租戶"

    def __str__(self) -> str:
        return self.name

    def issue_next_supplier_code(self) -> str:
        """原子地取下一個供應商代碼:`S-{6位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update(no_key=True).get(pk=self.pk)       # 只改流水號:不擋別人新增指到這家公司的資料
            seq = row.next_supplier_seq
            row.next_supplier_seq = seq + 1
            row.save(update_fields=["next_supplier_seq"])
            self.next_supplier_seq = row.next_supplier_seq
            return f"S-{seq:06d}"

    def issue_next_customer_code(self) -> str:
        """原子地取下一個客戶代碼:`C-{5位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update(no_key=True).get(pk=self.pk)       # 只改流水號:不擋別人新增指到這家公司的資料
            seq = row.next_customer_seq
            row.next_customer_seq = seq + 1
            row.save(update_fields=["next_customer_seq"])
            self.next_customer_seq = row.next_customer_seq
            return f"C-{seq:05d}"

    def issue_next_member_code(self) -> str:
        """原子地取下一個會員代碼:`M-{5位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update(no_key=True).get(pk=self.pk)       # 只改流水號:不擋別人新增指到這家公司的資料
            seq = row.next_member_seq
            row.next_member_seq = seq + 1
            row.save(update_fields=["next_member_seq"])
            self.next_member_seq = row.next_member_seq
            return f"M-{seq:05d}"

    def issue_next_style_code(self) -> str:
        """原子地取下一個款式碼:至少 3 位流水(例 042;超過 999 就變 4 位)。

        無品牌配件很難命名,店員不用自己想:系統給一個穩定的號,
        顯示成「透明磁吸防摔殼 042」就分得出來了。

        用 `no_key=True`:一般 FOR UPDATE 會擋住別的交易對這一列做外鍵檢查,
        而「建商品」需要對 Tenant 取 FOR KEY SHARE。兩邊交錯就會死鎖
        (實測:精靈鎖 Category 取 SKU,建新品鎖 Tenant 取款式碼,互等)。
        FOR NO KEY UPDATE 一樣序列化取號,但放行外鍵參照。
        """
        with transaction.atomic():
            row = Tenant.objects.select_for_update(no_key=True).get(pk=self.pk)
            seq = row.next_style_seq
            row.next_style_seq = seq + 1
            row.save(update_fields=["next_style_seq"])
            self.next_style_seq = row.next_style_seq
            return f"{seq:03d}"

    def issue_next_expense_no(self) -> str:
        """原子地取下一張雜支單號:`EX-{5位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update(no_key=True).get(pk=self.pk)       # 只改流水號:不擋別人新增指到這家公司的資料
            seq = row.next_expense_seq
            row.next_expense_seq = seq + 1
            row.save(update_fields=["next_expense_seq"])
            self.next_expense_seq = row.next_expense_seq
            return f"EX-{seq:05d}"

    def issue_next_cash_adj_no(self) -> str:
        """原子地取下一張現金調整單號:`CA-{5位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update(no_key=True).get(pk=self.pk)       # 只改流水號:不擋別人新增指到這家公司的資料
            seq = row.next_cash_adj_seq
            row.next_cash_adj_seq = seq + 1
            row.save(update_fields=["next_cash_adj_seq"])
            self.next_cash_adj_seq = row.next_cash_adj_seq
            return f"CA-{seq:05d}"

    def issue_next_phone_bill_no(self) -> str:
        """原子地取下一張代收話費單號:`PB-{5位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update(no_key=True).get(pk=self.pk)       # 只改流水號:不擋別人新增指到這家公司的資料
            seq = row.next_phone_bill_seq
            row.next_phone_bill_seq = seq + 1
            row.save(update_fields=["next_phone_bill_seq"])
            self.next_phone_bill_seq = row.next_phone_bill_seq
            return f"PB-{seq:05d}"

    def issue_next_repair_no(self) -> str:
        """原子地取下一張維修單號:`R-{6位流水}`。"""
        with transaction.atomic():
            row = Tenant.objects.select_for_update(no_key=True).get(pk=self.pk)       # 只改流水號:不擋別人新增指到這家公司的資料
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
    # 開單選了這種發票,課稅別跟著帶什麼(空的 = 不動)。以前「免用」寫死切成未稅;發票在別的系統開、稅有繳的店
    # (手機玩家 12/1 起照舊用舊系統印)這樣每張單毛利多算約 5% —— 改成每種發票自己設(全站檢視 A1;紅隊:不要改「免用」的定義)
    tax_method = models.CharField(
        "帶入課稅別", max_length=20, blank=True, default="", db_default="",
        choices=[("", "不帶"), ("taxable_included", "應稅內含"), ("taxable_excluded", "應稅外加"), ("untaxed", "未稅")],
    )

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

    **一條字軌是一間門市的**(owner 2026-10-13:發票機印的是號碼已經印在紙上的整捲發票,每間門市各有一捲):
    開單只取自己門市的字軌。`warehouse` 空的 = 全公司共用,只有分門市之前建的舊資料會這樣(新增一定要選門市)。
    **一條字軌是某一期的**(`period_start`,兩個月一期):開單只取發票日期那一期的,換期之後上一期的號碼不能再開。
    「下一張」只能用跳號改(`services.jump_invoice_track`,每一次留一筆 `InvoiceTrackJump`),不能直接改欄位。
    """

    invoice_type = models.ForeignKey(
        InvoiceType,
        on_delete=models.PROTECT,
        related_name="tracks",
        verbose_name="發票類型",
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="invoice_tracks",
        null=True,
        blank=True,
        verbose_name="門市",
        help_text="空的 = 全公司共用(分門市之前建的舊字軌)",
    )
    period_label = models.CharField(
        "期別",
        max_length=30,
        blank=True,
        help_text="例:115年5-6月(有登記 period_start 的由系統填)",
    )
    # 這條字軌是哪一期的(兩個月一期,記那一期的第一天;`invoice_periods.py`)。開單只取發票日期那一期的字軌。
    # 空的 = 沒有登記期別的舊字軌:不檢查期別、什麼時候都能用(新增的一定要選)
    period_start = models.DateField("期別的第一天", null=True, blank=True)
    prefix = models.CharField("字軌", max_length=4)
    range_start = models.PositiveIntegerField("起號")
    range_end = models.PositiveIntegerField("迄號")
    next_number = models.PositiveIntegerField(
        "下一張號碼",
        help_text="開檔時 = 起號;每開一張遞增 1",
    )
    # 這條字軌**系統自己開出去過**的最大號碼的下一號(沒開過 = 0);只往前、跳號不會動它。
    # 往回跳號不能跳到它前面。跟「下一張」分開記:往後跳錯了要改得回來(那幾號沒開過),但開出去過的號碼不行 ——
    # 就算那張銷貨單後來不在了(回到較早的備份,單沒了、紙已經用掉)。備份還原時跟「下一張」一樣只取大的。
    floor_number = models.PositiveIntegerField("開過的最大號碼的下一號", default=0, db_default=0, editable=False)
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

    def save(self, *args, **kwargs):
        # 有登記期別的:期別的字由系統照期別寫(例 `115年11-12月`),不收人打的 —— 清單與報表上看到的才會跟實際取號的期別一樣
        if self.period_start is not None:
            from . import invoice_periods

            self.period_label = invoice_periods.label(self.period_start)
            fields = kwargs.get("update_fields")
            if fields is not None and "period_start" in fields and "period_label" not in fields:
                kwargs["update_fields"] = [*fields, "period_label"]
        super().save(*args, **kwargs)


class InvoiceTrackJump(TenantOwnedModel):
    """跳號紀錄:有人把某一條字軌的「下一張」從幾號改成幾號(owner 2026-10-13:發票機故障之後要能指定從幾號開始印)。

    只記不改:往後跳 = 中間那幾號沒有開(卡紙、印壞的空白發票);往回 = 改打錯的(只有那一號之後都還沒開過才准)。
    這幾號實際有沒有開過,看的是銷貨單上的發票號碼,不是這張表。
    """

    track = models.ForeignKey(
        InvoiceTrack,
        on_delete=models.PROTECT,
        related_name="jumps",
        verbose_name="字軌",
    )
    from_number = models.PositiveIntegerField("原本的下一張")
    to_number = models.PositiveIntegerField("改成的下一張")
    reason = models.CharField("原因", max_length=100, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        editable=False,
        verbose_name="誰改的",
    )

    class Meta:
        ordering = ["-id"]
        verbose_name = "發票跳號紀錄"
        verbose_name_plural = "發票跳號紀錄"

    def __str__(self) -> str:
        return f"{self.track.prefix} {self.from_number}→{self.to_number}"


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


class DocNumberFloor(TenantOwnedModel):
    """單號的「已用過到幾號」下限。

    進貨 / 銷貨 / 銷退 / 調撥的單號是「這家公司最後一張單的號碼 + 1」。把資料
    還原到較早的備份時,備份之後開過的單會消失,下一張就會重用已經給過客人的
    號碼。還原前把當時用到的最大號記在這裡,取號時不會低於它。
    """

    prefix = models.CharField("單號字首", max_length=8)
    floor = models.PositiveIntegerField("已用過的最大流水", default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "prefix"], name="uniq_doc_number_floor"
            ),
        ]
        verbose_name = "單號下限"
        verbose_name_plural = "單號下限"

    def __str__(self) -> str:
        return f"{self.prefix}>{self.floor}"


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
    # 這個帳號不會變的識別碼。公司備份用它認「是不是同一個人」:帳號名稱可以改、
    # 也可以被別人拿去用,數字 id 換一台伺服器就不同,兩個都不能拿來認人。
    account_uuid = models.UUIDField(
        "帳號識別碼", default=uuid.uuid4, unique=True, editable=False
    )
    # 這個帳號被關掉的權限項目(清單與判斷在 apps/tenants/abilities.py)。空的 = 全開;只對店員帳號有用
    denied_abilities = models.JSONField(
        "關掉的權限", default=list, blank=True,
        help_text="項目代碼的清單;空的 = 全部可以做(管理員永遠全開)",
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


class SignInPlace(models.Model):
    """這個帳號現在在哪一個位置登入(owner 2026-10-24:「同一時間只允許同一帳號登入一個位置,登入新位置,自動踢掉舊位置」)。

    位置 = 一個瀏覽器:畫面第一次打開時自己產生一個記號存在瀏覽器裡,分頁之間共用、關掉再開還在。
    同一個位置再登入拿回同一把 token,不踢;換一個位置登入,舊的 token 作廢(規則在 apps/tenants/sign_in.py)。
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE,
        related_name="sign_in_place",
    )
    device = models.CharField("位置記號", max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "登入位置"
        verbose_name_plural = "登入位置"


class SignedOutElsewhere(models.Model):
    """被別處登入作廢的 token(只存雜湊):舊位置下一次操作看得到「帳號已在別處登入」。留 14 天。"""

    digest = models.CharField(max_length=64, primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "被別處登入作廢的登入"
        verbose_name_plural = "被別處登入作廢的登入"
