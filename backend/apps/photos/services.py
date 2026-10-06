"""商品照片的規則:照片作業、手機配對、隨商品存檔。

重點只有三件:
1. **照片先放在「這一次作業」上**,商品存檔的那個交易裡才掛到商品;取消、存檔失敗都不會動到商品原本的照片。
2. **手機配對綁的是這一次作業**,不是商品、不是登入的人:電腦換商品 / 取消 / 存完,那支手機就傳不進來,
   遲到的照片也不會被掛到下一筆商品。QR Code 裡的憑證只能做「對這一份作業傳照片」這一件事。
3. **同一張照片重試不會變兩張;取消過的不會因為上傳晚到又冒出來**(每張照片有自己的識別,取消留著紀錄)。
"""
import hashlib
import secrets
import uuid
from datetime import timedelta

from django.core import signing
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from . import imaging
from .models import PhotoDraft, PhotoUpload, ProductPhoto

PAIR_TTL = timedelta(minutes=3)        # QR Code 多久沒人掃就失效
DEVICE_IDLE = timedelta(minutes=10)    # 手機多久沒有動作(拍照 / 上傳)就結束
DEVICE_MAX = timedelta(minutes=60)     # 一次配對最長多久
DRAFT_TTL = timedelta(hours=24)        # 作業放多久沒存就清掉
CLOSED_KEEP = timedelta(hours=1)       # 結束的作業留多久(晚到的手機還查得到「已結束」)
MAX_PHOTOS = 10                        # 一個商品最多幾張
MAX_PENDING = 20                       # 一次作業裡最多暫存幾張(傳好的 + 還在傳的)
MAX_ROWS = 80                          # 一次作業最多記幾筆(含取消、失敗的):擋有人拿憑證一直灌
URL_MAX_AGE = 7 * 24 * 3600            # 照片網址的簽章有效多久
_SALT = "product-photo-file"


class PhotoRuleError(Exception):
    """照片這邊不讓做(原因會顯示給使用者)。code:gone = 作業 / 配對已經不在了。"""

    def __init__(self, message, code="invalid"):
        super().__init__(message)
        self.code = code


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── 照片網址 ─────────────────────────────────────────────────
# 照片用 <img> 顯示,帶不了登入的憑證;網址本身帶簽章(只發給看得到那個商品的人,過幾天失效)。
def file_token(kind: str, pk: int, variant: str) -> str:
    return signing.dumps([kind, pk, variant], salt=_SALT, compress=True)


def read_file_token(token: str):
    try:
        kind, pk, variant = signing.loads(token, salt=_SALT, max_age=URL_MAX_AGE)
    except Exception:
        return None
    if kind not in ("p", "u") or variant not in ("f", "t"):
        return None
    return kind, int(pk), variant


def photo_urls(kind: str, pk: int) -> dict:
    return {
        "image_url": f"/api/v1/photo-file/{file_token(kind, pk, 'f')}/",
        "thumb_url": f"/api/v1/photo-file/{file_token(kind, pk, 't')}/",
    }


def _delete_files(names):
    for name in names:
        if not name:
            continue
        try:
            default_storage.delete(name)
        except Exception:
            pass  # 刪不掉就留著,不讓它擋住正事


# ── 照片作業 ─────────────────────────────────────────────────
def new_draft(tenant, user, product=None, label="", spec="") -> PhotoDraft:
    return PhotoDraft.objects.create(
        tenant=tenant, created_by=user, product=product,
        label=(label or "")[:160], spec=(spec or "")[:160],
    )


def get_draft(tenant, user, uid, lock=False) -> PhotoDraft:
    """只有開這份作業的人拿得到(別人的作業、別家公司的作業都當作不存在)。"""
    try:
        uid = uuid.UUID(str(uid))
    except (ValueError, TypeError):
        raise PhotoRuleError("找不到這次照片作業", "gone")
    qs = PhotoDraft.objects.filter(tenant=tenant, created_by=user, uid=uid)
    if lock:
        qs = qs.select_for_update()
    draft = qs.first()
    if draft is None:
        raise PhotoRuleError("找不到這次照片作業", "gone")
    return draft


