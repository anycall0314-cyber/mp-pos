"""平台型號庫每天自動新增新機(M1-D;owner 2026-10-15「添加新工具可以自動新增手機型號」、2026-10-16「對，做自動新增手機型號」)。

每天一次(`run_due`;備份背景程式每分鐘問一次,過了 `DEVICE_WATCH_AT` 才做,一天只做一次;測試站用排程跑 `watch_device_catalog`):
1. 讀手機王的三頁清單(手機 / 平板 / 穿戴,`sogi.py`)。**清單比上一次成功時少很多(不到六成)就當成這一頁讀失敗**(版面改了),那一類這次不處理。
2. 清單上的每一個商品頁:型號庫記過它的網址、或之前看過(`DeviceCandidate`)→ 跳過;**名稱跟型號庫某一支一樣**(`strong_key`:
   去掉品牌字、容量、平板 / 手錶的連線字樣(Wi-Fi / 5G / LTE)、括號、「吋」,不分大小寫與順序)→ 記成「已經有」、不讀商品頁。
3. 剩下的讀商品頁(上市年月、每個容量的原廠售價、機身顏色、分類)。同一次裡名稱一樣的併成一支(平板的 Wi-Fi 版與 5G 版、手錶的 Wi-Fi 與 LTE)。
4. 每一支怎麼辦(`decide`):
   - 品牌型號庫沒有、穿戴看不出是哪一種、**跟型號庫某一支很像**(`weak_key`:手機再去掉 5G / 4G 還一樣)→「待確認」,平台管理員在「平台管理 → 型號庫」按;
   - 資料不齊(沒寫上市、還沒上市、手機平板沒有容量、沒有顏色)→「等資料」,之後每天再讀一次那一頁,齊了照第 4 條重新判斷;
   - 其他 → **直接加進型號庫**(一次匯入 `DeviceCatalogRun`,可以 `sync_device_catalog --undo` 收回),
     **再展開到有勾「新機自動建品號」的公司**(`Tenant.auto_device_models`;規則跟 `expand_device_catalog` 一樣,只展開這幾支)。
   - 一次要自動加超過 `MAX_AUTO` 支 → 全部改成「待確認」(多半是對方版面改了、名稱讀錯)。
5. **自動加進來的新機盯 `WATCH_DAYS` 天**(紅隊第 3 條:上市時顏色常常還沒公布齊):每天再讀它的商品頁,多出來的容量 / 顏色 / 連線補進型號庫,
   有勾的公司補建那幾個品號。**只加不減**;已經有的品號、售價、庫存、序號、單據一個都不改;本來就在型號庫的那 1,468 支不盯。
6. 售價:手機王的「原廠售價」記成來源報的建議價(跟 Codex 整理的同一種);**這裡自動加的新機,展開時帶進全新 / 已拆封的售價**
   (owner 2026-10-21「新機售價自動帶原廠建議價」;`device_expand.msrp`,同一個容量列了不一樣的價就不帶;中古機 0;Codex 整理的那一批照舊不帶)。
6b. **同一個容量有兩種以上記憶體 → 拆成「8GB/256GB」「12GB/256GB」兩個容量、各自帶價**(owner 2026-10-21 選「同容量有兩種才拆」;`variant_caps`);
   只有一種記憶體的照舊只寫容量。盯新機時同一個容量換了寫法(後來才多一種記憶體)不自動補,寫一句給人處理(不然同一台會有兩個品號)。
7. **還沒上市的也先加**(owner 2026-10-20「手機只要上市，甚至上市前，皆會自動把品名與品號新增進去」):
   手機王的清單只列上市的,還沒上市的只有商品頁(編號照建立順序往上加)→ 讀完清單,**最近 `SCAN_BACK` 號裡沒看過的再讀一次(一天最多 `SCAN_GAPS` 頁),
   再從看過的最大編號往後一頁一頁讀,連續 `SCAN_MISSES` 頁不存在就停**(第一次補讀用 `scan_from`)。
   清單上沒有的頁照規格分(`guess_kind`);分不出來的「等資料」,等它上清單。
   - 寫了上市月份、是這個月或之後 → 跟上市的一樣(齊了直接加、建品號);
   - 沒寫日期(只在國外發表)、日期過了還寫未上市(延期、不在台灣賣)→「等資料」,不給人看;
     等資料等了 `STALE_DAYS` 天的改成每 `STALE_EVERY` 天讀一次。
   - 上市前就加的盯到上市月份之後 `WATCH_DAYS` 天。

被擋(401 / 403 / 429)就整個停、這一次不再讀;讀不到的那幾頁下一次再試。任何一步出錯都不動型號庫以外的東西。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import time, timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.tenants.models import Tenant

from . import device_catalog, device_expand, sogi
from .models import DeviceCandidate, DeviceModel, DeviceWatchRun

ORIGIN = "sogi-auto"
WATCH_DAYS = 60
MAX_AUTO = 10
MAX_DETAIL = 40          # 一次最多讀幾個商品頁(一頁隔 2.5 秒 ≈ 100 秒)
FOLLOW_RESERVE = 10      # 等資料的再讀不能用掉的頁數(留給盯新機補顏色容量;複審 P2)
SHRINK = 0.6             # 清單少於上一次成功的六成 = 當成讀失敗
MIN_LIST = 10
SCAN_BACK = 30           # 最近幾號裡沒看過的再讀一次(晚發布的頁)
SCAN_GAPS = 10           # 那幾號一天最多讀幾頁(從新的讀起;對方刪了很多頁也不會把每天的頁數用光)
SCAN_MISSES = 5          # 往後讀,連續幾頁不存在就停
STALE_DAYS = 90          # 沒公布日期掛這麼久的
STALE_EVERY = 7          # 改成幾天讀一次
PHONE_MAX_INCH = 8.2     # 摺疊機打開約 8 吋;最小的平板 8.3 吋
LOCK_KEY = 0x4D31_4400   # pg advisory lock:同一時間只有一個在檢查
PRICE_KIND = "source_reported_suggested_price_not_verified_original_msrp"
DEFAULT_AT = time(5, 30)
OPEN = (DeviceCandidate.Status.WAITING, DeviceCandidate.Status.REVIEW)
SEEN = (DeviceCandidate.Status.KNOWN, DeviceCandidate.Status.ADDED, DeviceCandidate.Status.LINKED)

# 手機王的寫法 → 型號庫的品牌(其餘照型號庫現有的品牌,不分大小寫)
BRAND_ALIASES = {"小米": "Xiaomi", "紅米": "Xiaomi", "榮耀": "HONOR", "華為": "HUAWEI", "索尼": "Sony"}
WEARABLE = {"智慧手錶": DeviceModel.Category.WATCH, "智慧手環": DeviceModel.Category.BAND,
            "藍牙耳機": DeviceModel.Category.HEADPHONES}
CONN = {"wifi": "WiFi", "wi-fi": "WiFi", "5g": "5G", "lte": "LTE", "4g": "LTE", "(lte)": "LTE"}
# 展開時分顏色的(沒顏色就等資料);耳機、手環 2026-10-16 起也展開(只建全新、按數量)
EXPANDED = (DeviceModel.Category.PHONE, DeviceModel.Category.TABLET, DeviceModel.Category.WATCH,
            DeviceModel.Category.BAND, DeviceModel.Category.HEADPHONES)


class DecideError(Exception):
    """平台管理員按的不能做(訊息給人看)。"""


def watch_time() -> time | None:
    """`DEVICE_WATCH_AT`(HH:MM,台灣時間);設成空的 = 不自動做。寫錯用 05:30。"""
    raw = str(getattr(settings, "DEVICE_WATCH_AT", "05:30") or "").strip()
    if not raw:
        return None
    try:
        hh, mm = raw.split(":")
        return time(int(hh), int(mm))
    except (TypeError, ValueError):
        return DEFAULT_AT


# ───────────────────────── 名稱 ─────────────────────────

def split_list_name(kind: str, list_name: str, brands: dict[str, str]) -> tuple[str, str, str, list[str]]:
    """清單上的名稱 → (型號庫的品牌(認不得是空的), 手機王寫的品牌字, 型號名稱, 連線)。
    去掉容量(`256GB`、`(8GB/256GB)`);平板與穿戴的連線字樣(Wi-Fi / 5G / LTE)拿出來另外記,手機的 5G 留在名稱裡(4G 與 5G 是不同的手機)。"""
    words = list_name.split()
    raw_brand = words[0] if words else ""
    brand = BRAND_ALIASES.get(raw_brand) or brands.get(raw_brand.casefold(), "")
    rest = " ".join(words[1:])
    rest = re.sub(r"\(\s*\d+\s*(?:GB|TB)\s*/\s*\d+\s*(?:GB|TB)\s*\)", " ", rest, flags=re.I)
    conn = []
    out = []
    for w in rest.split():
        if re.fullmatch(r"\d+\s*(?:GB|TB)", w, re.I):
            continue
        c = CONN.get(w.casefold())
        if c and kind != "cellphone":
            conn.append(c)
            continue
        out.append(w)
    if kind == "cellphone" and any(w.casefold() == "5g" for w in out):
        conn.append("5G")
    return brand, raw_brand, " ".join(out), list(dict.fromkeys(conn))


def _words(name: str, brand: str, *, phone: bool) -> list[str]:
    t = name.casefold().replace("wi-fi", "wifi").replace("+", " plus ").replace("吋", " ")
    t = re.sub(r"第\s*(\d+)\s*代", r" gen\1 ", t)
    t = re.sub(r"[()（）\[\]【】,，/]", " ", t)
    drop = {brand.casefold(), "moto"}
    if not phone:
        drop |= {"wifi", "5g", "lte", "4g"}
    return sorted(w for w in re.split(r"[\s_]+", t) if w and w not in drop)


def strong_key(name: str, brand: str, *, phone: bool = True) -> tuple:
    """名稱一樣(順序、大小寫、空白、括號、「吋」都不算;平板與穿戴的連線字樣不算)= 同一支。"""
    return tuple(_words(name, brand, phone=phone))


def weak_key(name: str, brand: str) -> tuple:
    """再去掉 5G / 4G / LTE / Wi-Fi 還一樣 = 很像(手機的 4G 版與 5G 版:可能是另一支、也可能是同一支的另一種寫法),要人看。
    螢幕尺寸(有小數點的數字)也不算:手機王寫「iPad 10.2 (2021)」、型號庫寫「iPad (2021)」。
    年份不去掉:iPad、vivo 同名不同年是不同的機器,去掉的話每一代新的 iPad 都要人按(紅隊第 1 條:待確認越少越好)。"""
    return tuple(w for w in _words(name, brand, phone=False) if not re.fullmatch(r"\d{1,2}\.\d", w))


@dataclass
class Index:
    """型號庫現在的樣子:品牌、記過的手機王編號、每一支的名稱鍵。"""
    brands: dict = field(default_factory=dict)        # casefold → 型號庫的寫法
    sogi_ids: dict = field(default_factory=dict)      # 手機王編號 → uid
    strong: dict = field(default_factory=dict)        # (品牌, 是不是手機, 鍵) → {uid}
    weak: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)         # uid → 「品牌 型號」

    @classmethod
    def build(cls):
        ix = cls()
        for d in DeviceModel.objects.all().only("uid", "brand", "name", "category", "data"):
            ix.add(d.uid, d.brand, d.name, d.category, (d.data or {}).get("aliases") or [], (d.data or {}).get("sources") or [])
        return ix

    def add(self, uid, brand, name, category, aliases=(), sources=()):
        b = brand.casefold()
        self.brands.setdefault(b, brand)
        self.names[uid] = f"{brand} {name}"
        phone = category == DeviceModel.Category.PHONE
        for text in [name, *aliases]:
            self.strong.setdefault((b, phone, strong_key(text, brand, phone=phone)), set()).add(uid)
            self.weak.setdefault((b, weak_key(text, brand)), set()).add(uid)
        for s in sources:
            m = re.search(r"sogi\.com\.tw/products/[^/]+/(\d+)", s or "")
            if m:
                self.sogi_ids.setdefault(m.group(1), uid)

    def same(self, brand, name, *, phone) -> set:
        """手機跟手機比(5G 留著)、其他跟其他比(連線字樣不算)。"""
        return set(self.strong.get((brand.casefold(), phone, strong_key(name, brand, phone=phone)), ()))

    def similar(self, brand, name) -> set:
        return set(self.weak.get((brand.casefold(), weak_key(name, brand)), ()))


# ───────────────────────── 一個商品頁 → 一支 ─────────────────────────

def _cap_order(c: str) -> int:
    """容量 → GB 數(過濾、排序用);「8GB/256GB」看後面的儲存容量。認不出來回 0。"""
    m = re.fullmatch(r"(?:\d{1,2}GB/)?(\d+)(GB|TB)", c)
    return int(m.group(1)) * (1024 if m.group(2) == "TB" else 1) if m else 0


def _cap_key(c: str) -> tuple[int, int]:
    """排序:先照儲存容量,同容量照記憶體(8GB/256GB 在 12GB/256GB 前面)。"""
    m = re.match(r"(\d{1,2})GB/", c)
    return _cap_order(c), int(m.group(1)) if m else 0


def _storage_of(c: str) -> str:
    """「8GB/256GB」→ 256GB;本來就只寫容量的照回。"""
    return c.split("/")[-1]


def _ram(label: str) -> str | None:
    """版本寫法裡的記憶體:「8GB/256GB」「12GB+512GB」→ 8GB / 12GB;沒寫回 None。"""
    m = re.search(r"(\d{1,2})\s*GB\s*[/+]\s*\d{1,4}\s*(?:GB|TB)", label, re.I)
    return f"{int(m.group(1))}GB" if m else None


def variant_caps(variants: list[dict]) -> list[str]:
    """每個版本的容量那一格(跟 `variants` 一一對應;認不出容量是空字串)。
    **同一個儲存容量有兩種以上記憶體 → 那幾個版本寫「記憶體/容量」**(owner 2026-10-21「兩個都要填，都是個別規格」,
    選「同容量有兩種才拆」:8GB/256GB 與 12GB/256GB 是兩個品號、各自帶價);只有一種記憶體的照舊只寫容量(跟店裡原本的品名一樣)。
    同一個容量有的版本沒寫記憶體 → 分不出來,照舊只寫容量。"""
    rams: dict[str, set] = {}
    for v in variants:
        if v.get("storage"):
            rams.setdefault(v["storage"], set()).add(_ram(v.get("label") or ""))
    split = {st for st, rs in rams.items() if len(rs) > 1 and None not in rs}
    return [f"{_ram(v.get('label') or '')}/{v['storage']}" if v.get("storage") in split else (v.get("storage") or "")
            for v in variants]


def _tidy_caps(caps: list[str]) -> list[str]:
    """同一個容量同時有「256GB」與「8GB/256GB」(兩頁併成一支時)→ 留分開寫的那幾個;排好。"""
    split = {_storage_of(c) for c in caps if "/" in c}
    return sorted(dict.fromkeys(c for c in caps if "/" in c or c not in split), key=_cap_key)


def _classes(page: dict) -> list[str]:
    return [c.strip() for c in re.split(r"[,、，]", page.get("class") or "") if c.strip()]


def guess_kind(page: dict) -> str:
    """清單上沒有的頁(還沒上市)是哪一類:分類寫手錶 / 手環 / 耳機 = 穿戴;螢幕小於 `PHONE_MAX_INCH` 吋而且有 VoLTE = 手機;
    名稱有 Tab / Pad / 平板、或螢幕夠大,而且沒有 VoLTE = 平板;其他分不出來(空字串)。"""
    if any(c in WEARABLE for c in _classes(page)):
        return "wearable"
    screen, volte = page.get("screen"), bool(page.get("volte"))
    tabletish = bool(re.search(r"tab\b|pad\b|平板", (page.get("name") or "").casefold()))
    if screen is None:
        return ""
    if tabletish or screen >= PHONE_MAX_INCH:
        return "" if volte else "tablet"
    return "cellphone" if volte else ""


def info_of(kind: str, item: dict, page: dict, brands: dict) -> dict:
    """清單的一項 + 讀到的商品頁 → 型號庫一支要的東西(還沒判斷齊不齊)。`kind` 空的 = 清單上沒有、分不出是哪一類。"""
    brand, raw_brand, name, conn = split_list_name(kind, item["name"], brands)
    if kind == "cellphone":
        category = DeviceModel.Category.PHONE
    elif kind == "tablet":
        category = DeviceModel.Category.TABLET
    elif not kind:
        category = ""
    else:
        found = [WEARABLE[c] for c in _classes(page) if c in WEARABLE]
        category = found[0] if len(set(found)) == 1 else ""
    url = sogi.BASE + item["path"]
    plain = [v for v in page.get("variants") or [] if not v.get("bundle")]
    labels = variant_caps(plain)
    caps = [c for c in labels if c]
    if not caps and category in (DeviceModel.Category.PHONE, DeviceModel.Category.TABLET):
        caps = [f"{int(n)}{u.upper()}" for n, u in re.findall(r"(\d{1,4})\s*(GB|TB)", page.get("rom") or "", re.I)]
    caps = sorted({c for c in caps if 0 < _cap_order(c) <= 4096}, key=_cap_key)
    if category not in (DeviceModel.Category.PHONE, DeviceModel.Category.TABLET):
        caps = []
    prices = [{"version": v["label"], "storage": cap or None, "connectivity": conn[0] if len(conn) == 1 else None,
               "size_mm": None, "amount": v["msrp"], "kind": PRICE_KIND, "url": url}
              for v, cap in zip(plain, labels) if v.get("msrp")]
    return {"kind": kind, "category": category, "brand": brand, "raw_brand": raw_brand, "name": name, "launched": page.get("launch") or "",
            "unreleased": bool(page.get("unreleased")), "capacities": caps, "colors": list(page.get("colors") or []), "connectivity": conn, "prices": prices,
            "variants": [{"label": v["label"], "storage": v.get("storage") or ""} for v in plain],   # 兩頁合併時重算容量用(不進型號庫)
            "sources": [url], "aliases": [item["name"]]}


def merge(a: dict, b: dict) -> dict:
    """同一支的兩頁(Wi-Fi 版與 5G 版)併成一份:容量 / 顏色 / 連線 / 價格 / 來源都取聯集,上市取早的。"""
    out = dict(a)
    for k in ("capacities", "colors", "connectivity", "sources", "aliases"):
        out[k] = list(dict.fromkeys([*(a.get(k) or []), *(b.get(k) or [])]))
    out["capacities"] = _tidy_caps(out["capacities"])
    seen = {(p.get("version"), p.get("storage"), p.get("amount"), p.get("url")) for p in a.get("prices") or []}
    out["prices"] = list(a.get("prices") or []) + [p for p in b.get("prices") or []
                                                   if (p.get("version"), p.get("storage"), p.get("amount"), p.get("url")) not in seen]
    va, vb = a.get("variants"), b.get("variants")
    if va is not None and vb is not None:
        # 兩頁的版本合起來重算哪幾個容量要拆(複審 P1:Wi-Fi 頁只有 8GB/256GB、5G 頁有 8GB 與 12GB → 拆開;
        # Wi-Fi 那一列價錢也要跟著寫 8GB/256GB,不然它不算數,同一個規格兩個價會被當成只有一個價)
        union = list({(v["label"], v["storage"]): v for v in [*va, *vb]}.values())
        cap_of = dict(zip(((v["label"], v["storage"]) for v in union), variant_caps(union)))
        caps = [c for c in cap_of.values() if c and 0 < _cap_order(c) <= 4096]
        # 版本裡讀不到的容量(那一頁沒有版本、或版本只寫「Wi-Fi」「5G」→ 容量是從規格讀的)照樣留著(複審第二輪 P1)
        covered = {_storage_of(c) for c in caps}
        caps += [c for side in (a, b) for c in side.get("capacities") or [] if _storage_of(c) not in covered]
        if out["capacities"]:   # 兩頁都沒有容量(穿戴)就維持沒有
            out["capacities"] = _tidy_caps(caps)
        out["prices"] = [{**p, "storage": cap_of.get((p.get("version"), sogi._storage(p.get("version") or "")), p.get("storage")) or None}
                         for p in out["prices"]]
        out["variants"] = union
    launches = [x for x in (a.get("launched"), b.get("launched")) if x]
    out["launched"] = min(launches) if launches else ""
    out["category"] = a.get("category") or b.get("category") or ""
    out["unreleased"] = bool(a.get("unreleased") and b.get("unreleased"))   # 有一頁上市了就算上市(上市取早的那一頁)
    return out


def hold(info: dict, today) -> str:
    """先等、不給人看的原因(空字串 = 不用等):分不出是哪一類(等它上清單)、還沒上市而且沒寫日期 / 日期過了。"""
    if info.get("kind") == "":
        return "看不出是手機還是平板,等它上清單"
    if info.get("unreleased"):
        if not info.get("launched"):
            return "還沒公布上市日期"
        if info["launched"] < today.strftime("%Y-%m"):
            return f"過了預計上市({info['launched']})還沒上市"
    return ""


def missing(info: dict, today) -> str:
    """資料不齊的原因(空字串 = 齊了)。還沒上市但寫了這個月或之後的上市月份 = 齊了(owner 2026-10-20 要上市前就建)。"""
    wait = hold(info, today)
    if wait:
        return wait
    if not info.get("launched"):
        return "還沒寫上市日期"
    if not info.get("unreleased") and info["launched"] > today.strftime("%Y-%m"):
        return f"還沒上市({info['launched']})"
    if info.get("category") in (DeviceModel.Category.PHONE, DeviceModel.Category.TABLET) and not info.get("capacities"):
        return "還沒有容量"
    if info.get("category") in EXPANDED and not info.get("colors"):
        return "還沒有顏色"
    return ""


def doubt(info: dict, ix: Index) -> tuple[str, list]:
    """要人看的原因與「可能是哪一支」(空字串 = 不用人看)。"""
    if not info.get("brand"):
        return f"新的品牌「{info.get('raw_brand') or '?'}」", []
    if not info.get("category"):
        return "看不出是手錶、手環還是耳機", []
    if not info.get("name"):
        return "讀不出型號名稱", []
    near = sorted(ix.similar(info["brand"], info["name"]))
    if near:
        return "可能是型號庫的「" + "」「".join(ix.names[u] for u in near[:3]) + "」", [{"uid": u, "name": ix.names[u]} for u in near[:5]]
    return "", []


def group_key(info: dict) -> tuple:
    """同一次讀到、名稱一樣的併成一支(平板的 Wi-Fi 版與 5G 版);平台按「加入」時也照這個把同一支的其他頁一起處理。"""
    brand = info.get("brand") or info.get("raw_brand") or ""
    phone = info.get("category") == DeviceModel.Category.PHONE
    return (brand.casefold(), phone, *strong_key(info.get("name") or "", brand, phone=phone))


def new_uid(info: dict) -> str:
    first = min(info["sources"])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, first))


def catalog_row(uid: str, info: dict) -> dict:
    return {"uid": uid, "origin": ORIGIN, "category": info["category"], "brand": info["brand"], "name": info["name"],
            "launched": info["launched"], "capacities": info["capacities"], "connectivity": info["connectivity"],
            "sizes_mm": [], "colors": info["colors"], "prices": info["prices"], "sources": info["sources"],
            "aliases": info["aliases"], "needs_review": []}


# ───────────────────────── 寫進去 ─────────────────────────

@dataclass
class Report:
    counts: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    ok: bool = True

    def bump(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n


def _expand(uids: list[str], report: Report, *, add_variants=()):
    """自動加 / 補的那幾支展開到有勾的公司。一家出錯不擋別家,講出來。"""
    for tenant in Tenant.objects.filter(is_active=True, auto_device_models=True).order_by("pk"):
        try:
            r = device_expand.expand(tenant, uids=uids, add_variants=set(add_variants), confirm=True)
        except device_expand.ExpandError as exc:
            report.notes.append(f"{tenant.code}:{exc}")
            continue
        made = sum(r.created.values())
        if made:
            report.bump("products", made)
            report.notes.append(f"{tenant.code}:建了 {made} 個品號")
        report.notes.extend(f"{tenant.code}:{p}" for p in r.problems)


def add_to_catalog(info: dict, candidates: list[DeviceCandidate], report: Report, *, user=None, source="") -> str:
    """加一支進型號庫 + 那幾頁標成已加 + 展開。整支在一個交易裡(展開每一家各自一個交易,在它裡面)。
    呼叫的人要先鎖住那幾頁(`_claim` / `decide`)。"""
    uid = new_uid(info)
    with transaction.atomic():
        device_catalog.sync({"models": [catalog_row(uid, info)]}, source=source or f"手機王自動更新 {timezone.localdate():%Y-%m-%d}")
        now = timezone.now()
        for c in candidates:
            c.status, c.uid, c.reason = DeviceCandidate.Status.ADDED, uid, ""
            if user is not None:
                c.decided_by, c.decided_at = user, now
            c.save()
        report.bump("added")
        _expand([uid], report)
    return uid


def _save_candidate(item, kind, status, *, reason="", data=None, uid="", checked=False):
    """記一頁。**鎖住那一筆再看**:讀網頁的這段時間平台管理員已經按了(不收 / 同一型號 / 加入)的,不改回去,回 None。
    要在交易裡呼叫(`_claim`);單獨呼叫時自己開一個。"""
    with transaction.atomic():
        c = DeviceCandidate.objects.select_for_update().filter(source="sogi", source_id=item["id"]).first()
        if c is not None and c.status not in OPEN:
            return None
        values = {"kind": kind, "url": (sogi.BASE + item["path"])[:300], "list_name": item["name"][:200], "status": status,
                  "reason": reason[:300], "data": data or {}, "uid": uid, **({"checked_at": timezone.now()} if checked else {})}
        if c is None:
            return DeviceCandidate.objects.create(source="sogi", source_id=item["id"], **values)
        for k, v in values.items():
            setattr(c, k, v)
        c.save()
        return c


def _claim(members, data):
    """一支要自動加之前:那幾頁都還沒有人決定才加(鎖著,交易結束前別人按不了)。有人決定過了回 None。"""
    cands = [_save_candidate(item, kind, DeviceCandidate.Status.WAITING, data=data, checked=True) for kind, item, _ in members]
    return None if any(c is None for c in cands) else cands


def _watched(today) -> dict[str, list[DeviceCandidate]]:
    """要盯的:自動加進來、還沒滿 WATCH_DAYS 天的那幾支(上市前就加的,算到上市月份之後 WATCH_DAYS 天)→ 它們的商品頁。"""
    since = timezone.now() - timedelta(days=WATCH_DAYS)
    month = (today - timedelta(days=WATCH_DAYS)).strftime("%Y-%m")
    uids = set(DeviceModel.objects.filter(data__origin=ORIGIN, is_active=True)
               .filter(Q(created_at__gte=since) | Q(launched__gt=month)).values_list("uid", flat=True))
    out = {}
    for c in DeviceCandidate.objects.filter(uid__in=uids, status__in=SEEN).order_by("id"):
        out.setdefault(c.uid, []).append(c)
    return out


def _scan_ids(ix: Index, seen: dict, listed: set, scan_from: int | None) -> tuple[list[int], int]:
    """清單上沒有的頁要讀哪幾號:最近 SCAN_BACK 號裡型號庫、候選、清單都沒有的,從新的讀起、最多 SCAN_GAPS 頁
    (給了 `scan_from` = 從那一號起全部);回 (那幾號, 看過的最大編號)。最大編號往後由呼叫的人一頁一頁讀。"""
    known = {int(x) for x in (*ix.sogi_ids, *seen, *listed) if str(x).isdigit()}
    if not known:
        return [], 0
    top = max(known)
    start = top - SCAN_BACK if scan_from is None else scan_from
    gaps = [i for i in range(top - 1, max(1, start) - 1, -1) if i not in known]
    return (gaps if scan_from is not None else gaps[:SCAN_GAPS]), top


def check(fetcher: sogi.Fetcher | None = None, *, today=None, write=True, log=lambda m: None, scan_from: int | None = None) -> Report:
    """檢查一次。`write=False` 只算(什麼都不寫,商品頁照樣讀)。`scan_from` = 這一次從這一號起補讀清單上沒有的頁(第一次用)。
    回報告(筆數、要講的事)。"""
    fetcher = fetcher or sogi.Fetcher()
    today = today or timezone.localdate()
    report = Report()
    last_ok = DeviceWatchRun.objects.filter(ok=True).order_by("-day").first()
    before = (last_ok.counts if last_ok else {}) or {}
    lists = {}
    for kind, path in sogi.LISTS.items():
        try:
            items = sogi.parse_list(fetcher.get(path))
        except sogi.Blocked as exc:
            report.ok = False
            report.notes.append(str(exc))
            return report
        except OSError as exc:
            report.ok = False
            report.notes.append(f"{kind} 清單讀不到:{exc}")
            continue
        prev = int(before.get(f"list_{kind}") or 0)
        if len(items) < max(MIN_LIST, int(prev * SHRINK)):
            report.ok = False
            report.notes.append(f"{kind} 清單只讀到 {len(items)} 支(上一次 {prev} 支),當成這次讀失敗")
            continue
        lists[kind] = items
        report.counts[f"list_{kind}"] = len(items)

    ix = Index.build()
    seen = {c.source_id: c for c in DeviceCandidate.objects.filter(source="sogi")}
    todo = []   # (kind, item, candidate 或 None)
    handled = set()   # 同一頁出現在兩頁清單上(例:手機與平板)只處理一次
    for kind, items in lists.items():
        for item in items:
            if item["id"] in handled:
                continue
            handled.add(item["id"])
            c = seen.get(item["id"])
            if c is not None and c.status not in OPEN:
                continue
            if c is None and item["id"] in ix.sogi_ids:
                continue
            brand, _, name, _ = split_list_name(kind, item["name"], ix.brands)
            if c is None and brand and name:
                hit = ix.same(brand, name, phone=kind == "cellphone")
                if hit:
                    report.bump("known")
                    if write:
                        _save_candidate(item, kind, DeviceCandidate.Status.KNOWN, uid=sorted(hit)[0])
                    continue
            todo.append((kind, item, c))
    listed = {item["id"] for items in lists.values() for item in items}
    # 等資料的也每天再讀一次(清單上這次沒有它的,照原本的網址讀;最久沒讀的先讀)。
    # 等了 STALE_DAYS 天還在等的(只在國外發表、分不出類別的舊頁)改成每 STALE_EVERY 天一次,不佔每天的頁數
    now = timezone.now()
    again = []
    for c in sorted(seen.values(), key=lambda c: (c.checked_at or c.created_at, c.id)):
        if c.status != DeviceCandidate.Status.WAITING or c.source_id in listed:
            continue
        if c.created_at < now - timedelta(days=STALE_DAYS) and c.checked_at and c.checked_at > now - timedelta(days=STALE_EVERY):
            continue
        again.append((c.kind, {"id": c.source_id, "name": c.list_name, "path": c.url.replace(sogi.BASE, "", 1)}, c))

    gaps, top = _scan_ids(ix, seen, listed, scan_from) if lists else ([], 0)
    limit = MAX_DETAIL + (len(gaps) if scan_from is not None else 0)
    pages = 0
    fetched = set()   # 這一次讀過的商品頁(盯新機那一步不再讀一次)
    groups = {}   # (品牌, 鍵) → [info, [(kind, item, c)]]

    def take(kind, item, c, page):
        info = info_of(kind, item, page, ix.brands)
        key = group_key(info)
        if hold(info, today):
            # 還在等的頁自己一組(複審 P0):上市的 Wi-Fi 版 + 沒公布日期的 5G 版,5G 版的容量 / 連線不跟著建
            key = (*key, "先等", item["id"])
        if key in groups:
            groups[key][0] = merge(groups[key][0], info)
            groups[key][1].append((kind, item, c))
        else:
            groups[key] = [info, [(kind, item, c)]]

    def full(reserve=0):
        if pages >= limit - reserve:
            report.notes.append(f"商品頁一次最多讀 {limit} 頁,剩下的下一次再讀")
            return True
        return False

    try:
        # 1. 清單上新的
        for kind, item, c in todo:
            if c is not None and c.status == DeviceCandidate.Status.REVIEW:
                continue   # 等人按,不重讀
            if full():
                break
            try:
                page = sogi.parse_product(fetcher.get(item["path"]))
                pages += 1
                fetched.add(item["id"])
            except OSError as exc:
                report.notes.append(f"{item['name']} 的商品頁讀不到:{exc}")
                continue
            take(kind, item, c, page)
        # 2. 清單上沒有的頁(還沒上市的只有商品頁):最近沒看過的幾號,再從最大編號往後讀到連續幾頁不存在
        scanned = found = 0
        if top and pages < limit:
            misses, nxt, queue = 0, top + 1, list(gaps)
            while not full():
                if queue:
                    pid = queue.pop(0)
                elif misses < SCAN_MISSES:
                    pid, nxt = nxt, nxt + 1
                else:
                    break
                scanned += 1
                try:
                    page = sogi.parse_product(fetcher.get(sogi.product_path(pid)))
                    pages += 1
                except OSError:
                    pages += 1
                    if pid > top:
                        misses += 1
                    continue
                if pid > top:
                    misses = 0
                found += 1
                fetched.add(str(pid))
                # 型號庫已經有同名的,後面記成「已經有」(跟清單上的一樣)
                item = {"id": str(pid), "name": page.get("name") or f"手機王 {pid}", "path": page.get("path") or sogi.product_path(pid)}
                take(guess_kind(page), item, None, page)
        if scanned:
            report.counts["scanned"], report.counts["found"] = scanned, found
        # 3. 等資料的再讀一次
        for kind, item, c in again:
            if full(FOLLOW_RESERVE):
                break
            try:
                page = sogi.parse_product(fetcher.get(item["path"]))
                pages += 1
                fetched.add(item["id"])
            except OSError as exc:
                report.notes.append(f"{item['name']} 的商品頁讀不到:{exc}")
                continue
            take(kind if kind in sogi.LISTS else guess_kind(page), item, c, page)
    except sogi.Blocked as exc:
        # 讀到一半被擋(複審 P1):前面讀到的也不加,這一次什麼都不改
        report.ok = False
        report.notes.append(f"{exc},這一次什麼都不改")
        report.counts["pages"] = pages
        return report
    report.counts["pages"] = pages

    plans = []
    for key, (info, members) in groups.items():
        why, near = doubt(info, ix)
        if hold(info, today):
            plans.append(("waiting", info, members, hold(info, today), []))
        elif why:
            plans.append(("review", info, members, why, near))
        elif missing(info, today):
            plans.append(("waiting", info, members, missing(info, today), []))
        else:
            plans.append(("add", info, members, "", []))
    adds = [p for p in plans if p[0] == "add"]
    if len(adds) > MAX_AUTO:
        report.notes.append(f"這一次新的有 {len(adds)} 支(超過 {MAX_AUTO}),全部先給人看")
        plans = [("review", p[1], p[2], f"這一次新的太多({len(adds)} 支),先給人看", []) if p[0] == "add" else p for p in plans]

    for action, info, members, why, near in plans:
        label = f"{info['brand'] or info['raw_brand']} {info['name']}"
        data = {**info, "key": list(group_key(info)), "near": near}
        hit = ix.same(info["brand"], info["name"], phone=info["category"] == DeviceModel.Category.PHONE) if info["brand"] else set()
        if hit:
            # 等資料的那幾天型號庫已經有了(別的來源、或平台剛加的同一支另一頁)
            report.bump("known")
            if write:
                for kind, item, _ in members:
                    _save_candidate(item, kind, DeviceCandidate.Status.KNOWN, data=data, uid=sorted(hit)[0], checked=True)
            continue
        if action == "add":
            log(f"加進型號庫:{label}")
            if not write:
                report.bump("added")
                continue
            try:
                with transaction.atomic():
                    cands = _claim(members, data)
                    if cands is None:
                        report.notes.append(f"{label}:平台管理員剛處理過,這次不動")
                        continue
                    add_to_catalog(info, cands, report)
                ix.add(new_uid(info), info["brand"], info["name"], info["category"], info["aliases"], info["sources"])
            except device_catalog.CatalogError as exc:
                report.notes.append(f"{label}:{exc}")
                for kind, item, _ in members:
                    _save_candidate(item, kind, DeviceCandidate.Status.REVIEW, reason=str(exc), data=data, checked=True)
                report.bump("review")
            continue
        status = DeviceCandidate.Status.REVIEW if action == "review" else DeviceCandidate.Status.WAITING
        report.bump(action)
        log(f"{'待確認' if action == 'review' else '等資料'}:{label}({why})")
        if write:
            for kind, item, _ in members:
                _save_candidate(item, kind, status, reason=why, data=data, checked=True)

    if report.ok and write:
        _follow_up(fetcher, report, ix, budget=MAX_DETAIL - pages, log=log, skip=fetched, today=today)
    return report


def _follow_up(fetcher, report, ix, *, budget, log, skip=frozenset(), today=None):
    """自動加進來的新機,多出來的容量 / 顏色 / 連線補進型號庫、補建品號(只加不減)。這一次已經讀過的頁(`skip`)不再讀;
    還在等的頁(沒公布日期、日期過了還沒上市)不算(複審 P0)。
    **先把要讀的頁全部讀完才改**:讀到一半被擋就一支都不補(跟新增同一條規則)。"""
    read = []   # (DeviceModel, 讀到的)
    today = today or timezone.localdate()
    for uid, cands in _watched(today).items():
        d = DeviceModel.objects.filter(uid=uid).first()
        if d is None or any(c.source_id in skip for c in cands):
            continue
        fresh = None
        for c in cands:
            if budget <= 0:
                break
            budget -= 1
            try:
                page = sogi.parse_product(fetcher.get(c.url.replace(sogi.BASE, "", 1)))
            except sogi.Blocked as exc:
                report.ok = False
                report.notes.append(f"{exc},這一次什麼都不補")
                return
            except OSError:
                continue
            item = {"id": c.source_id, "name": c.list_name, "path": c.url.replace(sogi.BASE, "", 1)}
            info = info_of(c.kind, item, page, ix.brands)
            if hold(info, today):
                continue
            fresh = info if fresh is None else merge(fresh, info)
        if fresh is not None:
            read.append((d, fresh))
    for d, fresh in read:
        _grow(d, fresh, report, log)


def _grow(d, fresh, report, log):
    """一支自動加的新機:讀到的跟型號庫比,多出來的補進去、有勾的公司補建品號。"""
    data = dict(d.data or {})
    old = {k: list(data.get(k) or []) for k in ("capacities", "colors", "connectivity", "sources", "aliases", "prices")}
    now_info = merge({**old, "launched": d.launched, "category": d.category}, fresh)
    grew = {k: [x for x in now_info[k] if x not in old[k]] for k in ("capacities", "colors", "connectivity")}
    if d.category not in (DeviceModel.Category.PHONE, DeviceModel.Category.TABLET):
        grew["capacities"] = []
    # 同一個容量換了寫法(原本 256GB、現在多了 12GB 版本變成 8GB/256GB + 12GB/256GB,或反過來)→ 不自動補:
    # 原本那個品號已經在了,再建會變成同一台有兩個品號。講出來給人處理。
    had = {_storage_of(c) for c in old["capacities"]}
    odd = [c for c in fresh.get("capacities") or [] if c not in old["capacities"] and _storage_of(c) in had]
    if odd and d.category in (DeviceModel.Category.PHONE, DeviceModel.Category.TABLET):
        report.notes.append(f"{d}:{'、'.join(odd)} 跟型號庫原本的容量寫法不一樣(原本 {'、'.join(old['capacities'])}),沒有自動補,請人處理")
    grew["capacities"] = [c for c in grew["capacities"] if c not in odd and _storage_of(c) not in had]
    if not any(grew.values()):
        return
    row = {"uid": d.uid, "category": d.category, "brand": d.brand, "name": d.name, "launched": d.launched,
           **{k: data[k] for k in device_catalog.DATA_KEYS if k in data}}
    for k in ("colors", "connectivity", "sources", "aliases", "prices"):
        row[k] = now_info[k]
    if d.category in (DeviceModel.Category.PHONE, DeviceModel.Category.TABLET):
        row["capacities"] = sorted([*old["capacities"], *grew["capacities"]], key=_cap_key)
    what = "、".join(x for k in ("capacities", "colors", "connectivity") for x in grew[k])
    try:
        with transaction.atomic():
            device_catalog.sync({"models": [row]}, source=f"手機王自動更新(補) {timezone.localdate():%Y-%m-%d}")
            report.bump("updated")
            report.notes.append(f"{d}:補上 {what}")
            log(f"補進型號庫:{d}({what})")
            _expand([d.uid], report, add_variants=[d.uid])
    except device_catalog.CatalogError as exc:
        report.notes.append(f"{d}:{exc}")


# ───────────────────────── 每天一次 ─────────────────────────

def run_today(*, again=False, fetcher=None, log=lambda m: None, scan_from: int | None = None) -> DeviceWatchRun | None:
    """今天還沒做就做(`again` = 做過也再做一次;`scan_from` 見 `check`)。另一個程序正在做 → 回 None。"""
    today = timezone.localdate()
    if not again and DeviceWatchRun.objects.filter(day=today, finished_at__isnull=False).exists():
        return None
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_KEY])
        if not cur.fetchone()[0]:
            return None
    try:
        if not again and DeviceWatchRun.objects.filter(day=today, finished_at__isnull=False).exists():
            return None
        run, _ = DeviceWatchRun.objects.get_or_create(day=today)
        try:
            report = check(fetcher, today=today, log=log, scan_from=scan_from)
        except Exception as exc:  # noqa: BLE001 — 記下來、明天再試,不讓背景程式掛掉
            report = Report(ok=False, notes=[f"檢查失敗 {type(exc).__name__}: {exc}"[:300]])
        run.ok, run.counts, run.notes, run.finished_at = report.ok, report.counts, report.notes[:100], timezone.now()
        run.save()
        return run
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", [LOCK_KEY])


def run_due(now=None, log=lambda m: None):
    """備份背景程式每分鐘呼叫:過了 `DEVICE_WATCH_AT` 而今天還沒做才做。"""
    at = watch_time()
    if at is None or timezone.localtime(now or timezone.now()).time() < at:
        return None
    run = run_today(log=log)
    if run is not None:
        log(f"型號庫自動更新:{'成功' if run.ok else '沒有成功'} {run.counts}")
    return run


# ───────────────────────── 平台管理員按的 ─────────────────────────

def decide(candidate_id: int, action: str, user, *, name: str = "", uid: str = "") -> dict:
    """「加入」(`add`,可以改名稱)/「就是那一支」(`same` + uid)/「不收」(`dismiss`)。同一支的其他頁(Wi-Fi 版與 5G 版)一起。"""
    report = Report()
    with transaction.atomic():
        c = DeviceCandidate.objects.select_for_update().filter(pk=candidate_id).first()
        if c is None:
            raise DecideError("找不到這一筆")
        if c.status not in OPEN:
            raise DecideError(f"這一筆已經是「{c.get_status_display()}」了,請重新整理")
        key = (c.data or {}).get("key")
        mates = list(DeviceCandidate.objects.select_for_update().filter(status__in=OPEN).exclude(pk=c.pk).order_by("id"))
        group = [c] + [m for m in mates if key and (m.data or {}).get("key") == key]
        now = timezone.now()
        if action == "dismiss":
            for m in group:
                m.status, m.decided_by, m.decided_at = DeviceCandidate.Status.DISMISSED, user, now
                m.save()
            return {"status": "dismissed", "count": len(group)}
        if action == "same":
            if not DeviceModel.objects.filter(uid=uid).exists():
                raise DecideError("型號庫沒有這一支")
            for m in group:
                m.status, m.uid, m.decided_by, m.decided_at = DeviceCandidate.Status.LINKED, uid, user, now
                m.save()
            return {"status": "linked", "count": len(group)}
        if action != "add":
            raise DecideError("不認得要做什麼")
        # 還在等的頁(沒公布日期的 5G 版)不跟著加,留著等資料(複審第二輪 P0)
        group = [c] + [m for m in group[1:] if not hold(m.data or {}, timezone.localdate())]
        info = dict(c.data or {})
        for m in group[1:]:
            info = merge(info, m.data or {})
        name = (name or "").strip()
        if name:
            if len(name) > 160:
                raise DecideError("型號名稱太長")
            info["name"] = name
        if not info.get("brand"):
            info["brand"] = info.get("raw_brand") or ""
        if not info.get("brand") or not info.get("name") or not info.get("category"):
            raise DecideError("品牌、型號、類別要齊才能加入")
        lack = missing(info, timezone.localdate())
        if lack:
            raise DecideError(f"資料還不齊:{lack}")
        # 改過名稱也要再看一次型號庫是不是已經有(複審 P1:改成「Galaxy A57 (5G)」就跟「Galaxy A57 5G」變兩支)
        ix = Index.build()
        hit = ix.same(info["brand"], info["name"], phone=info["category"] == DeviceModel.Category.PHONE)
        if hit:
            raise DecideError("型號庫已經有「" + "」「".join(ix.names[u] for u in sorted(hit)[:3]) + "」,是同一支請按「同一型號」")
        try:
            new = add_to_catalog(info, group, report, user=user, source=f"平台加入(手機王) {timezone.localdate():%Y-%m-%d}")
        except device_catalog.CatalogError as exc:
            raise DecideError(str(exc)) from None
    return {"status": "added", "uid": new, "count": len(group), "notes": report.notes}
