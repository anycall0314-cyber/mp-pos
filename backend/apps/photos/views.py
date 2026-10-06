"""商品照片的 API。

電腦這邊(要登入):照片作業 `/photo-drafts/…`、看一個商品的照片 `/product-photos/`。
手機這邊(**不用登入**,只認 QR Code 的憑證 + 那支手機自己的識別):`/photo-pair/…`。
照片檔本身:`/photo-file/<簽章>/`(給 <img> 用,網址帶簽章)。

**除了照片檔,這裡每一個回應都不准瀏覽器留著(`never_cache`)。** 手機問狀態的網址每一次配對都一樣
(憑證放在標頭,不在網址裡);瀏覽器對「410 已經不在了」這種回應預設會永久記住,
不擋的話那支手機看過一次「已結束」,之後每一次新的配對一問狀態都拿到舊的「已結束」。
"""
import logging

from django.http import FileResponse, Http404
from django.views.decorators.cache import never_cache
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
)
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.backup.models import TenantMaintenance
from apps.catalog.models import Product

from . import services
from .models import PhotoDraft, PhotoUpload, ProductPhoto
from .services import PhotoRuleError

logger = logging.getLogger(__name__)


def _refuse(exc: PhotoRuleError) -> Response:
    code = {
        "gone": status.HTTP_410_GONE,
        "expired": status.HTTP_410_GONE,
        # 只是「這一張」取消了(整次配對還在):手機那邊要分得出來,不能當成整個結束
        "cancelled": status.HTTP_410_GONE,
        "taken": status.HTTP_409_CONFLICT,
        "frozen": status.HTTP_409_CONFLICT,
    }.get(exc.code, status.HTTP_400_BAD_REQUEST)
    return Response({"detail": str(exc), "code": exc.code}, status=code)


def _upload_dict(u: PhotoUpload) -> dict:
    out = {
        "uid": u.uid, "status": u.status, "source": u.source, "error": u.error,
        "width": u.width, "height": u.height,
    }
    if u.status == PhotoUpload.Status.READY:
        out.update(services.photo_urls("u", u.pk))
    return out


def _photo_dict(p: ProductPhoto) -> dict:
    return {
        "id": p.pk, "caption": p.caption, "is_primary": p.is_primary, "sort": p.sort,
        "width": p.width, "height": p.height, **services.photo_urls("p", p.pk),
    }


def _draft_dict(draft: PhotoDraft) -> dict:
    uploads = list(draft.uploads.all())
    return {
        "uid": str(draft.uid),
        "state": draft.state,
        "frozen": draft.frozen,
        "label": draft.label,
        "spec": draft.spec,
        "product": draft.product_id,
        "max_photos": services.MAX_PHOTOS,
        "pair": {
            "status": services.pair_status(draft),
            "expires_at": draft.pair_expires_at.isoformat() if draft.pair_expires_at else None,
            "received": sum(
                1 for u in uploads
                if u.source == PhotoUpload.Source.PHONE and u.status == PhotoUpload.Status.READY
            ),
        },
        "uploads": [_upload_dict(u) for u in uploads],
    }


# ── 電腦:照片作業 ────────────────────────────────────────────
@never_cache
@api_view(["POST"])
def drafts(request):
    """開一份照片作業。body: {product?: 商品編號, label, spec}"""
    product = None
    pid = request.data.get("product")
    if pid not in (None, ""):
        product = Product.objects.for_tenant(request.tenant).filter(pk=pid).first() \
            if str(pid).isdigit() else None
        if product is None:
            return Response({"detail": "找不到這個商品"}, status=status.HTTP_400_BAD_REQUEST)
    draft = services.new_draft(
        request.tenant, request.user, product,
        str(request.data.get("label") or ""), str(request.data.get("spec") or ""),
    )
    # 順手清掉放太久沒存、或結束一陣子的舊作業與暫存檔。不另外排程:
    # 有人開新的照片作業時掃一次就夠了(沒人用照片,就沒有東西要清)。清不掉不影響這一次
    try:
        services.cleanup()
    except Exception:
        logger.exception("清理舊的照片作業失敗")
    return Response(_draft_dict(draft), status=status.HTTP_201_CREATED)


@never_cache
@api_view(["GET", "PATCH"])
def draft_detail(request, uid):
    try:
        draft = services.get_draft(request.tenant, request.user, uid)
    except PhotoRuleError as exc:
        return _refuse(exc)
    if request.method == "PATCH":
        # 品名改了:手機那邊顯示的名稱跟著更新(照片還是同一份作業的,不重新配對)
        PhotoDraft.objects.filter(pk=draft.pk, state=PhotoDraft.State.OPEN).update(
            label=str(request.data.get("label") or "")[:160],
            spec=str(request.data.get("spec") or "")[:160],
        )
        draft.refresh_from_db()
    return Response(_draft_dict(draft))


@never_cache
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def draft_upload(request, uid):
    """電腦選的照片。欄位:uid(這一張的識別)、file。"""
    try:
        draft = services.get_draft(request.tenant, request.user, uid)
        row = services.add_upload(
            draft, str(request.data.get("uid") or ""), request.FILES.get("file"),
            PhotoUpload.Source.DESKTOP,
        ) if request.FILES.get("file") else None
    except PhotoRuleError as exc:
        return _refuse(exc)
    if row is None:
        return Response({"detail": "請附上照片(欄位名 file)"}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_upload_dict(row), status=status.HTTP_201_CREATED)