def _open_or_raise(draft):
    if draft.state != PhotoDraft.State.OPEN:
        raise PhotoRuleError("這次照片作業已經結束", "gone")


def _same_pair(locked, pair) -> None:
    """手機的動作:鎖住作業之後再核對一次「還是不是當初驗過的那一次配對」。

    手機的請求先驗憑證(`phone_draft`)、後做事,中間電腦可能按了「重新產生」、換了另一支手機連上。
    不再核對的話,舊手機還在路上的那個請求照樣寫得進來,甚至把新手機的配對結束掉。
    pair = 驗過的那一次配對(`pair_of(draft)`);電腦這邊的動作不帶(None)。
    """
    if pair is None:
        return
    if not locked.pair_hash or (locked.pair_hash, locked.device_hash) != pair:
        raise PhotoRuleError("要再拍,請在電腦按「重新產生」再掃一次", "gone")


def _pending(draft) -> int:
    """這份作業裡佔名額的照片:傳好的 + 還在傳的(失敗、取消的不算)。"""
    return PhotoUpload.objects.filter(
        draft=draft, status__in=[PhotoUpload.Status.UPLOADING, PhotoUpload.Status.READY]
    ).count()


def pair_of(draft) -> tuple[str, str]:
    """這份作業現在是哪一次配對、哪一支手機(都是雜湊)。`phone_draft()` 驗完當下拿。"""
    return (draft.pair_hash, draft.device_hash)


def _reserve(draft, uid: str, source: str, pair=None) -> PhotoUpload:
    """登記「這一張要傳了」。同一張(同一個 uid)只會有一筆;取消過的不會復活。
    之前沒傳成功的那一張再傳一次:狀態回到「上傳中」(存檔會等它)。"""
    uid = (uid or "").strip()
    if not uid or len(uid) > 64:
        raise PhotoRuleError("照片識別不對")
    with transaction.atomic():
        locked = PhotoDraft.objects.select_for_update().get(pk=draft.pk)
        _open_or_raise(locked)
        _same_pair(locked, pair)
        row = PhotoUpload.objects.select_for_update().filter(draft=locked, uid=uid).first()
        if row is not None:
            # 手機只能動手機自己傳的那幾張(電腦那幾張的識別它本來就看不到,猜到也不行)
            if source == PhotoUpload.Source.PHONE and row.source != PhotoUpload.Source.PHONE:
                raise PhotoRuleError("照片識別不對")
            if row.status == PhotoUpload.Status.CANCELLED:
                raise PhotoRuleError("這一張已經取消了", "cancelled")
            if row.status == PhotoUpload.Status.FAILED:
                # 重試:回到「上傳中」。電腦正在儲存的話不收(清單已經定了);名額滿了也不收
                if locked.frozen:
                    raise PhotoRuleError("電腦正在儲存,這一張沒有加入", "frozen")
                if _pending(locked) >= MAX_PENDING:
                    raise PhotoRuleError(f"一次最多放 {MAX_PENDING} 張,請先移掉幾張")
                row.status, row.error = PhotoUpload.Status.UPLOADING, ""
                row.save(update_fields=["status", "error", "updated_at"])
                locked.save(update_fields=["updated_at"])
            return row
        if locked.frozen:
            raise PhotoRuleError("電腦正在儲存,這一張沒有加入", "frozen")
        if _pending(locked) >= MAX_PENDING:
            raise PhotoRuleError(f"一次最多放 {MAX_PENDING} 張,請先移掉幾張")
        if PhotoUpload.objects.filter(draft=locked).count() >= MAX_ROWS:
            raise PhotoRuleError("這一次加過的照片太多了,請關掉表單重新開一次")
        # 還在用的作業不算「放太久」(清理看的是作業最後一次有動靜的時間)
        locked.save(update_fields=["updated_at"])
        return PhotoUpload.objects.create(
            tenant=locked.tenant, draft=locked, uid=uid, source=source,
        )


def announce(draft, uid: str, source: str, pair=None) -> PhotoUpload:
    """手機先講「這一張要傳了」,電腦那邊就看得到一格「上傳中」。"""
    return _reserve(draft, uid, source, pair)


