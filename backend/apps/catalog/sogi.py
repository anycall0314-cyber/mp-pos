"""讀手機王(SOGI,www.sogi.com.tw)的公開頁面:清單(手機 / 平板 / 穿戴,一頁列完)與商品頁。型號庫自動更新(`device_watch.py`)用。

- 照對方的 robots:`/search/…` 與 `/products/…` 可以讀;一次一頁、兩頁之間隔 `PAUSE` 秒。
- **被擋(401 / 403 / 429)就整個停**,這一次不再讀任何一頁(不換網址、不換身分繞過去);其他錯誤只算那一頁沒讀到。
- 讀法只認幾個固定的記號(商品格子的連結、「上市日期」、「版本空機」、規格表的格子),版面改了讀不到就是讀不到 ——
  數量突然少很多由 `device_watch` 判斷成這一次讀失敗,不會因此把型號庫當成少了東西。
"""
from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request

BASE = "https://www.sogi.com.tw"
LISTS = {"cellphone": "/search/cellphone", "tablet": "/search/tablet", "wearable": "/search/wearable"}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
PAUSE = 2.5
TIMEOUT = 20
MAX_BYTES = 5_000_000

_ITEM = re.compile(r'event-element-target="([^"]{1,200})"\s+href="(/products/[A-Za-z0-9_.\-]{1,120}/(\d{1,9}))"')
_VARIANT = re.compile(r'event-page-element="版本空機"[^>]*>\s*([^<]{1,60})</a>')
# 還沒上市的版本格子:沒有連結,版本寫在 <span>,下一格寫「未上市」
_UNRELEASED_VARIANT = re.compile(r'btn-price[^"]*"[^>]*>\s*<div[^>]*>\s*<span>\s*([^<]{1,60})</span>(?=[\s\S]{0,200}?未上市)')
_MONEY = re.compile(r"\$\s*([\d,]{1,9})")


class Blocked(Exception):
    """對方明講不讓讀(401 / 403 / 429):這一次整個停。"""


class Fetcher:
    """一次檢查用一個:記上一頁的時間,兩頁之間至少隔 PAUSE 秒;被擋之後每一頁都直接丟 Blocked。"""

    def __init__(self, opener=None, sleep=time.sleep, clock=time.monotonic):
        self._open = opener or self._urlopen
        self._sleep, self._clock = sleep, clock
        self._last = None
        self.blocked = ""
        self.pages = 0

    @staticmethod
    def _urlopen(url):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return res.read(MAX_BYTES + 1).decode("utf-8", errors="replace")

    def get(self, path: str) -> str:
        """讀一頁,回網頁內容。被擋丟 Blocked;其他讀不到丟 OSError(只算這一頁)。"""
        if self.blocked:
            raise Blocked(self.blocked)
        if self._last is not None:
            wait = PAUSE - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self.pages += 1
        try:
            body = self._open(BASE + path)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 429):
                self.blocked = f"手機王不讓讀(HTTP {exc.code})"
                raise Blocked(self.blocked) from None
            raise OSError(f"HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise OSError(str(getattr(exc, "reason", exc))[:120]) from None
        if len(body) > MAX_BYTES:
            raise OSError("網頁太大")
        return body


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def parse_list(page: str) -> list[dict]:
    """清單頁 → [{"id", "name", "path"}](同一個商品出現兩次只算一次,照頁面上的順序)。"""
    out, seen = [], set()
    for m in _ITEM.finditer(page):
        name, path, pid = html.unescape(m.group(1)).strip(), m.group(2), m.group(3)
        if pid in seen or not name:
            continue
        seen.add(pid)
        out.append({"id": pid, "name": name, "path": path})
    return out


def _storage(label: str) -> str:
    """版本的寫法 → 儲存容量:「(8GB/256GB)」→ 256GB、「Wi-Fi 128GB」→ 128GB、「1 TB」→ 1TB。認不出來回空字串。"""
    sizes = re.findall(r"(\d{1,4})\s*(GB|TB)", label, re.I)
    if not sizes:
        return ""
    n, unit = sizes[-1]
    return f"{int(n)}{unit.upper()}"


def product_path(pid: str | int) -> str:
    """只知道編號時讀商品頁的路徑(對方會轉到正式的網址)。"""
    return f"/products/x/{int(pid)}"


def parse_product(page: str) -> dict:
    """商品頁 → {"name", "launch"(YYYY-MM 或空的), "unreleased", "variants": [{"label", "storage", "msrp"}], "colors", "class", "rom",
    "screen"(吋,沒寫是 None), "volte", "path"(正式的網址,沒寫是空的)}。

    還沒上市的頁:「上市日期：2026/10(未上市)」或「上市日期：------(未上市)」(沒公布日期);版本格子沒有連結、價錢那一格寫「未上市」,原廠售價照寫。"""
    name = _text((re.search(r"<h1[^>]*>([\s\S]{0,400}?)</h1>", page) or [None, ""])[1])
    m = re.search(r"上市日期：\s*(\d{4})\s*/\s*(\d{1,2})", page)
    launch = f"{m.group(1)}-{int(m.group(2)):02d}" if m and 1 <= int(m.group(2)) <= 12 else ""
    unreleased = bool(re.search(r"上市日期：[^<]{0,30}\(未上市\)", page))
    variants = []
    hits = list(_VARIANT.finditer(page)) or list(_UNRELEASED_VARIANT.finditer(page) if unreleased else [])
    for i, v in enumerate(hits):
        block = page[v.end(): hits[i + 1].start() if i + 1 < len(hits) else v.end() + 3000]
        label = _text(v.group(1)).strip("() ")
        msrp_at = block.find("原廠售價")
        msrp = None
        if msrp_at >= 0:
            mm = _MONEY.search(block[msrp_at: msrp_at + 200])
            msrp = int(mm.group(1).replace(",", "")) if mm else None
        variants.append({"label": label, "storage": _storage(label), "msrp": msrp,
                         "bundle": bool(re.search(r"套裝|套組|組合|禮盒", label))})
    specs = {}
    for s in re.finditer(r'<th[^>]*>([^<]{1,40})</th>\s*<td[^>]*>([\s\S]{0,2000}?)</td>', page):
        specs.setdefault(_text(s.group(1)), _text(s.group(2)))
    colors = [c.strip() for c in re.split(r"[,、，]", specs.get("機身顏色", "")) if c.strip()]
    inch = re.search(r"(\d{1,2}(?:\.\d{1,2})?)\s*inch", specs.get("主螢幕尺寸", ""), re.I)
    canon = re.search(r'<link rel="canonical" href="https://www\.sogi\.com\.tw(/products/[A-Za-z0-9_.\-]{1,120}/\d{1,9})"', page)
    return {"name": name, "launch": launch, "unreleased": unreleased, "variants": variants, "colors": list(dict.fromkeys(colors)),
            "class": specs.get("裝置分類", ""), "rom": specs.get("ROM儲存空間", ""),
            "screen": float(inch.group(1)) if inch else None, "volte": specs.get("VoLTE", "").strip().casefold() == "yes",
            "path": canon.group(1) if canon else ""}
