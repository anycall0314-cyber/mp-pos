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
    ipads: dict[int, tuple] = field(default_factory=dict)   # 機型 id → (系列, 第幾代, 尺寸, 年份)

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


# 型號庫的 iPad → (系列, 第幾代, 尺寸, 年份)。這張表是已經上市的那幾代(Apple 的代數 / 尺寸 / 年份),也是往後算的基準;
# **表上沒有的新 iPad 照名稱與上市年份自己算**(`_ipad_specs`;V3,2026-10-18:型號庫每天自動加新機,不能等人來加表)。
# 店內寫法是「代數」(IPAD7、AIR4、MINI6、10代)、「尺寸」(10.2、11吋)或「尺寸 + 年份」(PRO/11吋(2024)),
# Pro 沒有代數。owner 2026-10-16:「iPad皮套是我最頭痛的，很常找不到，也看不懂」。
_IPAD_SPECS = {norm(k): v for k, v in {
    "iPad 5": ("", 5, "9.7", 2017), "iPad 6": ("", 6, "9.7", 2018), "iPad (2019)": ("", 7, "10.2", 2019),
    "iPad (2020)": ("", 8, "10.2", 2020), "iPad 9": ("", 9, "10.2", 2021), "iPad 10": ("", 10, "10.9", 2022),
    "iPad 11 (A16)": ("", 11, "11", 2025),
    "iPad Air 2": ("AIR", 2, "9.7", 2014), "iPad Air (2019)": ("AIR", 3, "10.5", 2019),
    "iPad Air (2020)": ("AIR", 4, "10.9", 2020), "iPad Air 5 (M1)": ("AIR", 5, "10.9", 2022),
    "iPad Air 11吋 (M2)": ("AIR", 6, "11", 2024), "iPad Air 13吋 (M2)": ("AIR", 6, "13", 2024),
    "iPad Air 11吋 (M3)": ("AIR", 7, "11", 2025), "iPad Air 13吋 (M3)": ("AIR", 7, "13", 2025),
    "iPad Air (2026) 11 吋": ("AIR", 8, "11", 2026), "iPad Air (2026) 13 吋": ("AIR", 8, "13", 2026),
    "iPad mini 4": ("MINI", 4, "7.9", 2015), "iPad mini (2019)": ("MINI", 5, "7.9", 2019),
    "iPad mini 6": ("MINI", 6, "8.3", 2021), "iPad mini 7 (A17 Pro)": ("MINI", 7, "8.3", 2024),
    "iPad Pro (2018) 11 吋": ("PRO", 0, "11", 2018), "iPad Pro (2018) 12.9 吋": ("PRO", 0, "12.9", 2018),
    "iPad Pro (2020) 11 吋": ("PRO", 0, "11", 2020), "iPad Pro (2020) 12.9 吋": ("PRO", 0, "12.9", 2020),
    "iPad Pro (2021) 11 吋": ("PRO", 0, "11", 2021), "iPad Pro (2021) 12.9 吋": ("PRO", 0, "12.9", 2021),
    "iPad Pro (2022) 11 吋": ("PRO", 0, "11", 2022), "iPad Pro (2022) 12.9 吋": ("PRO", 0, "12.9", 2022),
    "iPad Pro 11吋 (M4)": ("PRO", 0, "11", 2024), "iPad Pro 13吋 (M4)": ("PRO", 0, "13", 2024),
    "iPad Pro (2025) 11 吋": ("PRO", 0, "11", 2025), "iPad Pro (2025) 13 吋": ("PRO", 0, "13", 2025),
}.items()}
_IPAD_SIZES = {"7.9", "8.3", "9.7", "10.2", "10.5", "10.9", "11", "12.9", "13"}


_IPAD_NAME = re.compile(r"^iPad(?:\s+(Air|mini|Pro))?(?=[\s(（]|$)(.*)$", re.I)


def _read_ipad(name: str, launched: str):
    """表上沒有的 iPad 名稱 → (系列, 名稱寫明的代數(沒寫 0), 尺寸(沒寫 ""), 年份(名稱的括號,沒有看上市;都沒有 0));不是 iPad 回 None。
    `iPad Air 5 (M1)`、`iPad 12 (A18)` 的數字是代數;`iPad Air 11吋 (M5)` 的 11 是尺寸。"""
    mo = _IPAD_NAME.match((name or "").strip())
    if not mo:
        return None
    fam, rest = (mo.group(1) or "").upper(), mo.group(2)
    size = next((x for x in re.findall(r"(\d{1,2}(?:\.\d)?)\s*吋", rest) if x in _IPAD_SIZES), "")
    years = re.findall(r"[(（](20\d\d)[)）]", rest)
    year = int(years[0]) if years else (int(launched[:4]) if (launched or "")[:4].isdigit() else 0)
    gen = 0
    if fam != "PRO" and (g := re.match(r"\s*(\d{1,2})(?!\s*(?:\.\d|吋|\d))", rest)):
        gen = int(g.group(1))
    return fam, gen, size, year