def add_upload(draft, uid: str, fileobj, source: str, pair=None) -> PhotoUpload:
    """收一張照片。已經收過(同一個 uid)就回原本那一筆,不會變成兩張。

    **整段(登記 → 處理圖片 → 落檔)都握著這份作業的鎖。** 處理圖片要零點幾秒到一兩秒,這段時間:
    同一張的另一次傳、取消、手機重新配對、電腦存檔都得等它做完 —— 所以不會有「一次傳失敗把另一次還在處理的蓋成失敗」、
    「圖片處理到一半配對換人了還是寫進去」、「存檔沒等到還在處理的那一張」這幾種交錯。
    代價是同一份作業的照片一次只處理一張(也順便擋住同時解好幾張大圖吃光記憶體)。
    """
    written = []
    failure = None
    try:
        with transaction.atomic():
            # _reserve 會鎖住作業那一列;包在這個交易裡,鎖一直握到下面做完
            row = _reserve(draft, uid, source, pair)
            if row.status == PhotoUpload.Status.READY:
                return row
            try:
                full, thumb, width, height = imaging.process(fileobj)
            except imaging.PhotoError as exc:
                row.status, row.error = PhotoUpload.Status.FAILED, str(exc)[:200]
                row.save(update_fields=["status", "error", "updated_at"])
                failure = str(exc)
            else:
                stem = uuid.uuid4().hex
                row.image.save(f"{stem}.jpg", ContentFile(full), save=False)
                written.append(row.image.name)
                row.thumb.save(f"{stem}_t.jpg", ContentFile(thumb), save=False)
                written.append(row.thumb.name)
                row.width, row.height = width, height
                row.status, row.error = PhotoUpload.Status.READY, ""
                row.save()
                PhotoDraft.objects.filter(pk=draft.pk).update(updated_at=timezone.now())
    except Exception:
        # 檔案已經寫到硬碟、資料卻沒存成:檔案不留(不然沒有任何一筆資料指著它,永遠清不到)
        _delete_files(written)
        raise
    if failure is not None:
        # 「沒傳成功」已經記下來了(交易成立之後才往外丟,不然那一筆記錄會跟著退回)
        raise PhotoRuleError(failure)
    return row


def cancel_upload(draft, uid: str, by=PhotoUpload.Source.DESKTOP, pair=None) -> None:
    """取消一張(傳到一半、傳失敗、或不要了)。留著「已取消」的紀錄:晚到的上傳不會讓它又出現。

    by = 誰取消的。電腦可以拿掉任何一張(包含手機傳來的);手機只能取消手機自己傳的。
    """
    uid = (uid or "").strip()
    if not uid or len(uid) > 64:
        return
    with transaction.atomic():
        locked = PhotoDraft.objects.select_for_update().get(pk=draft.pk)
        if locked.state != PhotoDraft.State.OPEN:
            return
        _same_pair(locked, pair)
        row = PhotoUpload.objects.select_for_update().filter(draft=locked, uid=uid).first()
        if row is None:
            # 還沒見過的識別(取消比上傳先到):記一筆「已取消」。有上限:不讓人一直灌
            if PhotoUpload.objects.filter(draft=locked).count() < MAX_ROWS:
                PhotoUpload.objects.create(
                    tenant=locked.tenant, draft=locked, uid=uid, source=by,
                    status=PhotoUpload.Status.CANCELLED,
                )
            return
        if by == PhotoUpload.Source.PHONE and row.source != PhotoUpload.Source.PHONE:
            return
        if row.consumed:
            return
        names = [row.image.name, row.thumb.name]
        row.image, row.thumb = "", ""
        row.status = PhotoUpload.Status.CANCELLED
        row.save()
        transaction.on_commit(lambda: _delete_files(names))


def set_frozen(draft, frozen: bool) -> None:
    PhotoDraft.objects.filter(pk=draft.pk, state=PhotoDraft.State.OPEN).update(frozen=frozen)


