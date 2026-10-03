"""公司備份與還原的 API。

只有**這家公司的管理員**能用:一般店員不行;平台管理員也不行 —— 平台維運走
主機上的管理指令,不能因為有平台角色就從一般網址跨進別家公司的備份。
每一支都從「登入者自己的公司」出發找資料(不看 ?tenant=),查工作、下載、驗證、
還原每一次都重新檢查。
"""
import hashlib
import secrets

from datetime import timedelta

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from apps.inventory.models import Warehouse

from . import jobs, keys, restore
from .models import (
    BackupAuditLog,
    BackupJob,
    BackupKey,
    DownloadTicket,
    RestoreJob,
    TenantMaintenance,
    audit,
)

TICKET_TTL = 60          # 下載票券幾秒內有效
CONFIRM_WORD = "還原"


class IsCompanyAdmin(permissions.BasePermission):
    message = "需要公司管理員權限"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or not user.is_active:
            return False
        profile = getattr(user, "profile", None)
        return bool(profile and profile.role == "tenant_admin" and profile.tenant_id)


def _company(request):
    return request.user.profile.tenant


def _job_data(job):
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "status_label": job.get_status_display(),
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "snapshot_at": job.snapshot_at,
        "expires_at": job.expires_at,
        "file_size": job.file_size,
        "file_sha256": job.file_sha256,
        "summary": job.summary,
        "error": job.error,
        "requested_by": job.requested_by.get_username() if job.requested_by else "",
        "download_started_at": job.download_started_at,
        "local_verified_at": job.local_verified_at,
    }


def _restore_data(job):
    return {
        "id": job.id,
        "mode": job.mode,
        "status": job.status,
        "status_label": job.get_status_display(),
        "created_at": job.created_at,
        "expires_at": job.expires_at,
        "confirmed_at": job.confirmed_at,
        "finished_at": job.finished_at,
        "report": job.report,
        "result": job.result,
        "error": job.error,
        "safety_backup": job.safety_backup_id,
        "confirm_word": CONFIRM_WORD,
    }


