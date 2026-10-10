"""「標準格式」的廠商下單 API —— 就是膜總裁 B2B 對外下單 API v1 那一套(格式見那個專案的 docs/api-v1.md;以它實際回的為準)。
照這套格式的廠商都用這一支,不用為每一家另外寫:差別只有對方的網址與名稱(`Client`),從平台的廠商名單來。

這裡只管「送什麼、回了什麼、算不算明確的答覆」,不碰資料庫。所有對外的請求都經過 `_call`(測試換掉的就是它)。
金鑰只放在 Authorization 標頭,不放進網址、不進例外訊息;**一把金鑰只會送到它所屬的那一家的網址**。
"""
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

PAYMENT_METHODS = ("月結", "貨到付款", "匯款")
DELIVERY_METHODS = ("宅配", "自取")
INVOICE_TYPES = ("個人", "公司")


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


def looks_like_key(raw, prefix: str = "") -> bool:
    """像不像一把金鑰。`prefix` = 這家廠商的金鑰固定的開頭(有設才檢查):擋掉貼錯的東西(別的密碼)被送去問廠商。"""
    return isinstance(raw, str) and raw.startswith(prefix) and 20 <= len(raw) <= 200 and raw.isascii() \
        and not any(c.isspace() for c in raw)


def _call(method: str, path: str, key: str, body: dict | None = None, timeout: float = 15, *,
          base: str, name: str = "廠商") -> Reply:
    request = urllib.request.Request(
        base.rstrip("/") + path,
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
        raise Unreachable(f"連不到{name}({type(exc).__name__})") from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Unreachable(f"{name}回的內容看不懂(HTTP {status})") from None
    if not isinstance(data, dict):
        raise Unreachable(f"{name}回的內容看不懂(HTTP {status})")
    return Reply(status, data)


def _sandbox(data: dict):
    """這個回應說這把金鑰是不是沙盒。只認明講的 true / false;沒講或亂填 = 不知道(None)。"""
    flag = data.get("sandbox")
    return flag if isinstance(flag, bool) else None


@dataclass
class Listing:
    products: list
    sandbox: object = None          # True / False / None(廠商沒有講)


@dataclass
class Detail:
    order: dict                     # 這張單現在的樣子(含 items:廠商事後改單、改價之後就是改過的)
    sandbox: object = None


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


@dataclass(frozen=True)
class Client:
    """跟某一家廠商講話:對方的網址 + 訊息裡怎麼稱呼它。"""
    base: str
    name: str

    def _send(self, method: str, path: str, key: str, body: dict | None = None, timeout: float = 15) -> Reply:
        return _call(method, path, key, body, timeout, base=self.base, name=self.name)

    def _reason(self, reply: Reply) -> str:
        text = reply.data.get("error")
        return text if isinstance(text, str) and text else f"{self.name}回 HTTP {reply.status}"

    def _read(self, path: str, key: str) -> dict:
        reply = self._send("GET", path, key)
        if reply.status >= 500:
            raise Unreachable(f"{self.name}那邊出錯(HTTP {reply.status})")
        if reply.status != 200 or reply.data.get("ok") is not True:
            raise Refused(reply.status, self._reason(reply))
        return reply.data

    def products(self, key: str) -> Listing:
        data = self._read("/products", key)
        rows = data.get("products")
        return Listing(rows if isinstance(rows, list) else [], _sandbox(data))

    def orders(self, key: str, limit: int = 100) -> list:
        rows = self._read(f"/orders?limit={int(limit)}", key).get("orders")
        return rows if isinstance(rows, list) else []

    def detail(self, key: str, order_no: str) -> Detail:
        data = self._read("/orders/" + urllib.parse.quote(order_no, safe=""), key)
        row = data.get("order")
        return Detail(row if isinstance(row, dict) else {}, _sandbox(data))

    def order(self, key: str, order_no: str) -> dict:
        return self.detail(key, order_no).order

    def place(self, key: str, payload: dict):
        """下單。回 `Placed` / `Rejected`;沒有明確答覆丟 `Unreachable`(= 不知道有沒有成立)。"""
        reply = self._send("POST", "/orders", key, payload, timeout=30)
        order_no = reply.data.get("order_no")
        has_no = isinstance(order_no, str) and order_no != ""
        if reply.status == 200 and reply.data.get("ok") is True and has_no:
            return Placed(order_no, reply.data.get("total_amount"), reply.data.get("shipping_fee"),
                          sandbox=_sandbox(reply.data))
        if reply.status == 409 and has_no:
            # 這把鑰匙送過、而且成立了:不是錯誤
            return Placed(order_no, replay=True, sandbox=_sandbox(reply.data))
        if 400 <= reply.status < 500 and reply.status not in (408, 409):
            return Rejected(reply.status, self._reason(reply))
        raise Unreachable(f"{self.name}沒有給明確的答覆(HTTP {reply.status})")
