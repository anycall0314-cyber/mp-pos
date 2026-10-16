"""店內配件品名 → 手機品牌 / 適用機型 / 其他片段(M1-E 第二段,2026-10-16)。

店內品名的寫法是「種類/廠牌/手機品牌/機型/款式/顏色」,中間幾段可有可無:
`背蓋/DAP/IP6+/多工插卡`、`9H/滿/SAM/M11/黑`、`皮套/平板/DAP/OPPO/PAD 2/立架玫金`、`空壓/REALME-11X`。

跟 `accessory_model_match` 的差別:那支是照舊的機型主檔寫的(而且商品比對在用,不動它);
這支照**平台型號庫的名稱**(`Galaxy S25 Ultra`、`vivo X200 FE`、`Redmi Note 15 Pro+ 5G`)建查表,
而且**看前面的手機品牌**:`SAM/S8` 只在三星裡找、`紅米/NOTE15P+` 只在紅米裡找 ——
沒有品牌的片段只認 iPhone 的寫法(`IP15PM`、`16PM`),或全部品牌裡只有一支對得到的。

只做查表(這一支不判斷):對不到的片段原樣交回去,怎麼處理由呼叫的人決定。
這裡不碰資料庫,單純吃字串;機型清單由呼叫的人給 `(id, 名稱, 品牌)`。
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

# 店內寫的手機品牌 → 品牌群組。只收品牌本身的各種寫法(查表,不是判斷)。
BRAND_ALIASES = {
    "APPLE": "APPLE", "IPHONE": "APPLE", "蘋果": "APPLE",
    "SAM": "SAMSUNG", "SAMSUNG": "SAMSUNG", "三星": "SAMSUNG", "GALAXY": "SAMSUNG",
    "OPPO": "OPPO",
    "VIVO": "VIVO", "IQOO": "VIVO",
    "小米": "XIAOMI", "XIAOMI": "XIAOMI",
    "紅米": "REDMI", "REDMI": "REDMI",
    "POCO": "POCO",
    "REALME": "REALME",
    "SONY": "SONY", "XPERIA": "SONY",
    "GOOGLE": "GOOGLE", "PIXEL": "GOOGLE",
    "ASUS": "ASUS", "ROG": "ASUS",
    "華為": "HUAWEI", "HUAWEI": "HUAWEI",
    "HTC": "HTC", "LG": "LG",
    "MOTO": "MOTO", "MOTOROLA": "MOTO",
    "NOKIA": "NOKIA", "SHARP": "SHARP", "SUGAR": "SUGAR",
    "HONOR": "HONOR", "榮耀": "HONOR",
    "NOTHING": "NOTHING", "BENTEN": "BENTEN",
    "聯想": "LENOVO", "LENOVO": "LENOVO",
    "INF": "INFOCUS", "INFOCUS": "INFOCUS",
    "ONEPLUS": "ONEPLUS", "一加": "ONEPLUS",
}

# 型號庫的品牌 → 群組(小米的機子再看名稱分小米 / 紅米 / POCO)
CATALOG_BRAND_GROUP = {
    "apple": "APPLE", "samsung": "SAMSUNG", "oppo": "OPPO", "vivo": "VIVO", "iqoo": "VIVO",
    "xiaomi": "XIAOMI", "小米xiaomi": "XIAOMI", "紅米redmi": "REDMI", "poco": "POCO", "realme": "REALME",
    "sony": "SONY", "google": "GOOGLE", "asus": "ASUS", "huawei": "HUAWEI", "htc": "HTC", "lg": "LG",
    "motorola": "MOTO", "nokia": "NOKIA", "sharp": "SHARP", "sugar": "SUGAR", "honor": "HONOR",
    "nothing": "NOTHING", "cmf": "NOTHING", "benten": "BENTEN", "lenovo": "LENOVO", "oneplus": "ONEPLUS",
}

# 型號庫名稱前面的品牌字(店內品名不寫,寫在前一段)
_PREFIX = re.compile(
    r"^(galaxy|vivo|oppo|realme|redmi|xiaomi|小米|紅米|poco|pixel|xperia|zenfone|huawei|motorola|moto|"
    r"nokia|sugar|htc|lg|honor|benten|iqoo|find)\s*", re.I)

_IPHONE = re.compile(r"^iPhone\s+(\d{1,2})\s*(Plus|Pro Max|Pro|mini|Air|e)?$", re.I)
_IPHONE_SUFFIX = {
    "": [""], "plus": ["+", "PLUS"], "pro": ["PRO", "P"], "pro max": ["PM", "PROMAX"],
    "mini": ["MINI"], "air": ["AIR"], "e": ["E"],
}
_IPHONE_OTHER = {   # 型號庫名稱 → 店內寫法(不帶 IP 的也收)
    "iphone 5s": ["5S"], "iphone 6s": ["6S"], "iphone 6s plus": ["6S+", "6SP", "6SPLUS"],
    "iphone x": ["X"], "iphone xr": ["XR"], "iphone xs": ["XS"], "iphone xs max": ["XSMAX", "XSM"],
    "iphone se": ["SE"], "iphone se (2020)": ["SE2", "SE2020", "SE(2020)"], "iphone se (2022)": ["SE3", "SE2022", "SE(2022)"],
}

# 店內的縮寫(前面是型號庫的寫法):PRO MAX → PM、PRO → P、PLUS → +、ULTRA → U
_SUBS = [("PROMAX", ("PROMAX", "PM")), ("PRO", ("PRO", "P")), ("PLUS", ("PLUS", "+")), ("ULTRA", ("ULTRA", "U"))]


def norm(s: str) -> str:
    return re.sub(r"[\s()（）_]+", "", s or "").upper()


_NET = re.compile(r"(5G|4G|WI-?FI|LTE)$")   # 連線版本:同一支的 5G / Wi-Fi / LTE 版配件通用


def _variants(core: str) -> set[str]:
    """`S25ULTRA5G` → {S25ULTRA5G, S25ULTRA, S25U5G, S25U, …}。"""
    out = set()
    for drop5g in (False, True):
        base = _NET.sub("", core) if drop5g else core
        # 依序替換;每一種縮寫都可以用或不用
        options = [base]
        for long, shorts in _SUBS:
            nxt = set()
            for o in options:
                if long in o:
                    for s in shorts:
                        nxt.add(o.replace(long, s))
                else:
                    nxt.add(o)
            options = list(nxt)
        out.update(options)
    return {o for o in out if o}


def model_group(name: str, brand: str) -> str:
    b = (brand or "").strip().casefold()
    g = CATALOG_BRAND_GROUP.get(b, b.upper())
    if g == "XIAOMI":
        if name.lower().startswith("redmi"):
            return "REDMI"
        if name.lower().startswith("poco"):
            return "POCO"
    return g


@dataclass
class ModelIndex:
    """{群組: {店內寫法: {機型 id}}};`exact` 是不去掉 5G 的那一份(有的話優先)。"""
    keys: dict[str, dict[str, set[int]]] = field(default_factory=dict)
    exact: dict[str, dict[str, set[int]]] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)
    groups: dict[int, str] = field(default_factory=dict)
    tablets: set[int] = field(default_factory=set)

    def add(self, group: str, key: str, mid: int, exact: bool):
        key = norm(key)
        if len(key) < 1:
            return
        self.keys.setdefault(group, {}).setdefault(key, set()).add(mid)
        if exact:
            self.exact.setdefault(group, {}).setdefault(key, set()).add(mid)

    def find(self, group: str, key: str, exact_only: bool = False) -> set[int]:
        key = norm(key)
        hit = self.exact.get(group, {}).get(key)
        if not hit and not exact_only:
            hit = self.keys.get(group, {}).get(key)
        return set(hit or ())


_CODE = re.compile(r"[A-Za-z]{2,4}\d{3,}[A-Za-z]{0,4}")   # 括號裡的型號:`ZS630KL`(不收 `A16`、`M4` 這種短的)


def _alt_names(name: str) -> set[str]:
    """型號庫名稱的幾種讀法:原樣;括號裡只是容量或型號時去掉括號(`P30 Pro (8G/128G)`、`ZenFone 6 (ZS630KL)`);
    砍掉後面的中文(`P30 Pro 頂配版`,砍完要還有數字);括號裡的型號本身(`ZS630KL`)。
    括號裡是年份 / 代數 / 晶片的不去掉:`iPad (2019)` 去掉就只剩 `iPad`,會把所有 iPad 的配件都吃進來。"""
    out = {name}
    inners = re.findall(r"[(（]([^)）]*)[)）]", name)
    if inners and all("/" in i or _CODE.fullmatch(i.strip()) for i in inners):
        out.add(re.sub(r"\s*[(（][^)）]*[)）]", "", name).strip())
    for base in list(out):
        cut = re.split(r"\s*[一-鿿]", base, maxsplit=1)[0].strip()
        if cut and cut != base and _HAS_DIGIT.search(cut) and not re.search(r"[(（][^)）]*$", cut):
            out.add(cut)
    for inner in inners:
        if _CODE.fullmatch(inner.strip()):
            out.add(inner.strip())
    return {o for o in out if o}


_TABLET_NAME = re.compile(r"tab|pad|平板|surface|nxtpaper|iconia", re.I)


def build_index(models) -> ModelIndex:
    """`models` = [(id, 名稱, 品牌名稱)] 或 [(id, 名稱, 品牌名稱, 型號庫的種類)];沒給種類的照名稱看是不是平板。"""
    idx = ModelIndex()
    rows = [(m[0], (m[1] or "").strip(), m[2], m[3] if len(m) > 3 else "") for m in models]
    models = [(mid, name, brand) for mid, name, brand, _ in rows]
    names = {name.lower() for _, name, _ in models}
    for mid, name, _, kind in rows:
        if kind == "tablet" or (not kind and _TABLET_NAME.search(name)):
            idx.tablets.add(mid)
    for mid, name, brand in models:
        group = model_group(name, brand)
        idx.names[mid] = name
        idx.groups[mid] = group
        low = name.lower()
        if group == "APPLE":
            mo = _IPHONE.match(name)
            if mo:
                num, suf = mo.group(1), (mo.group(2) or "").lower()
                codes = list(_IPHONE_SUFFIX.get(suf, []))
                if suf == "plus" and f"iphone {num} pro" not in names:
                    codes.append("P")   # 6 / 7 / 8 沒有 Pro:店內 `IP7P` = 7 Plus(11 以後 `IP11P` = 11 Pro)
                for c in codes:
                    idx.add(group, f"IP{num}{c}", mid, True)
                    idx.add(group, f"IPHONE{num}{c}", mid, True)
                    if c:   # 裸數字(`8`)多半是吋數,只收有後綴的(`16PM`、`17E`)
                        idx.add(group, f"{num}{c}", mid, True)
                continue
            if low in _IPHONE_OTHER:
                for c in _IPHONE_OTHER[low]:
                    idx.add(group, f"IP{c}", mid, True)
                    if len(c) >= 2:
                        idx.add(group, c, mid, True)
                continue
        for alt in _alt_names(name):
            core = norm(_PREFIX.sub("", alt))
            full = norm(alt)
            forms = {core, full}
            if group == "SAMSUNG":
                forms.add(core.replace("ZFOLD", "FOLD").replace("ZFLIP", "FLIP"))
            if group == "ASUS":
                forms |= {full.replace("ZENFONE", "ZF"), full.replace("ROGPHONE", "ROG")}
            if group == "HTC":
                forms.add(full.replace("DESIRE", "D"))
            for f in forms:
                for v in _variants(f):
                    idx.add(group, v, mid, not _NET.search(f) or bool(_NET.search(v)))
    return idx


_IP_TOKEN = re.compile(r"^IP(HONE)?(\d|X|SE)")
_HAS_DIGIT = re.compile(r"\d")
SPLIT = re.compile(r"/+")


@dataclass
class Parsed:
    segments: list[str]
    host_groups: list[str]            # 品名裡出現的手機品牌(照順序、不重複)
    models: set[int]                  # 對到的機型
    unmatched: list[str]              # 像機型、但對不到的片段(有數字)
    others: list[tuple[int, str]]     # 其他片段(位置, 原字);廠牌、種類、款式都在這裡
    first_model_at: int | None        # 第一個對到機型的片段位置


def _split_brand(seg: str):
    """`REALME-10T` → ("REALME", "10T");`紅米-NOTE12P+(5G)` → ("REDMI", "NOTE12P+(5G)")。"""
    if "-" in seg:
        head, rest = seg.split("-", 1)
        g = BRAND_ALIASES.get(head.upper())
        if g:
            return g, rest
    for alias, g in BRAND_ALIASES.items():   # `小米3`、`紅米NOTE10PRO` 這種黏在一起的(只收中文品牌)
        if not alias.isascii() and seg.startswith(alias) and len(seg) > len(alias):
            return g, seg[len(alias):]
    return None, seg


def _lookup(idx: ModelIndex, group: str | None, seg: str) -> set[int]:
    raw = seg.upper().strip()
    cands = [raw, raw.replace("-", "")]
    cut = re.split(r"\s*[一-鿿]", raw, maxsplit=1)[0].strip().rstrip("-")
    if cut and cut != raw:   # 顏色 / 款式黏在後面:`X300PRO超聲波`、`NOTE13PRO(5G)黑`;只剩數字的是吋數(`6吋`)
        if not re.fullmatch(r"[\d.]+", cut):
            cands.append(cut)
        raw = cut
    m5 = re.search(r"\((5G|4G)\)$", raw)
    plain = None
    if m5:   # `A55(5G)`:先找有 5G 的,再找名稱沒寫連線的(不收「只有 5G 版、被去掉 5G」的那種:寫明 4G 不能對到 5G)
        cands.append(raw[: m5.start()] + m5.group(1))
        plain = raw[: m5.start()]
    if _IP_TOKEN.match(raw):
        group = "APPLE"
    if not group:
        return set()
    for c in cands:
        hit = idx.find(group, c)
        if hit:
            return hit
    if plain:
        return idx.find(group, plain, exact_only=True)
    head, _, tail = raw.partition("-")
    if tail and (not re.search(r"[A-Z]", tail) or _IP_TOKEN.match(head)):
        # 連字號當分隔、後面是款式或吋數:`IP6-漸層`、`IP6-4.7-亮` → 第一段是機型。
        # 後面有英文的不拆(iPhone 的除外:`IP6-DEVIA`):`S6-LITE` 是平板 Tab S6 Lite、`SE-NEO` 是 Sony Ericsson
        return idx.find(group, head)
    return set()


def _lookup_any(idx: ModelIndex, seg: str) -> set[int]:
    """沒有品牌的片段:全部群組裡只有一個群組對得到、而且片段夠長(字母 + 數字、4 個字以上)才算。
    (`T21` 這種短的常是系列名:`背蓋/T21/IP15PM` 不是 Nokia T21。)"""
    key = norm(seg)
    if len(key) < 4 or not re.search(r"[A-Z]", key) or not _HAS_DIGIT.search(key):
        return set()
    hits = {g: ids for g in idx.keys if (ids := idx.find(g, key))}
    if len(hits) == 1:
        return next(iter(hits.values()))
    return set()


def _by_size(idx: ModelIndex, hit: set[int], nxt: str) -> set[int]:
    """後面一段是尺寸(`9.7吋`),而型號庫有「同名 + 這個尺寸」的那一支 → 換成那一支(`紅米-PAD2/9.7吋` 是 Redmi Pad 2 9.7)。"""
    mo = re.fullmatch(r"(\d+(?:\.\d+)?)\s*吋", nxt.strip())
    if not mo:
        return hit
    size = mo.group(1)
    bases = {idx.names[m] for m in hit}
    if any(re.search(rf"(?<![\d.]){re.escape(size)}(?![\d.])", b) for b in bases):
        return hit
    sized = {m for m, n in idx.names.items() if any(n.startswith(b + " ") for b in bases)
             and re.search(rf"(?<![\d.]){re.escape(size)}(?![\d.])", n[len(min(bases, key=len)):])}
    return sized or hit


def parse(name: str, idx: ModelIndex) -> Parsed:
    # 舊系統匯入時同名的加了 `_1`、`_2`,不是品名的一部分
    segs = [re.sub(r"_\d+$", "", s.strip()) for s in SPLIT.split(name or "") if s.strip()]
    groups: list[str] = []
    models: set[int] = set()
    unmatched: list[str] = []
    others: list[tuple[int, str]] = []
    context: str | None = None
    first = None
    tablet = any(s == "平板" for s in segs)   # `皮套/平板/SAM/S10FE` 是 Galaxy Tab S10 FE,不是手機
    for i, seg in enumerate(segs):
        up = seg.upper()
        g = BRAND_ALIASES.get(up)
        if g:
            context = g
            if g not in groups:
                groups.append(g)
            continue
        g2, rest = _split_brand(seg)
        if g2:
            context = g2
            if g2 not in groups:
                groups.append(g2)
            hit = _lookup(idx, g2, rest)
        else:
            hit = (_lookup(idx, context, "TAB" + seg) if tablet and context == "SAMSUNG" else set()) \
                or _lookup(idx, context, seg)
            if not hit and context is None and not _IP_TOKEN.match(up):
                # 沒寫品牌的 iPhone 寫法只收有數字的(`16PM`、`SE2`)跟 X 系列(`XR`、`XS`);
                # 單寫 `SE` 在舊品名裡常是 Sony Ericsson
                hit = _lookup_any(idx, seg)
                if not hit and (_HAS_DIGIT.search(up) or up.startswith("X")):
                    hit = _lookup(idx, "APPLE", seg)
        if tablet:   # 寫了「平板」的只收平板:`皮套/平板/SAM/S6` 沒有 Tab S6 時不能掛到手機 Galaxy S6
            hit = {m for m in hit if m in idx.tablets}
        if hit and i + 1 < len(segs):
            hit = _by_size(idx, hit, segs[i + 1])
        if hit:
            models |= hit
            if first is None:
                first = i
            grp = {idx.groups[m] for m in hit}
            if len(grp) == 1:
                context = next(iter(grp))
                if context not in groups:
                    groups.append(context)
            continue
        if g2:
            unmatched.append(seg)
            continue
        if _IP_TOKEN.match(up) or (context and _HAS_DIGIT.search(up) and len(up) <= 24):
            unmatched.append(seg)
            continue
        others.append((i, seg))
    return Parsed(segs, groups, models, unmatched, others, first)