def _ipad_specs(rows) -> dict:
    """`rows` = [(機型 id, 名稱, 上市)] → {機型 id: (系列, 第幾代, 尺寸, 年份)}。
    表上有的照表;沒有的:代數照名稱寫的,沒寫的照同一系列的上市年份排在已知的後面(同一年同一代、之後每多一年 +1);
    尺寸沒寫的照同一系列那一年(或之前最近一代)的尺寸;Pro 沒有代數、要有年份。年份看不出來的不算(對不到就不掛,不猜)。"""
    out: dict = {}
    pending = []
    for mid, name, launched in rows:
        spec = _IPAD_SPECS.get(norm(name))
        if spec:
            out[mid] = spec
        elif (r := _read_ipad(name, launched)) and r[3]:
            pending.append((mid, *r))
    history = list(_IPAD_SPECS.values()) + [(f, g, sz, y) for _, f, g, sz, y in pending if g]
    for mid, fam, gen, size, year in sorted(pending, key=lambda x: x[4]):
        same = [h for h in history if h[0] == fam]
        if fam != "PRO" and not gen:
            this_year = [h[1] for h in same if h[3] == year and h[1]]
            gen = max(this_year) if this_year else max([h[1] for h in same if h[3] < year] or [0]) + 1
        if not size:
            near = sorted((h for h in same if h[3] <= year and h[2]), key=lambda h: h[3])
            size = near[-1][2] if near and fam != "PRO" else ""
        out[mid] = (fam, gen, size, year)
        history.append((fam, gen, size, year))
    return out


def _size_class(s: str) -> str:
    return "11" if s in ("10.9", "11") else s   # 店內「11吋」包含 10.9 吋的(`AIR4-8/11吋` 從 Air 4 算起)


def _ipad(segs: list[str], idx: "ModelIndex", loose: bool = False) -> tuple[set[int], list[str], list[str]]:
    """`IPAD/AIR4/5/PRO11`、`IPAD7/8/10.2`、`IPAD/PRO/11吋(2024)` → 型號庫的 iPad。回 (機型, 寫得不夠清楚的那一段)。

    一段一段讀成好幾組「系列 + 代數 / 尺寸 / 年份」;代數、尺寸、年份接在最近的那一組後面。
    寫得夠清楚才掛(有代數、有年份、一般 iPad 寫了尺寸);Pro 只寫尺寸沒寫年份、只寫 Air / mini 的不猜,交回去。
    `loose`(搜尋用):寫得不夠清楚的也全部算(打「ipad pro 11」列出每一代 Pro 11 吋的配件)。
    回 (機型, 寫得不夠清楚的那一段, 不是 iPad 寫法的字);最後那一份給搜尋拿去比品名(`ipad air 5 皮套` 的「皮套」)。"""
    clauses: list[dict] = []
    rest: list[str] = []

    def start(fam, text, pro_too=False):
        if clauses and clauses[-1]["fam"] == "" and not (clauses[-1]["gens"] or clauses[-1]["sizes"] or clauses[-1]["years"]):
            clauses.pop()   # `IPAD/AIR4`:前面那個空的 IPAD 只是開頭
        c = {"fam": fam, "gens": set(), "sizes": set(), "years": set(), "text": [text], "pro_too": pro_too}
        clauses.append(c)
        return c

    cur = None
    for seg in segs:
        for raw in re.split(r"(?<!\d)-|-(?!\d)", seg.upper()):
            t = raw.strip()
            if not t:
                continue
            years = {int(y) for y in re.findall(r"20\d\d", t)}
            if mo := re.fullmatch(r"IPAD(\(PRO\))?(\d+)?(專用)?", t):
                cur = start("", t, pro_too=bool(mo.group(1)))
                if mo.group(2):
                    cur["gens"].add(int(mo.group(2)))
                continue
            if mo := re.fullmatch(r"(AIR|PRO|MINI)(\d+(?:\.\d+)*)?(?:-(\d+))?(吋)?", t):
                fam, num, to = mo.group(1), mo.group(2), mo.group(3)
                cur = start(fam, t)
                if num and fam == "PRO":
                    cur["sizes"].add(num)
                elif num:
                    first = [int(x) for x in num.split(".")]
                    cur["gens"].update(range(first[0], int(to) + 1) if to else first)
                continue
            if cur is None:
                rest.append(t)
                continue
            cur["text"].append(t)
            if mo := re.fullmatch(r"(\d+)代", t):
                cur["gens"].add(int(mo.group(1)))
            elif re.fullmatch(r"\d+(\.\d+){2,}", t):          # `7.8.9` = 第 7、8、9 代
                cur["gens"].update(int(x) for x in t.split("."))
            elif re.fullmatch(r"\(?20\d\d\)?", t):              # `(2024/2025)` 被斜線拆成兩段
                cur["years"] |= years
            elif mo := re.fullmatch(r"(\d+(?:\.\d+)?)\s*(吋)?\s*(\([\d/]+\)?)?", t):
                num, inch = mo.group(1), mo.group(2)
                if inch or "." in num or cur["fam"] == "PRO":
                    if num in _IPAD_SIZES:
                        cur["sizes"].add(num)
                    elif "." in num and not inch:
                        cur["gens"].update(int(x) for x in num.split("."))   # `MINI2.3`
                else:
                    cur["gens"].add(int(num))
                cur["years"] |= years
            else:
                cur["text"].pop()                              # 款式、顏色:不算機型
                rest.append(t)
    for c in list(clauses):
        if c["pro_too"]:                                     # `IPAD(PRO)/9.7`:一般 iPad 跟 Pro 都算
            clauses.append({**c, "fam": "PRO", "pro_too": False})
    all_sizes = {_size_class(s) for c in clauses for s in c["sizes"]}
    hits: set[int] = set()
    unsure: list[str] = []
    for c in clauses:
        def pick(fam):
            out = [(m, sp) for m, sp in idx.ipads.items() if sp[0] == fam]
            if c["gens"]:
                out = [x for x in out if x[1][1] in c["gens"]]
            if c["sizes"]:
                out = [x for x in out if any(s == x[1][2] or (s == "11" and x[1][2] == "10.9") for s in c["sizes"])]
            if c["years"]:
                out = [x for x in out if x[1][3] in c["years"]]
            return out
        found = pick(c["fam"])
        if not found and c["fam"] == "" and not c["gens"] and c["sizes"]:   # `IPAD/12.9(2020)`:12.9 吋只有 Pro
            fams = {f: r for f in ("AIR", "PRO", "MINI") if (r := pick(f))}
            if len(fams) == 1:
                found = next(iter(fams.values()))
        if not c["sizes"] and len({_size_class(sp[2]) for _, sp in found}) > 1 and all_sizes:
            found = [x for x in found if _size_class(x[1][2]) in all_sizes]   # `AIR4-7/PRO11`:Air 6、7 只要 11 吋
        clear = {
            "": bool(c["gens"] or c["sizes"]),
            "AIR": bool(c["gens"] or c["years"]),
            "MINI": bool(c["gens"]),
            "PRO": bool(c["years"]),
        }[c["fam"]]   # 型號庫剛好只有一台也不算清楚:舊的 Pro 11 皮套不能掛到唯一的那台 M4(複審 P1)
        if not found:
            if not (c["gens"] or c["sizes"] or c["years"]):
                unsure.append("/".join(c["text"]))   # 只寫 `IPAD-MINI`:不知道是哪一台
            continue                                 # 寫清楚了、型號庫沒有這一台(`MINI2`、`PRO/10.5`):不掛
        if loose or (clear and len({_size_class(sp[2]) for _, sp in found}) <= max(1, len(c["sizes"]), len(all_sizes))):
            hits |= {m for m, _ in found}
        else:
            unsure.append("/".join(c["text"]))
    return hits, unsure, rest