def _drop_loose_files(draft) -> None:
    """這份作業裡還沒掛到商品的暫存檔:資料標成已取消、檔案在交易成立後刪掉。要在交易裡、作業已經鎖住時呼叫。"""
    names = []
    for row in PhotoUpload.objects.select_for_update().filter(draft=draft, consumed=False):
        if not (row.image.name or row.thumb.name):
            continue
        names += [row.image.name, row.thumb.name]
        row.image, row.thumb = "", ""
        row.status = PhotoUpload.Status.CANCELLED
        row.save(update_fields=["image", "thumb", "status", "updated_at"])
    if names:
        transaction.on_commit(lambda: _delete_files(names))


def cancel_draft(draft) -> None:
    """整份作業不要了(取消新增 / 取消編輯 / 換商品):配對一起撤銷,這次傳上來的暫存照片當下就刪。"""
    with transaction.atomic():
        locked = PhotoDraft.objects.select_for_update().filter(pk=draft.pk).first()
        if locked is None or locked.state != PhotoDraft.State.OPEN:
            return
        locked.state = PhotoDraft.State.CANCELLED
        locked.closed_at = timezone.now()
        locked.pair_hash, locked.device_hash, locked.frozen = "", "", False
        locked.save()
        _drop_loose_files(locked)


# ── 手機配對 ─────────────────────────────────────────────────
def start_pair(draft) -> str:
    """產生一張新的 QR Code(舊的那張、連著的那支手機都作廢)。回憑證本身:只在這一刻看得到。"""
    token = secrets.token_urlsafe(32)
    with transaction.atomic():
        locked = PhotoDraft.objects.select_for_update().get(pk=draft.pk)
        _open_or_raise(locked)
        locked.pair_hash = _hash(token)
        locked.pair_expires_at = timezone.now() + PAIR_TTL
        locked.device_hash = ""
        locked.paired_at = None
        locked.device_active_at = None
        locked.save()
    return token


def end_pair(draft, pair=None) -> None:
    """結束手機拍照。pair 有給(手機自己按「完成」)= 只結束它自己那一次配對:
    電腦已經重新產生、換別支手機連上了,舊手機晚到的「完成」不能把新的那一次結束掉。"""
    rows = PhotoDraft.objects.filter(pk=draft.pk)
    if pair is not None:
        rows = rows.filter(pair_hash=pair[0], device_hash=pair[1]).exclude(pair_hash="")
    rows.update(pair_hash="", device_hash="", pair_expires_at=None)


def still_paired(draft_pk, pair) -> bool:
    """回應手機之前再看一次:還是不是它那一次配對(不是的話不能把這份作業的內容回給它)。"""
    return PhotoDraft.objects.filter(
        pk=draft_pk, state=PhotoDraft.State.OPEN, pair_hash=pair[0], device_hash=pair[1],
    ).exclude(pair_hash="").exists()


def pair_status(draft, now=None) -> str:
    """none 沒在配對 / waiting 等手機掃 / expired QR 過期了沒人掃 / connected 手機連著 / idle 手機太久沒動作。"""
    now = now or timezone.now()
    if not draft.pair_hash or draft.state != PhotoDraft.State.OPEN:
        return "none"
    if not draft.device_hash:
        return "waiting" if draft.pair_expires_at and now <= draft.pair_expires_at else "expired"
    if draft.paired_at and now - draft.paired_at > DEVICE_MAX:
        return "idle"
    if draft.device_active_at and now - draft.device_active_at > DEVICE_IDLE:
        return "idle"
    return "connected"


