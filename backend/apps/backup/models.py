"""公司備份 / 還原的工作、憑證與操作紀錄。

這個 app 自己的資料表**不進公司備份、也不會被還原蓋掉**:操作紀錄與還原前的
安全備份要留在原地,不然一還原就把「誰在什麼時候還原了什麼」一起抹掉了。
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel


class BackupKey(TimestampedModel):
    """一家公司的復原憑證。

    備份檔用它加密。產生時會給管理員看一次、請他抄下來跟硬碟分開保管 ——
    原伺服器壞掉時,只有這組憑證能把備份解開。伺服器這邊存的是用系統金鑰
    包過的密文(`wrapped`),不是明文;`fingerprint` 是讓人核對「是不是同一組」
    用的短碼,不能拿來解密。
    """

    tenant = models.OneToOneField(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="backup_key",
        verbose_name="公司",
    )
    wrapped = models.TextField("包過的憑證")
    fingerprint = models.CharField("核對碼", max_length=16)
    # 完整的雜湊:判斷「輸入的是不是原本那一組」用這個。核對碼只有 8 碼,是給人
    # 對照用的,不夠拿來證明是同一組。
    secret_hash = models.CharField("憑證雜湊", max_length=64, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="+", null=True, blank=True, verbose_name="產生者",
    )
    # 管理員按過「我已經抄下來了」
    acknowledged_at = models.DateTimeField("確認已保管", null=True, blank=True)

    class Meta:
        verbose_name = "復原憑證"
        verbose_name_plural = "復原憑證"

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.fingerprint}"


class BackupJob(TimestampedModel):
    """一次公司備份工作。狀態存資料庫,由背景 worker 執行,不靠網頁行程的記憶體。"""

    class Kind(models.TextChoices):
        MANUAL = "manual", "手動備份"
        SAFETY = "safety", "還原前安全備份"

    class Status(models.TextChoices):
        QUEUED = "queued", "排隊中"
        RUNNING = "running", "產生中"
        VERIFIED = "verified", "已驗證,可下載"
        FAILED = "failed", "失敗"
        EXPIRED = "expired", "已過期"

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="backup_jobs",
        verbose_name="公司",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MANUAL)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    # 同一個人連點兩下、或網路重送,用這個鍵認出是同一次請求
    idempotency_key = models.CharField(max_length=64, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="+", null=True, blank=True, verbose_name="發起者",
    )

    # worker 租約:拿到工作的 worker 在這個時間前要做完或續約,過期由別人接手
    attempts = models.PositiveIntegerField("已嘗試次數", default=0)
    lease_until = models.DateTimeField("租約到期", null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # 產物(只有 status=verified 時這些才有意義)
    backup_id = models.UUIDField("備份編號", default=uuid.uuid4, editable=False)
    file_name = models.CharField("檔名(相對於備份目錄)", max_length=200, blank=True)
    file_size = models.BigIntegerField("檔案大小", default=0)
    file_sha256 = models.CharField("檔案雜湊", max_length=64, blank=True)
    snapshot_at = models.DateTimeField("資料時間點", null=True, blank=True)
    summary = models.JSONField("內容摘要", default=dict, blank=True)
    error = models.TextField("失敗原因", blank=True)
    expires_at = models.DateTimeField("下載期限", null=True, blank=True)

    # 「已開始下載」只代表伺服器回應過下載請求,不能證明檔案寫進硬碟了
    download_started_at = models.DateTimeField("開始下載", null=True, blank=True)
    # 使用者重新選取本機檔案、雜湊與伺服器那份相同
    local_verified_at = models.DateTimeField("本機檔案驗證", null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["tenant", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="uniq_backup_job_idempotency",
            ),
        ]
        verbose_name = "備份工作"
        verbose_name_plural = "備份工作"

    def __str__(self) -> str:
        return f"#{self.pk} {self.tenant_id} {self.status}"


class DownloadTicket(models.Model):
    """短效、只能用一次的下載票券。

    存資料庫而不是存在行程的記憶體裡:正式機有好幾個網頁行程,換票的請求與
    實際下載的請求不一定落在同一個行程。只存票券的雜湊,不存票券本身。
    """

    token_hash = models.CharField(max_length=64, unique=True)
    job = models.ForeignKey(BackupJob, on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "下載票券"
        verbose_name_plural = "下載票券"


class RestoreJob(TimestampedModel):
    """一次還原:上傳 → 預檢 → 確認 → 執行。預檢不改任何正式資料。"""

    class Mode(models.TextChoices):
        ROLLBACK = "rollback", "既有公司回溯"
        NEW_ENV = "new_env", "新環境復原"

    class Status(models.TextChoices):
        PRECHECKED = "prechecked", "已預檢,待確認"
        REJECTED = "rejected", "預檢未通過"
        QUEUED = "queued", "排隊中"
        RUNNING = "running", "還原中"
        DONE = "done", "已完成"
        FAILED = "failed", "失敗,資料未變動"
        NEEDS_ATTENTION = "needs_attention", "中斷,需人工確認"
        CANCELLED = "cancelled", "已取消"

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="restore_jobs",
        verbose_name="目標公司",
    )
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.ROLLBACK)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PRECHECKED, db_index=True
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="+", null=True, blank=True, verbose_name="上傳者",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="+", null=True, blank=True, verbose_name="確認者",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    staged_file = models.CharField("暫存檔(相對於備份目錄)", max_length=200, blank=True)
    file_sha256 = models.CharField(max_length=64, blank=True)
    # 預檢結果:來源公司、門市、備份時間、各表筆數、會取代什麼、帳號對不回來的清單
    report = models.JSONField("預檢報告", default=dict, blank=True)
    # 預檢當下目標公司的資料指紋;確認時要一樣,不然得重新預檢
    target_fingerprint = models.CharField(max_length=64, blank=True)
    safety_backup = models.ForeignKey(
        BackupJob, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="還原前安全備份",
    )
    result = models.JSONField("還原結果", default=dict, blank=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    lease_until = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField("預檢有效期限", null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["tenant", "status"])]
        verbose_name = "還原工作"
        verbose_name_plural = "還原工作"

    def __str__(self) -> str:
        return f"#{self.pk} {self.tenant_id} {self.status}"


class TenantMaintenance(TimestampedModel):
    """公司維護鎖。還原進行中(或中斷後還沒確認一致)時,這家公司的操作一律擋下。"""

    tenant = models.OneToOneField(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="maintenance",
        verbose_name="公司",
    )
    active = models.BooleanField("維護中", default=False)
    reason = models.CharField("原因", max_length=200, blank=True)
    restore_job = models.ForeignKey(
        RestoreJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "公司維護鎖"
        verbose_name_plural = "公司維護鎖"

    def __str__(self) -> str:
        return f"{self.tenant_id}:{'on' if self.active else 'off'}"


class BackupAuditLog(models.Model):
    """備份 / 下載 / 驗證 / 還原的操作紀錄。只增不改。

    公司與操作者都另外存一份文字(公司識別碼、帳號名稱):紀錄不能因為
    帳號或公司後來被改掉就看不出當時是誰。
    """

    created_at = models.DateTimeField("時間", auto_now_add=True)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="公司",
    )
    tenant_uuid = models.CharField("公司識別碼", max_length=36, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="操作者",
    )
    actor_name = models.CharField("操作者帳號", max_length=150, blank=True)
    action = models.CharField("動作", max_length=40)
    ok = models.BooleanField("成功", default=True)
    backup_job = models.ForeignKey(
        BackupJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    restore_job = models.ForeignKey(
        RestoreJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    detail = models.JSONField("細節", default=dict, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["tenant", "-id"])]
        verbose_name = "備份操作紀錄"
        verbose_name_plural = "備份操作紀錄"

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_name} {self.action}"


def audit(tenant, actor, action, *, ok=True, backup_job=None, restore_job=None, **detail):
    """寫一筆操作紀錄。detail 裡不要放憑證或密碼。"""
    actor = actor if getattr(actor, "is_authenticated", False) else None
    return BackupAuditLog.objects.create(
        tenant=tenant,
        tenant_uuid=str(tenant.backup_uuid) if tenant is not None else "",
        actor=actor,
        actor_name=actor.get_username() if actor is not None else "系統",
        action=action, ok=ok, backup_job=backup_job, restore_job=restore_job,
        detail=detail,
    )