_TABLET_NAME = re.compile(r"tab|pad|平板|surface|nxtpaper|iconia", re.I)


def build_index(models) -> ModelIndex:
    """`models` = [(id, 名稱, 品牌名稱)]、[(id, 名稱, 品牌名稱, 型號庫的種類)] 或再加型號庫的上市(`2026-03`);
    沒給種類的照名稱看是不是平板。"""
    idx = ModelIndex()
    rows = [(m[0], (m[1] or "").strip(), m[2], m[3] if len(m) > 3 else "", m[4] if len(m) > 4 else "") for m in models]
    models = [(mid, name, brand) for mid, name, brand, _, _ in rows]
    names = {name.lower() for _, name, _ in models}
    for mid, name, _, kind, _ in rows:
        if kind == "tablet" or (not kind and _TABLET_NAME.search(name)):
            idx.tablets.add(mid)
    idx.ipads = _ipad_specs([(mid, name, launched or "") for mid, name, _, _, launched in rows])
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
    unsure: list[str] = field(default_factory=list)   # 寫得不夠清楚、對不下去的 iPad 寫法(`PRO/11吋` 沒寫年份)


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


def parse(name: str, idx: ModelIndex, loose: bool = False) -> Parsed:
    # 舊系統匯入時同名的加了 `_1`、`_2`,不是品名的一部分
    segs = [re.sub(r"_\d+$", "", s.strip()) for s in SPLIT.split(name or "") if s.strip()]
    groups: list[str] = []
    models: set[int] = set()
    unmatched: list[str] = []
    others: list[tuple[int, str]] = []
    context: str | None = None
    first = None
    tablet = any(s == "平板" for s in segs)   # `皮套/平板/SAM/S10FE` 是 Galaxy Tab S10 FE,不是手機
    unsure: list[str] = []
    for i, seg in enumerate(segs):
        up = seg.upper()
        if up.startswith("IPAD") or (tablet and context in (None, "APPLE") and re.match(r"(AIR|PRO|MINI)(\d|$|/|-)", up)):
            hit, unsure, rest = _ipad(segs[i:], idx, loose)   # iPad 的寫法自成一套,後面整段交給它
            others += [(len(segs), w) for w in rest]          # 排在最後:不是廠牌的位置,只給搜尋比品名
            if hit:
                models |= hit
                first = i if first is None else first
                if "APPLE" not in groups:
                    groups.append("APPLE")
            break
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
    return Parsed(segs, groups, models, unmatched, others, first, unsure)
