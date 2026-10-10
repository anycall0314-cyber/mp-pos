"""跟膜總裁 B2B 對外下單 API v1 講話的地方(格式見那個專案的 docs/api-v1.md;以它實際回的為準)。

這裡只管「送什麼、回了什麼、算不算明確的答覆」,不碰資料庫。所有對外的請求都經過 `_call`(測試換掉的就是它)。
金鑰只放在 Authorization 標頭,不放進網址、不進例外訊息。
"""
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings

PAYMENT_METHODS = ("月結", "貨到付款", "匯款")
DELIVERY_METHODS = ("宅配", "自取")
INVOICE_TYPES = ("個人", "公司")
KEY_PREFIX = "mk_live_"         # 沙盒金鑰也是這個開頭;是不是沙盒要看膜總裁後台的設定


class Unreachable(Exception):
    """沒有拿到明確的答覆:連不上、逾時、對方出錯(5xx)、回來的不是看得懂的內容。"""


class Refused(Exception):
    """對方明確說不行(讀資料的那幾支用)。`reason` 是給人看的原因。"""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


@dataclass
class Reply:
    status: int
    data: dict


def looks_like_key(raw) -> bool:
    return isinstance(raw, str) and raw.startswith(KEY_PREFIX) and 20 <= len(raw) <= 200 and raw.isascii() \
        and not any(c.isspace() for c in raw)


def _call(method: str, path: str, key: str, body: dict | None = None, timeout: float = 15) -> Reply:
    request = urllib.request.Request(
        settings.MOCEO_API_BASE.rstrip("/") + path,
        data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MP-POS vendor-orders",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise Unreachable(f"連不到膜總裁({type(exc).__name__})") from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Unreachable(f"膜總裁回的內容看不懂(HTTP {status})") from None
    if not isinstance(data, dict):
        raise Unreachable(f"膜總裁回的內容看不懂(HTTP {status})")
    return Reply(status, data)


def _reason(reply: Reply) -> str:
    text = reply.data.get("error")
    return text if isinstance(text, str) and text else f"膜總裁回 HTTP {reply.status}"


def _read(path: str, key: str) -> dict:
    reply = _call("GET", path, key)
    if reply.status >= 500:
        raise Unreachable(f"膜總裁那邊出錯(HTTP {reply.status})")
    if reply.status != 200 or reply.data.get("ok") is not True:
        raise Refused(reply.status, _reason(reply))
    return reply.data


def _sandbox(data: dict):
    """這個回應說這把金鑰是不是沙盒。只認明講的 true / false;沒講或亂填 = 不知道(None)。"""
    flag = data.get("sandbox")
    return flag if isinstance(flag, bool) else None


@dataclass
class Listing:
    products: list
    sandbox: object = None          # True / False / None(廠商沒有講)


def products(key: str) -> Listing:
    data = _read("/products", key)
    rows = data.get("products")
    return Listing(rows if isinstance(rows, list) else [], _sandbox(data))


def orders(key: str, limit: int = 100) -> list:
    rows = _read(f"/orders?limit={int(limit)}", key).get("orders")
    return rows if isinstance(rows, list) else []


def order(key: str, order_no: str) -> dict:
    row = _read("/orders/" + urllib.parse.quote(order_no, safe=""), key).get("order")
    return row if isinstance(row, dict) else {}


@dataclass
class Placed:
    order_no: str
    total_amount: object = None       # 重送拿到 409 時廠商只回單號,這兩個是 None
    shipping_fee: object = None
    replay: bool = False
    sandbox: object = None            # 這張是不是測試單(沙盒金鑰下的);None = 廠商沒有講


@dataclass
class Rejected:
    """明確沒有成立(內容被擋、金鑰無效…)。這把鑰匙沒有被用掉。"""
    status: int
    reason: str


def place(key: str, payload: dict):
    """下單。回 `Placed` / `Rejected`;沒有明確答覆丟 `Unreachable`(= 不知道有沒有成立)。"""
    reply = _call("POST", "/orders", key, payload, timeout=30)
    order_no = reply.data.get("order_no")
    has_no = isinstance(order_no, str) and order_no != ""
    if reply.status == 200 and reply.data.get("ok") is True and has_no:
        return Placed(order_no, reply.data.get("total_amount"), reply.data.get("shipping_fee"),
                      sandbox=_sandbox(reply.data))
    if reply.status == 409 and has_no:
        # 這把鑰匙送過、而且成立了:不是錯誤
        return Placed(order_no, replay=True, sandbox=_sandbox(reply.data))
    if 400 <= reply.status < 500 and reply.status not in (408, 409):
        return Rejected(reply.status, _reason(reply))
    raise Unreachable(f"膜總裁沒有給明確的答覆(HTTP {reply.status})")