@never_cache
@api_view(["POST"])
def draft_action(request, uid, action):
    try:
        draft = services.get_draft(request.tenant, request.user, uid)
        if action == "pair":
            token = services.start_pair(draft)
            draft.refresh_from_db()
            return Response({**_draft_dict(draft), "pair_token": token})
        if action == "unpair":
            services.end_pair(draft)
        elif action == "freeze":
            services.set_frozen(draft, True)
        elif action == "unfreeze":
            services.set_frozen(draft, False)
        elif action == "cancel":
            services.cancel_draft(draft)
        elif action == "cancel-upload":
            services.cancel_upload(draft, str(request.data.get("uid") or ""))
        else:
            raise Http404
    except PhotoRuleError as exc:
        return _refuse(exc)
    draft.refresh_from_db()
    return Response(_draft_dict(draft))


@never_cache
@api_view(["GET"])
def product_photos(request):
    """一個商品的照片(主圖在前)。?product=商品編號"""
    pid = request.query_params.get("product", "")
    if not pid.isdigit():
        return Response({"detail": "需提供 product"}, status=status.HTTP_400_BAD_REQUEST)
    product = Product.objects.for_tenant(request.tenant).filter(pk=int(pid)).first()
    if product is None:
        return Response({"detail": "找不到這個商品"}, status=status.HTTP_404_NOT_FOUND)
    return Response([_photo_dict(p) for p in product.photos.all()])


# ── 照片檔 ───────────────────────────────────────────────────
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def photo_file(request, token):
    parsed = services.read_file_token(token)
    if parsed is None:
        raise Http404
    kind, pk, variant = parsed
    obj = (ProductPhoto if kind == "p" else PhotoUpload).objects.filter(pk=pk).first()
    field = None if obj is None else (obj.image if variant == "f" else obj.thumb)
    if not field:
        raise Http404
    try:
        handle = field.open("rb")
    except Exception:
        raise Http404
    response = FileResponse(handle, content_type="image/jpeg")
    # 網址本身就是憑證:只讓這個人的瀏覽器記著,不給中間的快取留
    response["Cache-Control"] = "private, max-age=86400"
    return response


# ── 手機:只認 QR Code 的憑證 ─────────────────────────────────
def _phone(request, claim=False, active=False):
    """驗手機的憑證。回 (作業, 這一次配對):後面每一個動作都帶著「這一次配對」,鎖住作業之後再核對一次。"""
    draft = services.phone_draft(
        request.headers.get("X-Pair-Token", ""), request.headers.get("X-Pair-Device", ""),
        claim=claim, active=active,
    )
    # 公司資料還原中:手機這條路也要擋(它不經過登入那一層的維護鎖)
    if TenantMaintenance.objects.filter(tenant_id=draft.tenant_id, active=True).exists():
        raise PhotoRuleError("公司資料還原中,暫時不能上傳,請稍後再試", "frozen")
    return draft, services.pair_of(draft)


def _phone_dict(draft: PhotoDraft) -> dict:
    """手機看得到的只有:這些照片要放到哪一筆、這次自己傳了哪幾張。沒有金額、沒有別的商品。"""
    product = draft.product
    return {
        "label": draft.label,
        "spec": draft.spec,
        "sku": product.sku if product else "",
        "frozen": draft.frozen,
        "uploads": [
            {
                "uid": u.uid, "status": u.status, "error": u.error,
                **({"thumb_url": services.photo_urls("u", u.pk)["thumb_url"]}
                   if u.status == PhotoUpload.Status.READY else {}),
            }
            for u in draft.uploads.filter(source=PhotoUpload.Source.PHONE)
            .exclude(status=PhotoUpload.Status.CANCELLED)
        ],
    }


@never_cache
@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def phone(request, action):
    """claim 掃碼連上 / state 看狀態 / announce 這一張要傳了 / upload 傳 / cancel 取消一張 / finish 拍完了"""
    try:
        if action == "claim" and request.method == "POST":
            draft, pair = _phone(request, claim=True)
        elif action == "state" and request.method == "GET":
            draft, pair = _phone(request)
        elif action == "announce" and request.method == "POST":
            draft, pair = _phone(request, active=True)
            services.announce(
                draft, str(request.data.get("uid") or ""), PhotoUpload.Source.PHONE, pair
            )
        elif action == "upload" and request.method == "POST":
            draft, pair = _phone(request, active=True)
            if not request.FILES.get("file"):
                return Response({"detail": "沒有收到照片"}, status=status.HTTP_400_BAD_REQUEST)
            services.add_upload(
                draft, str(request.data.get("uid") or ""), request.FILES["file"],
                PhotoUpload.Source.PHONE, pair,
            )
        elif action == "cancel" and request.method == "POST":
            draft, pair = _phone(request, active=True)
            services.cancel_upload(
                draft, str(request.data.get("uid") or ""), by=PhotoUpload.Source.PHONE, pair=pair
            )
        elif action == "finish" and request.method == "POST":
            draft, pair = _phone(request)
            services.end_pair(draft, pair)
            return Response({"detail": "已結束"})
        else:
            raise Http404
        draft.refresh_from_db()
        body = _phone_dict(draft)
        # 做事的這段時間電腦按了「重新產生」、換別支手機連上了:這份作業的內容不回給舊的那一支
        if not services.still_paired(draft.pk, pair):
            raise PhotoRuleError("要再拍,請在電腦按「重新產生」再掃一次", "gone")
    except PhotoRuleError as exc:
        return _refuse(exc)
    return Response(body)