def phone_draft(token: str, device: str, claim=False, active=False) -> PhotoDraft:
    """手機拿 QR Code 的憑證進來。claim = 掃碼那一下(可以綁手機);active = 這是一次「動作」(延長閒置時間)。"""
    token, device = (token or "").strip(), (device or "").strip()
    if not token or not device or len(device) > 128:
        raise PhotoRuleError("要再拍,請在電腦按「重新產生」再掃一次", "gone")
    now = timezone.now()
    with transaction.atomic():
        draft = (
            PhotoDraft.objects.select_for_update()
            .filter(pair_hash=_hash(token)).first()
        )
        if draft is None or draft.state != PhotoDraft.State.OPEN:
            raise PhotoRuleError("要再拍,請在電腦按「重新產生」再掃一次", "gone")
        if not draft.device_hash:
            if not claim:
                raise PhotoRuleError("請重新掃描 QR Code", "gone")
            if not draft.pair_expires_at or now > draft.pair_expires_at:
                raise PhotoRuleError("QR Code 過期了,請在電腦按「重新產生」再掃一次", "expired")
            draft.device_hash = _hash(device)
            draft.paired_at = now
            draft.device_active_at = now
            draft.save(update_fields=["device_hash", "paired_at", "device_active_at", "updated_at"])
            return draft
        if draft.device_hash != _hash(device):
            raise PhotoRuleError(
                "已經有另一支手機連上了。要換手機,請在電腦按「重新產生」", "taken"
            )
        if pair_status(draft, now) == "idle":
            raise PhotoRuleError("太久沒有動作,已經結束。請在電腦按「重新產生」再掃一次", "expired")
        if active or claim:
            draft.device_active_at = now
            draft.save(update_fields=["device_active_at", "updated_at"])
        return draft


# ── 隨商品存檔 ───────────────────────────────────────────────
def committed_product(tenant, user, draft_uid):
    """這份作業是不是已經跟著某個商品存好了(新增商品重送時:回那個商品,不建第二個品號)。"""
    try:
        draft = get_draft(tenant, user, draft_uid)
    except PhotoRuleError:
        return None
    if draft.state == PhotoDraft.State.COMMITTED and draft.product_id:
        return draft.product
    return None


def apply_to_product(product, payload, user, created=False) -> None:
    """商品存檔的**同一個交易裡**呼叫:把這次作業定下來的照片清單套到商品上。

    payload = {"draft": 作業識別, "seen": [開表單時這個商品有哪幾張照片的編號],
               "items": [{"photo": 編號} 或 {"upload": 上傳識別}, 另帶 caption / is_primary]}
    items 的順序就是顯示順序;商品原本有、清單裡沒有的照片 = 移除。沒帶 payload = 照片不動。
    **編輯既有商品一定要帶 seen**,而且要跟商品現在的照片一樣:不一樣 = 開表單之後別人改過這個商品的照片
    (加了一張、刪了一張),這張表單沒看過的照片不能被當成「移除」→ 整筆退回,請他重開表單。
    created = 這個商品是這一次存檔才建的。**新增商品開的作業(沒有綁商品)只能用在這一次新建的商品上;
    編輯既有商品只收「為這個商品開的」作業** —— 新增時加的照片不能被拿去蓋掉別的既有商品的照片。
    """
    if not payload:
        return
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise PhotoRuleError("照片清單格式不對")
    draft = get_draft(product.tenant, user, payload.get("draft"), lock=True)
    if draft.state == PhotoDraft.State.COMMITTED and draft.product_id == product.id:
        return  # 同一份作業重送:已經套過了
    _open_or_raise(draft)
    if created:
        if draft.product_id:
            raise PhotoRuleError("這次照片作業是另一個商品的")
    elif draft.product_id != product.id:
        raise PhotoRuleError(
            "這次照片作業是另一個商品的" if draft.product_id
            else "這些照片是新增商品時加的,不能直接放到既有的商品上"
        )
    items = payload["items"]
    if len(items) > MAX_PHOTOS:
        raise PhotoRuleError(f"一個商品最多 {MAX_PHOTOS} 張照片")

    uploads = {u.uid: u for u in PhotoUpload.objects.select_for_update().filter(draft=draft)}
    waiting = [u for u in uploads.values() if u.status == PhotoUpload.Status.UPLOADING]
    if waiting:
        raise PhotoRuleError(f"還有 {len(waiting)} 張照片尚未完成,等傳完或取消之後再儲存")
    existing = {p.id: p for p in ProductPhoto.objects.select_for_update().filter(product=product)}
    if not created:
        seen = payload.get("seen")
        if not isinstance(seen, list) or not all(type(x) is int for x in seen):
            raise PhotoRuleError("照片清單格式不對")
        if set(seen) != set(existing):
            raise PhotoRuleError("這個商品的照片剛才被別人改過了,請關掉表單重新開一次再改")

    plan, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise PhotoRuleError("照片清單格式不對")
        caption = str(item.get("caption") or "").strip()[:40]
        if item.get("photo") is not None:
            # 只收真正的整數(true 在 Python 裡也算 int,會對到編號 1 的照片)
            photo = existing.get(item["photo"]) if type(item["photo"]) is int else None
            if photo is None or ("p", photo.id) in seen:
                raise PhotoRuleError("照片清單裡有不屬於這個商品的照片")
            seen.add(("p", photo.id))
            plan.append((photo, None, caption, item.get("is_primary") is True))
        else:
            upload = uploads.get(str(item.get("upload") or ""))
            if upload is None or ("u", upload.id) in seen:
                raise PhotoRuleError("照片清單裡有這次作業沒有的照片")
            if upload.status != PhotoUpload.Status.READY or upload.consumed:
                raise PhotoRuleError("有照片還沒傳好,不能儲存")
            seen.add(("u", upload.id))
            plan.append((None, upload, caption, item.get("is_primary") is True))

    # 主圖剛好一張:有指定用指定的那一張(多指定算第一個),沒指定就是第一張
    primary_at = next((i for i, p in enumerate(plan) if p[3]), 0)

    removed = [p for pid, p in existing.items() if ("p", pid) not in seen]
    gone_files = [n for p in removed for n in (p.image.name, p.thumb.name)]
    ProductPhoto.objects.filter(pk__in=[p.pk for p in removed]).delete()
    # 先全部拿掉主圖再設新的(一個商品最多一張主圖是資料庫擋的)
    ProductPhoto.objects.filter(product=product, is_primary=True).update(is_primary=False)
    for index, (photo, upload, caption, _flag) in enumerate(plan):
        is_primary = index == primary_at
        if photo is not None:
            photo.caption, photo.sort, photo.is_primary = caption, index, is_primary
            photo.save(update_fields=["caption", "sort", "is_primary", "updated_at"])
            continue
        created = ProductPhoto(
            tenant=product.tenant, product=product, caption=caption, sort=index,
            is_primary=is_primary, width=upload.width, height=upload.height,
        )
        # 檔案直接交給正式照片(不複製);暫存那一筆標成「已掛到商品」,清暫存時不會刪到它
        created.image.name, created.thumb.name = upload.image.name, upload.thumb.name
        created.save()
        upload.consumed = True
        upload.save(update_fields=["consumed", "updated_at"])

    draft.state = PhotoDraft.State.COMMITTED
    draft.product = product
    draft.closed_at = timezone.now()
    draft.pair_hash, draft.device_hash, draft.frozen = "", "", False
    draft.save()
    # 這次傳上來、最後沒放進清單的暫存照片:不留
    _drop_loose_files(draft)
    transaction.on_commit(lambda: _delete_files(gone_files))


