"""小幫手(在廠商下單網站的頁面裡跑的那一支 JS)跟 POS 講話的端點。規則在 `handoff.py`。

**不用登入**:小幫手跑在廠商的網站上,拿不到 POS 的登入;認的是網址後面那一組一次性的代碼(只對得到一張叫貨單、15 分鐘內要開始用)。
**只對廠商網站的來源開跨來源**(`Access-Control-Allow-Origin`),別的網站的頁面叫不動這幾支。
內容用 `text/plain` 送 JSON:這樣是「簡單請求」,瀏覽器不會先發一個預檢。
"""
import json

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.exceptions import ParseError
from rest_framework.parsers import BaseParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import handoff, kcimos
from .services import VendorError

STEPS = ("claim", "submitting", "done", "failed", "release")


class PlainJSON(BaseParser):
    """`text/plain` 的內容當成 JSON 讀(小幫手用這種寫法避開預檢)。"""

    media_type = "text/plain"

    def parse(self, stream, media_type=None, parser_context=None):
        raw = stream.read()
        if not raw.strip():
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ParseError("內容不是 JSON") from None


def _reply(request, body, code=status.HTTP_200_OK):
    response = Response(body, status=code)
    if request.headers.get("Origin") == kcimos.SITE["origin"]:
        response["Access-Control-Allow-Origin"] = kcimos.SITE["origin"]
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        response["Access-Control-Max-Age"] = "600"
    response["Vary"] = "Origin"
    response["Cache-Control"] = "no-store"
    return response


def _bad(request, exc):
    return _reply(request, {"detail": str(exc)}, status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "OPTIONS"])
@authentication_classes([])
@permission_classes([AllowAny])
def site_handoff(request, code: str):
    """這張單要送什麼(品項、數量、收件人、備註、這家門市綁的帳號)。"""
    if request.method == "OPTIONS":
        return _reply(request, {})
    try:
        return _reply(request, handoff.payload(code))
    except VendorError as exc:
        return _bad(request, exc)


@api_view(["POST", "OPTIONS"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([JSONParser, PlainJSON])
def site_handoff_step(request, code: str, step: str):
    """小幫手回報進度:`claim` 開始動購物車 / `submitting` 要送了 / `done` 成立了 / `failed` 廠商不收 / `release` 不送了。"""
    if request.method == "OPTIONS":
        return _reply(request, {})
    if step not in STEPS:
        return _reply(request, {"detail": "沒有這一步"}, status.HTTP_404_NOT_FOUND)
    data = request.data if isinstance(request.data, dict) else {}
    try:
        if step == "claim":
            body = handoff.claim(code)
        elif step == "submitting":
            body = handoff.submitting(code, data.get("account"), data.get("bind"))
        elif step == "done":
            body = handoff.done(code, data.get("order_no"), data.get("total"), data.get("shipping"), data.get("note"))
        elif step == "failed":
            body = handoff.failed(code, data.get("message"))
        else:
            body = handoff.release(code, data.get("reason"))
    except VendorError as exc:
        return _bad(request, exc)
    return _reply(request, body)
