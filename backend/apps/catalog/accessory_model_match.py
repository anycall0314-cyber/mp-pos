"""配件品名 → 相容機型:規則比對。

## 這支在解什麼問題

型錄裡同一台機有兩套寫法:手機主檔寫 `iPhone 15 Pro Max 256GB 黑色鈦金屬 台版 全新`,
配件料號寫 `IMOS/IP15PM/透`。`identity.services._candidate_search` 是逐詞 AND 模糊比對,
跨慣例時候選會是 0 筆——實測 8 句跨慣例的廠商寫法全部撈不到東西。

這裡不做模糊比對,而是把「店內縮寫 → 機型主檔」建成一張查表。

## 縮寫慣例是從真實資料數出來的,不是猜的

數 2953 筆配件品名的斜線片段頻率:

    IP16 37   IP16+ 32   IP16PRO 33   IP16PM 33
    IP15 36   IP15+ 30                IP15PM 38
    IP14 30   IP14+ 35   IP14P  26    IP14PM 29

所以 `+` = Plus、`PRO` = Pro、`PM` = Pro Max。

**`P` 的意思取決於那一代有沒有 Pro**:iPhone 6/7/8 沒有 Pro 機,所以 `IP7P` = 7 Plus;
iPhone 11 之後有 Pro,所以 `IP11P` = 11 Pro。這條不寫死,而是查該租戶主檔裡
有沒有「iPhone N Pro」那一筆來決定——主檔補了新機,判斷自動跟著變。

## 刻意不做的事

- **不做模糊比對**。查表對不到就回「對不到」,交給人或待確認區處理,不硬湊一個像的。
- **不碰 `identity.match_line` 的比對階梯**。這裡只負責把配件的相容機型建起來
  (`ProductRelation`),讓後續比對有東西可對。
- **不判老機**。主檔只收現役機;老配件(HTC/LG/SONY 老機)本來就對不到,
  那是主檔涵蓋範圍的問題,不是比對邏輯的問題。
"""
from __future__ import annotations

import re

# ── 品牌詞:出現在品名裡但不是機型。從真實片段頻率前 70 名挑出來的。
BRAND_TOKENS = set("""
SAM DAP IMOS SONY HTC OPPO ASUS AI膜速箱 太空盾 PG VIVO 華為 LG 小米 INF YESIDO APPLE
GOOGLE BIAZE MOPHIE ANANK TPU MRCOQ JR 通海 橙艾 凱夫拉 BENTEN SHARP NOKIA HONOR REALME
MATTO DEVIA 半 滿 全膠 平板 中古 A.K XIAOMI REDMI MOTO ZTE ACER INFOCUS SUGAR GPLUS
IBACK EARPODS POCO X-LEVEL REMAX NISDA ZGA RPF80 PAD 紅米 ONEPLUS 一加 NILLKIN 犀牛盾 UAG
""".split())

# ── 通用配件:整條品名出現這些就是不對應特定機型的品(線材/充電頭/支架/吊飾)。
GENERIC_RE = re.compile(
    r"旅充|快充|閃充|充電頭|車充|原車充|QC|\bPD\b|USB|TYPE-?C|A轉|C轉|L轉|MICRO|LIGHTNING|"
    r"合一|一拖|拖|MAH|無線充|行動電源|耳機|AIRPODS|藍芽|藍牙|支架|車架|收納|手機鍊|吊飾|"
    r"花球|編織|捲線|矽膠|3\.5MM|共座|DOCK|HUB|轉接|延長|SIM|卡針|清潔|除膠|治具|GLASS|"
    r"膜速箱|UV膜",
    re.I,
)

