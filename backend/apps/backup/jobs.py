"""備份工作的建立與執行。

網頁行程只負責「排進去」;真正匯出、加密、驗證由背景 worker 做
(`manage.py run_backup_worker`)。工作狀態都在資料庫裡:網頁關掉、換一台電腦、
worker 重啟,都看得到同一份工作。
"""
import hashlib
import os
import uuid
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from . import container, keys
from .export import ExportError, export_company
from .models import BackupJob, RestoreJob, TenantMaintenance, audit

LEASE = timedelta(minutes=15)
MAX_ATTEMPTS = 3


class BackupError(Exception):
    """備份相關、可以直接顯示給管理員的錯誤。"""


def backup_root() -> Path:
    root = Path(settings.BACKUP_ROOT)
    for sub in ("files", "tmp", "staging"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


# ── 「這個工作現在真的有人在做」的判斷 ──
# 光看租約時間不夠:工作跑得比租約久(大公司的還原)時,別的 worker 會以為它死了。
# 所以執行中的 worker 另外握著一把 PostgreSQL 的 session 層級 advisory lock,
# 行程或連線一斷就自動放掉。要回收一個工作之前先試著拿這把鎖:拿得到才是真的沒人在做。
def _lock_id(kind: str, pk: int) -> int:
    raw = hashlib.sha256(f"mppos-backup:{kind}:{pk}".encode()).digest()[:8]
    return int.from_bytes(raw, "big", signed=True)


def try_job_lock(kind: str, pk: int) -> bool:
    if connection.vendor != "postgresql":
        return True
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [_lock_id(kind, pk)])
        return bool(cur.fetchone()[0])


def release_job_lock(kind: str, pk: int) -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", [_lock_id(kind, pk)])


def job_is_abandoned(kind: str, pk: int) -> bool:
    """沒有任何 worker 握著這個工作 → True。只是探一下,馬上放掉。"""
    if not try_job_lock(kind, pk):
        return False
    release_job_lock(kind, pk)
    return True


@contextmanager
def holding_job(kind: str, pk: int):
    """執行工作的這段期間握著它的鎖。拿不到(別人正在做)就丟 BackupError。"""
    if not try_job_lock(kind, pk):
        raise BackupError("這個工作正在被別的程序處理")
    try:
        yield
    finally:
        try:
            release_job_lock(kind, pk)
        except Exception:  # noqa: BLE001 - 連線已經斷了的話鎖也跟著沒了
            pass


def in_maintenance(tenant) -> bool:
    return TenantMaintenance.objects.filter(tenant=tenant, active=True).exists()


def request_backup(tenant, user=None, *, kind=BackupJob.Kind.MANUAL, idempotency_key=""):
    """排一個備份工作。回傳 (job, 是不是新建的)。

    同一家公司同時只會有一個手動備份在排隊 / 執行:連點、重送、兩個人各按一次,
    拿到的都是同一個工作。
    """
    if keys.get_secret(tenant) is None:
        raise BackupError("還沒有復原憑證(或伺服器上的憑證讀不出來),請先設定")
    if kind == BackupJob.Kind.MANUAL and in_maintenance(tenant):
        raise BackupError("這家公司正在還原或維護中,暫時不能備份")
    with transaction.atomic():
        # 先鎖公司那一列。只對「進行中的工作」下 select_for_update 的話,還沒有任何
        # 工作時什麼都鎖不到,兩台電腦同時按就會各排一個。
        # 用 no_key:只跟「另一個也在排工作的人」互斥,不會被正在開單的交易擋住
        # (開單新增資料時,資料庫會對公司這一列上共享鎖)。
        from apps.tenants.models import Tenant

        Tenant.objects.select_for_update(no_key=True).get(pk=tenant.pk)
        active = (
            BackupJob.objects
            .filter(tenant=tenant, kind=kind,
                    status__in=[BackupJob.Status.QUEUED, BackupJob.Status.RUNNING])
            .first()
        )
        if active is not None:
            return active, False
        if idempotency_key:
            same = BackupJob.objects.filter(
                tenant=tenant, idempotency_key=idempotency_key
            ).first()
            if same is not None:
                return same, False
        try:
            with transaction.atomic():
                job = BackupJob.objects.create(
                    tenant=tenant, kind=kind, idempotency_key=idempotency_key or "",
                    requested_by=user if getattr(user, "is_authenticated", False) else None,
                )
        except IntegrityError:
            return BackupJob.objects.get(tenant=tenant, idempotency_key=idempotency_key), False
    audit(tenant, user, "backup.requested", backup_job=job, kind=kind)
    return job, True


def claim_next():
    """拿下一個該做的備份工作(排隊中的,或租約過期的)。沒有就回 None。"""
    now = timezone.now()
    with transaction.atomic():
        # 做到一半 worker 死掉的:租約過期。還有次數就重來,沒有就標失敗
        for stale in BackupJob.objects.select_for_update(skip_locked=True).filter(
            status=BackupJob.Status.RUNNING, lease_until__lt=now
        ):
            if not job_is_abandoned("backup", stale.pk):
                continue      # 租約過了但還有人在做(只是比較久),不要搶
            if stale.attempts >= MAX_ATTEMPTS:
                _fail(stale, "備份工作中斷多次,已停止重試")
            else:
                stale.status = BackupJob.Status.QUEUED
                stale.save(update_fields=["status", "updated_at"])
        job = (
            BackupJob.objects.select_for_update(skip_locked=True)
            .filter(status=BackupJob.Status.QUEUED).order_by("id").first()
        )
        if job is None:
            return None
        job.status = BackupJob.Status.RUNNING
        job.attempts += 1
        job.started_at = now
        job.lease_until = now + LEASE
        job.error = ""
        job.save(update_fields=[
            "status", "attempts", "started_at", "lease_until", "error", "updated_at",
        ])
        return job