def _bad(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"detail": str(message)}, status=code)


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def overview(request):
    tenant = _company(request)
    key = BackupKey.objects.filter(tenant=tenant).first()
    last_ok = BackupJob.objects.filter(
        tenant=tenant, kind=BackupJob.Kind.MANUAL,
        status__in=[BackupJob.Status.VERIFIED, BackupJob.Status.EXPIRED],
    ).first()
    last_restore = RestoreJob.objects.filter(
        tenant=tenant, status=RestoreJob.Status.DONE
    ).first()
    maint = (
        TenantMaintenance.objects.filter(tenant=tenant, active=True)
        .select_related("restore_job").first()
    )
    held = maint.restore_job if maint else None
    return Response({
        "company": tenant.name,
        "warehouses": list(
            Warehouse.objects.filter(tenant=tenant).order_by("id").values_list("name", flat=True)
        ),
        "key": {
            "exists": key is not None,
            "fingerprint": key.fingerprint if key else "",
            "acknowledged": bool(key and key.acknowledged_at),
            "readable": keys.get_secret(tenant) is not None,
        },
        "last_backup": _job_data(last_ok) if last_ok else None,
        "last_restore": _restore_data(last_restore) if last_restore else None,
        "maintenance": {
            "active": bool(maint),
            "reason": maint.reason if maint else "",
            "restore_job": held.pk if held else None,
            "restore_status": held.status if held else "",
            # 還在排隊的可以取消;被中斷的才需要「解除維護」
            "can_cancel": bool(held and held.status == RestoreJob.Status.QUEUED),
            "can_release": bool(maint and (
                held is None or held.status not in (
                    RestoreJob.Status.QUEUED, RestoreJob.Status.RUNNING,
                )
            )),
        },
        "retention_hours": settings.BACKUP_RETENTION_HOURS,
    })


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def key_create(request):
    tenant = _company(request)
    try:
        key, text = keys.create_key(tenant, request.user)
    except keys.KeyError_ as exc:
        return _bad(exc, status.HTTP_409_CONFLICT)
    audit(tenant, request.user, "key.created", fingerprint=key.fingerprint)
    return Response({"credential": text, "fingerprint": key.fingerprint},
                    status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def key_reveal(request):
    """再看一次憑證(例:當初沒抄好)。每看一次都留紀錄。"""
    tenant = _company(request)
    secret = keys.get_secret(tenant)
    if secret is None:
        return _bad("伺服器上沒有可讀的憑證", status.HTTP_404_NOT_FOUND)
    audit(tenant, request.user, "key.revealed", fingerprint=keys.fingerprint(secret))
    return Response({"credential": keys.format_secret(secret),
                     "fingerprint": keys.fingerprint(secret)})


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def key_acknowledge(request):
    tenant = _company(request)
    updated = BackupKey.objects.filter(tenant=tenant).update(acknowledged_at=timezone.now())
    if not updated:
        return _bad("還沒有復原憑證", status.HTTP_404_NOT_FOUND)
    audit(tenant, request.user, "key.acknowledged")
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def key_register(request):
    """伺服器上的憑證讀不出來時(換過系統金鑰),把手上那份重新登記進來。"""
    tenant = _company(request)
    try:
        key = keys.register_key(tenant, request.data.get("credential", ""), request.user)
    except keys.KeyError_ as exc:
        audit(tenant, request.user, "key.registered", ok=False)
        return _bad(exc, status.HTTP_409_CONFLICT)
    audit(tenant, request.user, "key.registered", fingerprint=key.fingerprint)
    return Response({"fingerprint": key.fingerprint})


@api_view(["GET", "POST"])
@permission_classes([IsCompanyAdmin])
def backup_jobs(request):
    tenant = _company(request)
    if request.method == "GET":
        jobs.expire_old()
        rows = BackupJob.objects.filter(tenant=tenant).select_related("requested_by")[:30]
        return Response({"results": [_job_data(j) for j in rows]})
    try:
        job, created = jobs.request_backup(
            tenant, request.user,
            idempotency_key=str(request.data.get("idempotency_key", ""))[:64],
        )
    except jobs.BackupError as exc:
        return _bad(exc, status.HTTP_409_CONFLICT)
    return Response(
        _job_data(job),
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


def _own_job(request, pk):
    # 只找自己公司的;別家的編號猜中了也是「找不到」
    return BackupJob.objects.filter(tenant=_company(request), pk=pk).first()


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def backup_job_detail(request, pk):
    job = _own_job(request, pk)
    if job is None:
        return _bad("找不到這個備份工作", status.HTTP_404_NOT_FOUND)
    return Response(_job_data(job))


def _ticket_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def download_ticket(request, pk):
    """換一張短效、只能用一次的下載票券。

    瀏覽器要把檔案直接存到硬碟(不先整包讀進記憶體),得用一般的網址下載,
    而一般的網址帶不了登入標頭。所以先用登入身分換票,再用票下載。
    """
    job = _own_job(request, pk)
    if job is None:
        return _bad("找不到這個備份工作", status.HTTP_404_NOT_FOUND)
    try:
        jobs.file_path(job)
    except jobs.BackupError as exc:
        return _bad(exc, status.HTTP_409_CONFLICT)
    token = secrets.token_urlsafe(32)
    now = timezone.now()
    DownloadTicket.objects.filter(expires_at__lt=now - timedelta(hours=1)).delete()
    DownloadTicket.objects.create(
        token_hash=_ticket_hash(token), job=job, user=request.user,
        expires_at=now + timedelta(seconds=TICKET_TTL),
    )
    return Response({"ticket": token, "expires_in": TICKET_TTL})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def download(request):
    """用票券下載。票券只能用一次;用的當下再檢查一次這個人現在還有沒有資格。"""
    from django.contrib.auth import get_user_model

    token = request.GET.get("ticket", "")
    now = timezone.now()
    # 「標成已使用」這一句同時也是檢查:兩個請求拿同一張票,只有一個改得到
    claimed = DownloadTicket.objects.filter(
        token_hash=_ticket_hash(token), used_at__isnull=True, expires_at__gt=now
    ).update(used_at=now) if token else 0
    if not claimed:
        return _bad("下載連結已失效,請回到備份頁重新按下載", status.HTTP_403_FORBIDDEN)
    ticket = DownloadTicket.objects.get(token_hash=_ticket_hash(token))
    user = get_user_model().objects.filter(pk=ticket.user_id, is_active=True).first()
    profile = getattr(user, "profile", None) if user else None
    job = BackupJob.objects.filter(pk=ticket.job_id).select_related("tenant").first()
    if (
        job is None or profile is None or profile.role != "tenant_admin"
        or profile.tenant_id != job.tenant_id
    ):
        return _bad("沒有下載這份備份的權限", status.HTTP_403_FORBIDDEN)
    try:
        path = jobs.file_path(job)
    except jobs.BackupError as exc:
        return _bad(exc, status.HTTP_409_CONFLICT)
    if job.download_started_at is None:
        BackupJob.objects.filter(pk=job.pk).update(download_started_at=timezone.now())
    audit(job.tenant, user, "backup.download_started", backup_job=job)
    stamp = timezone.localtime(job.snapshot_at or job.created_at).strftime("%Y%m%d-%H%M")
    response = FileResponse(
        open(path, "rb"), as_attachment=True,
        filename=f"MPPOS備份_{job.tenant.code}_{stamp}.mppos-backup",
        content_type="application/octet-stream",
    )
    response["Content-Length"] = str(job.file_size)
    response["Cache-Control"] = "no-store"
    return response


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def verify_local(request, pk):
    """使用者重新選取存到硬碟的檔案,瀏覽器算出雜湊送上來比對。

    一樣才算「已驗證本機檔案」。「開始下載」不能證明檔案真的寫進硬碟了。
    """
    job = _own_job(request, pk)
    if job is None:
        return _bad("找不到這個備份工作", status.HTTP_404_NOT_FOUND)
    if not job.file_sha256:
        return _bad("這個備份沒有產生檔案", status.HTTP_409_CONFLICT)
    sha = str(request.data.get("sha256", "")).lower()
    size = request.data.get("size")
    if size is not None:
        try:
            size = int(str(size))
        except ValueError:
            return _bad("檔案大小的格式不對")
    if sha != job.file_sha256 or (size is not None and size != job.file_size):
        audit(job.tenant, request.user, "backup.local_verify", ok=False, backup_job=job)
        return _bad("這個檔案跟伺服器產生的那份不一樣(可能沒有下載完,或選到別的檔)")
    job.local_verified_at = timezone.now()
    job.save(update_fields=["local_verified_at", "updated_at"])
    audit(job.tenant, request.user, "backup.local_verify", backup_job=job)
    return Response(_job_data(job))


@api_view(["GET", "POST"])
@permission_classes([IsCompanyAdmin])
def restores(request):
    tenant = _company(request)
    if request.method == "GET":
        rows = RestoreJob.objects.filter(tenant=tenant)[:20]
        return Response({"results": [_restore_data(j) for j in rows]})
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return _bad("請選擇備份檔")
    if jobs.in_maintenance(tenant):
        return _bad("這家公司正在還原或維護中", status.HTTP_409_CONFLICT)
    try:
        job = restore.stage_upload(
            tenant, uploaded, request.user,
            credential=str(request.data.get("credential", "")).strip(),
        )
    except restore.RestoreError as exc:
        return _bad(exc)
    return Response(_restore_data(job), status=status.HTTP_201_CREATED)


def _own_restore(request, pk):
    return RestoreJob.objects.filter(tenant=_company(request), pk=pk).first()


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def restore_detail(request, pk):
    job = _own_restore(request, pk)
    if job is None:
        return _bad("找不到這個還原工作", status.HTTP_404_NOT_FOUND)
    return Response(_restore_data(job))


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def restore_confirm(request, pk):
    job = _own_restore(request, pk)
    if job is None:
        return _bad("找不到這個還原工作", status.HTTP_404_NOT_FOUND)
    if str(request.data.get("confirm", "")).strip() != CONFIRM_WORD:
        return _bad(f"請輸入「{CONFIRM_WORD}」確認")
    try:
        job = restore.confirm(job, request.user)
    except restore.RestoreError as exc:
        return _bad(exc, status.HTTP_409_CONFLICT)
    return Response(_restore_data(job))


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def restore_cancel(request, pk):
    job = _own_restore(request, pk)
    if job is None:
        return _bad("找不到這個還原工作", status.HTTP_404_NOT_FOUND)
    try:
        job = restore.cancel(job, request.user, reason="管理員取消")
    except restore.RestoreError as exc:
        return _bad(exc, status.HTTP_409_CONFLICT)
    return Response(_restore_data(job))


@api_view(["POST"])
@permission_classes([IsCompanyAdmin])
def maintenance_release(request):
    try:
        restore.release_after_interruption(_company(request), request.user)
    except restore.RestoreError as exc:
        return _bad(exc, status.HTTP_409_CONFLICT)
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([IsCompanyAdmin])
def audit_log(request):
    rows = BackupAuditLog.objects.filter(tenant=_company(request))[:100]
    return Response({"results": [
        {"at": r.created_at, "who": r.actor_name, "action": r.action, "ok": r.ok,
         "backup_job": r.backup_job_id, "restore_job": r.restore_job_id}
        for r in rows
    ]})