# ── 顏色 / 表面處理 / 款式 / 規格:是「整個片段」才算,所以用 fullmatch 的形狀。
FINISH_RE = re.compile(
    r"(黑|白|灰|藍|綠|紅|粉|桃|紫|金|銀|透|亮|霧|鑽|藍光|防窺|低藍光|2\.5D|3D|AR|背貼|LCD|副|"
    r"[A-Z]|停售|\d+A\d*C?|\d+A|"
    r"[0-9]+(%|G|GB|TB|W|M|MM|CM|吋|代|寸)|\d+%原|\d+\+\d+G?B?|\d{5,}|\(.*\)|"
    r".*色|.*版|.*面|.*套|.*殼|.*貼|.*膜|框有傷|.*邊框|.*磁吸.*|柔幻.*|荔枝.*|坦克.*|三環|二環|"
    r"極空.*|冰鑽.*|菱格|電鍍.*|浮雕.*|真皮.*|立架.*|筆槽|旋轉筆槽|三折.*|鋁合金|抗反射|"
    r"滿天星.*|防摔.*|超容.*|副廠.*|原廠.*|雙料.*|全透.*|滿版.*|認證電池|指紋解鎖版|大師版|"
    r"人像黑點|LITE|.*糖|.*風|.*星|.*草莓|"
    # 以下是跑 --show-unresolved 從真實殘留撈出來的漏網款式 / 規格詞
    r"電池|抗藍光|WIFI|晶剛|藍寶石|H\.K\.|那盾)",
    re.I,
)

SPLIT_RE = re.compile(r"[/\s]+")


def segments(name: str) -> list[str]:
    """把品名拆成片段(大寫)。斜線與空白都是分隔符。"""
    return [s.strip().upper() for s in SPLIT_RE.split(name or "") if s.strip()]


def resolve_segment(seg: str, index: dict[str, set[int]]) -> set[int] | None:
    """一個片段 → 對到的機型 id;對不到回 None。

    連字號在真實品名裡兩種用法都有,所以兩種都試:
    - 是型號的一部分:`S4-MINI`、`ZF4-PRO`、`PIXEL-8`(抹掉連字號才對得到)
    - 是分隔符:`IP6SP-軟質邊框`、`IP6-4.7-亮`(要拆開才看得到 `IP6SP` / `IP6`)
    """
    for cand in (seg, seg.replace("-", "")):
        hit = index.get(cand)
        if hit:
            return hit
    if "-" in seg:
        ids: set[int] = set()
        for part in seg.split("-"):
            ids |= index.get(part) or set()
        if ids:
            return ids
    return None