# ── 清暫存 ───────────────────────────────────────────────────
def cleanup(now=None) -> int:
    """清掉結束一陣子、或放太久沒存的作業,連同還沒掛到商品的暫存檔。回清了幾份作業。"""
    now = now or timezone.now()
    stale = PhotoDraft.objects.filter(
        state__in=[PhotoDraft.State.COMMITTED, PhotoDraft.State.CANCELLED],
        closed_at__lt=now - CLOSED_KEEP,
    ) | PhotoDraft.objects.filter(
        state=PhotoDraft.State.OPEN, updated_at__lt=now - DRAFT_TTL,
    )
    count = 0
    for draft in stale.distinct():
        with transaction.atomic():
            locked = PhotoDraft.objects.select_for_update().filter(pk=draft.pk).first()
            if locked is None:
                continue
            # 鎖到之後再看一次:這段時間又有人動過(還在用)就跳過
            still_stale = (
                locked.state != PhotoDraft.State.OPEN
                and locked.closed_at and locked.closed_at < now - CLOSED_KEEP
            ) or (
                locked.state == PhotoDraft.State.OPEN
                and locked.updated_at < now - DRAFT_TTL
            )
            if not still_stale:
                continue
            names = [
                n for u in locked.uploads.filter(consumed=False)
                for n in (u.image.name, u.thumb.name)
            ]
            locked.delete()
            transaction.on_commit(lambda names=names: _delete_files(names))
            count += 1
    return count
