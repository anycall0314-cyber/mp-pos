"""對外的端點:不在這套 POS 上的系統照買賣串接規格 v2 來跟這裡的賣家買(`docs/api/買賣串接規格_v2_草稿.md`)。

網址 `/api/trade/v2/…`(全平台同一個),標頭 `Authorization: Bearer <金鑰>`。**不用 POS 的登入**:認的是賣家發的那把金鑰(`keys.py`),
一把金鑰 = 一家賣家的一個同行;之後做的事跟平台內的買家一模一樣 —— 都是 `api.handle`,看得到什麼只有那裡一份。
這幾支不經過 POS 的登入驗證,所以賣家的「資料還原中」要自己擋(回 503)。回應一律是 `{ok, …}` / `{ok: false, error, code}`,不快取。
"""
import logging

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.backup.jobs import in_maintenance

from . import api, keys
from .models import TradePartner


logger = logging.getLogger(__name__)


def _reply(status: int, body: dict) -> Response:
    response = Response(body, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _fail(status: int, message: str, code: str) -> Response:
    return _reply(status, {"ok": False, "error": message, "code": code})


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def entry(request, rest: str = ""):
    header = request.headers.get("Authorization", "")
    key = keys.find(header[7:].strip()) if header.startswith("Bearer ") else None
    if key is None:
        return _fail(401, "金鑰不對或已經作廢", "unauthorized")
    partner, seller = key.partner, key.partner.tenant
    if partner.kind != TradePartner.Kind.EXTERNAL or not seller.is_active:
        return _fail(401, "金鑰不對或已經作廢", "unauthorized")
    if not keys.hit(key):
        return _fail(429, "太頻繁,請過一分鐘再試", "too_many")
    if in_maintenance(seller):
        return _fail(503, "賣家的資料維護中,請稍後再試", "maintenance")
    body = None
    if request.method == "POST":
        try:
            body = request.data
        except (ParseError, UnsupportedMediaType):
            return _fail(400, "內容要是 JSON", "bad_json")
        if not isinstance(body, dict):
            return _fail(400, "內容要是 JSON 物件", "bad_json")
    query = request.META.get("QUERY_STRING", "")
    path = "/" + rest.strip("/") + (f"?{query}" if query else "")
    try:
        status, data = api.handle(seller, partner, request.method, path, body, store=partner.name)
    except Exception:          # noqa: BLE001 —— 沒料到的錯:對方拿到的還是講好的樣子(不是一頁錯誤訊息),這邊記下來查
        logger.exception("對外端點出錯 %s /%s", request.method, rest.strip("/"))      # 不記查詢字串與內容
        return _fail(500, "系統出錯了,請稍後再試", "error")
    return _reply(status, data)