def build_index(models) -> dict[str, set[int]]:
    """機型主檔 → {店內縮寫: {機型 id}}。

    `models` 是該租戶的 PhoneModel 可迭代物(至少要有 id / name)。
    一定要先按租戶過濾:機型是 per-tenant 的,不同租戶有同名同 code 的機型,
    不過濾會把別人家的機型混進候選。
    """
    rev: dict[str, set[int]] = {}
    names = {(m.name or "").strip() for m in models}

    def add(key: str, mid: int):
        key = re.sub(r"\s+", "", key).upper()
        if len(key) >= 2:
            rev.setdefault(key, set()).add(mid)

    for m in models:
        n = (m.name or "").strip()

        # iPhone:IP{世代}{後綴}。P 的意思看這一代有沒有 Pro。
        mo = re.match(r"^iPhone\s+(\d{1,2})\s*(Plus|Pro Max|Pro|mini|S Max|S|R|e|Air)?$", n, re.I)
        if mo:
            num = mo.group(1)
            suf = (mo.group(2) or "").strip().lower()
            has_pro = f"iPhone {num} Pro" in names
            codes = {
                "": [""],
                "plus": ["+", "PLUS"] + ([] if has_pro else ["P"]),
                "pro": ["PRO"] + (["P"] if has_pro else []),
                "pro max": ["PM", "PROMAX"],
                "mini": ["MINI"],
                "s": ["S"],
                "r": ["R"],
                "s max": ["SMAX", "XSMAX"],
                "e": ["E"],
                "air": ["AIR"],
            }.get(suf, [])
            for c in codes:
                add(f"IP{num}{c}", m.id)
                add(f"IPHONE{num}{c}", m.id)
                # 一條品名列多款機時,後面幾款常省略 IP 前綴(`IP16E/17E`、`IP13P/13PM`)。
                # 只收「有後綴」的裸寫法:裸數字(`8`、`7`)在品名裡多半是吋數或代數,
                # 收進來會亂對。
                if c:
                    add(f"{num}{c}", m.id)
            # 主檔把 iPhone XS / XR 寫成「iPhone 10 S」/「iPhone 10 R」,店內寫 IPXS / IPXR。
            if num == "10":
                # XS Max 店內有 IPXSMAX 也有簡寫成 IPXSM 的(實測各 5 / 6 次)
                xs = {"s": ["XS"], "r": ["XR"], "": ["X"],
                      "s max": ["XSMAX", "XSM"]}.get(suf, [])
                for x in xs:
                    add(f"IP{x}", m.id)
                    add(x, m.id)

        mo = re.match(r"^iPhone\s+(\d)\s+s\s*(Plus)?$", n, re.I)   # iPhone 6 s / 6 s Plus
        if mo:
            base = f"IP{mo.group(1)}S"
            add(base, m.id)
            if mo.group(2):
                add(base + "+", m.id)
                add(base + "P", m.id)

        mo = re.match(r"^iPhone\s+SE\s*(\d)?$", n, re.I)
        if mo:
            gen = mo.group(1) or ""
            add(f"IPSE{gen}", m.id)
            add(f"SE{gen}", m.id)

        # Galaxy:去空格,U = Ultra,5G 可有可無。
        mo = re.match(r"^Galaxy\s+(.+)$", n, re.I)
        if mo:
            core = re.sub(r"\s+", "", mo.group(1)).upper()
            for v in {
                core,
                core.replace("5G", ""),
                core.replace("ULTRA", "U"),
                core.replace("5G", "").replace("ULTRA", "U"),
                core.replace("ZFLIP", "FLIP"),
                core.replace("ZFOLD", "FOLD"),
                core.replace("PLUS", "+"),
            }:
                add(v, m.id)
                add("GALAXY" + v, m.id)
                add("SAM" + v, m.id)

        # 其他品牌:店內通常把品牌前綴省掉(寫 RENO12 不寫 Reno 12)。
        for pre in ("Pixel", "Reno", "Find", "Zenfone", "Xperia", "realme",
                    "Redmi", "小米", "紅米", "ROG Phone", "iPad"):
            if n.upper().startswith(pre.upper()):
                add(n, m.id)
                add(n[len(pre):], m.id)

        # 主檔裡有些名字沒帶品牌(A 5 Pro / V 40 / X 100 / Y 39),原樣也收一份。
        if re.match(r"^(A|V|X|Y)\s+\d", n):
            add(n, m.id)

    return rev


# 分類結果
MATCHED = "matched"          # 查表對到機型
GENERIC = "generic"          # 通用配件,本來就沒有機型
UNRESOLVED = "unresolved"    # 有看不懂的片段,對不到機型


def classify(name: str, index: dict[str, set[int]]) -> tuple[str, set[int], list[str]]:
    """判一條配件品名。回傳 (分類, 對到的機型 id, 對不到的片段)。

    先擋通用配件:線材/充電頭/支架這類品名裡常有數字型號(`YESIDO/CA205P/1M`),
    不先擋會把它們的廠商料號誤當成機型片段。
    """
    if GENERIC_RE.search(name or ""):
        return GENERIC, set(), []

    ids: set[int] = set()
    unresolved: list[str] = []
    for s in segments(name):
        # 品牌詞先比原樣(X-LEVEL 抹掉連字號就認不出來了)
        if s in BRAND_TOKENS:
            continue
        # 查表擺在款式詞過濾之前:款式那些 `.*` 規則很容易把整段品名吃掉
        # (`.*框.*` 會吃掉 `IP6SP-軟質邊框`,連機型一起沒了)。
        # 對得到機型的片段一律以查表為準,款式規則只處理查不到的。
        hit = resolve_segment(s, index)
        if hit:
            ids |= hit
        elif not FINISH_RE.fullmatch(s):
            unresolved.append(s)

    if ids:
        return MATCHED, ids, unresolved
    if unresolved:
        return UNRESOLVED, set(), unresolved
    return GENERIC, set(), []