def _fail(job, message):
    job.status = BackupJob.Status.FAILED
    job.error = str(message)[:2000]
    job.finished_at = timezone.now()
    job.lease_until = None
    job.save(update_fields=["status", "error", "finished_at", "lease_until", "updated_at"])
    audit(job.tenant, None, "backup.failed", ok=False, backup_job=job, error=job.error[:300])


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def run_backup(job) -> BackupJob:
    """執行一個已經被 claim 的備份工作。成功 = 檔案封裝好、再解開驗證過。

    狀態的寫入都在匯出那個唯讀快照交易**之外**:匯出前標「產生中」,
    匯出完、驗證完才標「已驗證」。中途任何失敗都不會留下可下載的半份檔。
    """
    try:
        with holding_job("backup", job.pk):
            return _run_backup(job)
    except BackupError:
        return job        # 別的 worker 正在做同一個工作:讓它做


def _run_backup(job) -> BackupJob:
    root = backup_root()
    secret = keys.get_secret(job.tenant)
    if secret is None:
        _fail(job, "伺服器上的復原憑證讀不出來,請管理員重新輸入憑證")
        return job
    # 暫存檔名帶上「第幾次嘗試」:萬一同一個工作被兩個行程碰到,也不會互相蓋檔
    stem = f"{job.backup_id}.{job.attempts}.{os.getpid()}"
    plain = root / "tmp" / f"{stem}.zip"
    partial = root / "tmp" / f"{stem}.part"
    check = root / "tmp" / f"{stem}.check"
    final_name = f"files/{job.tenant.backup_uuid}/{job.backup_id}.mppos-backup"
    final = root / final_name
    try:
        manifest = export_company(job.tenant, plain, job.backup_id)
        digest = container.encrypt_file(
            plain, partial, secret, key_fingerprint=keys.fingerprint(secret)
        )
        # 封裝完再整包解開一次:確認這份檔用這組憑證真的打得開、內容沒壞
        container.decrypt_file(partial, check, secret)
        if container.sha256_file(check) != container.sha256_file(plain):
            raise ExportError("備份檔封裝後驗證失敗")
        # 再用「還原時的那一套檢查」看一遍。這樣「已驗證」的意思是:這份檔現在
        # 拿去還原,檢查會過 —— 不會等到真的要救資料那天才發現它不能用。
        from . import restore

        try:
            with restore.Package(None, None, plain_path=check) as pkg:
                report = restore.validate(job.tenant, pkg, RestoreJob.Mode.ROLLBACK)
        except restore.RestoreError as exc:
            raise ExportError(f"備份檔沒有通過還原檢查:{exc}")
        if not report["ok"]:
            raise ExportError(
                "備份檔沒有通過還原檢查:" + ";".join(report["problems"][:3])
            )
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(partial, final)          # 同一個檔案系統內是原子動作
        os.chmod(final, 0o600)
    except ExportError as exc:
        _remove(partial)
        _fail(job, exc)
        return job
    except Exception as exc:  # noqa: BLE001 - 任何意外都要落成「失敗」而不是卡在產生中
        _remove(partial)
        _fail(job, f"備份產生失敗:{exc}")
        return job
    finally:
        _remove(plain)
        _remove(check)

    now = timezone.now()
    job.status = BackupJob.Status.VERIFIED
    job.file_name = final_name
    job.file_size = final.stat().st_size
    job.file_sha256 = digest
    job.snapshot_at = manifest["snapshot_at"]
    job.summary = {
        "company": manifest["company"]["name"],
        "warehouses": [w["name"] for w in manifest["warehouses"]],
        "tables": manifest["tables"],
        "rows": sum(manifest["tables"].values()),
        "attachments": len(manifest["attachments"]),
        "schema_fingerprint": manifest["schema_fingerprint"],
        "key_fingerprint": keys.fingerprint(secret),
    }
    job.finished_at = now
    job.lease_until = None
    job.expires_at = now + timedelta(hours=settings.BACKUP_RETENTION_HOURS)
    job.save()
    audit(job.tenant, None, "backup.verified", backup_job=job,
          size=job.file_size, rows=job.summary["rows"])
    return job


def expire_old():
    """到期的備份:刪伺服器上那份檔,狀態改成已過期。安全備份不自動清。"""
    now = timezone.now()
    root = backup_root()
    done = 0
    for job in BackupJob.objects.filter(
        status=BackupJob.Status.VERIFIED, kind=BackupJob.Kind.MANUAL, expires_at__lt=now
    ):
        if job.file_name:
            _remove(root / job.file_name)
        job.status = BackupJob.Status.EXPIRED
        job.save(update_fields=["status", "updated_at"])
        done += 1
    return done


def file_path(job) -> Path:
    """可下載的檔案路徑;不該下載(狀態不對 / 過期 / 檔案不在)就丟 BackupError。"""
    if job.status == BackupJob.Status.EXPIRED or (
        job.expires_at and job.expires_at < timezone.now()
        and job.kind == BackupJob.Kind.MANUAL
    ):
        raise BackupError("這份備份已經過期,請重新備份")
    if job.status != BackupJob.Status.VERIFIED or not job.file_name:
        raise BackupError("這份備份還沒有可以下載的檔案")
    path = backup_root() / job.file_name
    if not path.is_file():
        raise BackupError("伺服器上找不到這份備份檔,請重新備份")
    return path


def new_backup_id():
    return uuid.uuid4()
