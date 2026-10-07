"""商品叫法比對:把「每個店員各寫各的」拆成同一組特徵再比。

## 這支在解什麼問題

同一款商品會被寫成:

    reno16 皮套 藍色
    reno-16 側翻皮套 藍
    reno16/側翻/藍
    reno16/皮套/側翻藍

舊的候選搜尋是「逐詞 AND icontains」,寫法一換(多個連字號、顏色黏在款式後面、
詞序不同)就 0 筆,店員看到「找不到」就重建一個品號。

## 為什麼從品名拆,而不是比結構化欄位

實測本機 2,922 筆配件:`color` / `phone_model` / `style_code` **全部是空的**。
靠欄位比等於什麼都比不到。所以查詢字串與商品品名走**同一支** `parse_features()`,
兩邊拆出來的特徵再比。同一支函式的好處是拆錯也對稱 —— 兩邊錯得一樣,仍然相等。

## 三種特徵

- `codes`:英數型號(RENO16、IP13PM、S25U)。**必須完全相同**,RENO16 ≠ RENO16PRO。
  有機型主檔時另外用 `accessory_model_match.build_index` 認店內縮寫
  (IP13PM = iPhone 13 Pro Max)。
- `colors`:顏色。藍 = 藍色;深藍 / 淺藍 / 丁香紫 是**另一個顏色**,不消去差異。
- `words`:其餘的字(款式、類別、品牌、規格)。

## 紀律

- 特徵比對只產「候選 + 符合原因 + 差異」,**永遠不替人做決定**。能直接認定
  「就是這個」的只有條碼、廠商料號、已確認別名、品號這些可靠識別。
- 不碰 IMEI,也不拿數字去比品號:那是 `ProductViewSet.get_search_fields`
  的安全閥在管的(「中古 11」不該帶出品號 AA-000011)。
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

# ─────────────────────────── 詞典 ───────────────────────────
# 都是從真實品名的片段頻率挑的,不是憑空想的。

# 顏色:標準字 → 其他寫法
_COLOR_SYNONYMS = {
    "黑": [], "白": [], "藍": [], "灰": [], "粉": ["粉紅"], "銀": [], "綠": [],
    "金": [], "紫": [], "紅": [], "黃": [], "橘": ["橙"], "棕": ["咖啡"],
    "桃": ["桃紅"], "透": ["透明", "全透"],
}
# 帶修飾的顏色自成一色,不等於底色(深藍 ≠ 藍)
_COMPOUND_COLORS = [
    "深藍", "淺藍", "天藍", "寶藍", "深綠", "淺綠", "墨綠", "深灰", "淺灰",
    "透黑", "透白", "透紫", "透藍", "透粉", "亮黑", "霧黑", "霧透", "玫金", "玫瑰金",
]
_COLOR_CANON: dict[str, str] = {}
for _c, _alts in _COLOR_SYNONYMS.items():
    for _form in [_c, *_alts]:
        _COLOR_CANON[_form] = _c
        _COLOR_CANON[_form + "色"] = _c
for _c in _COMPOUND_COLORS:
    _COLOR_CANON[_c] = _c
    _COLOR_CANON[_c + "色"] = _c
_SINGLE_COLORS = set(_COLOR_SYNONYMS)
# 結尾是顏色字但不是顏色的詞
_NOT_COLOR = {"合金", "鋁合金", "鈦合金", "鈦金", "現金"}

# 已知的款式 / 類別 / 規格詞:用來把黏在一起的字切開(側翻皮套 → 側翻 + 皮套、
# 側翻藍 → 側翻 + 藍)。不在這裡的字不會被切,整塊留著比對。
_BASE_TERMS = """
側翻 側掀 皮套 保護殼 手機殼 背蓋 空壓殼 保護貼 玻璃貼 鏡頭貼 背貼 包膜 殼 貼
磁吸 支架 立架 荔枝 防窺 防摔 全膠 滿版 半版 霧面 亮面 抗藍光 低藍光 藍光
柔幻 極光 彈蓋 冰霧 冰鑽 無線 編織 筆槽 旋轉 橫式 直式 空壓 氣墊 軟殼 硬殼
鋼化 類紙膜 光固膜 滿天星 坦克 菱格 電鍍 浮雕 真皮 三折 雙料 認證 電池
原廠 副廠 掛繩 吊飾 晶亮 傳感 收納 掛片 三環 二環 單環 鋁合金 平板 中古
""".split()

# 同一件事的不同寫法 → 標準字
_WORD_SYNONYMS = {
    "側掀": "側翻", "霧面": "霧", "亮面": "亮", "滿版": "滿", "半版": "半",
    "保護殼": "殼", "手機殼": "殼", "抗藍光": "藍光",
}

# 數字後面接這些是規格單位,不是機型後綴(20W 不是機型,15F 才是)
_UNITS = {
    "W", "M", "MM", "CM", "A", "MA", "MAH", "V", "D", "H", "G", "GB", "TB", "T",
    "K", "HZ", "ML", "L", "KG", "X", "IN",
}
_CJK_UNITS = "吋寸代入米片組個條支包"
# 空白隔開時可以接在機型後面的後綴詞(Reno 16 Pro、iPhone 15 Pro Max)
_SUFFIX_WORDS = {"PRO", "MAX", "PLUS", "ULTRA", "MINI", "LITE", "FE", "AIR", "PROMAX"}
_CAPACITY_GB = {"16", "32", "64", "128", "256", "512"}
_CAPACITY_TB = {"1", "2"}

_SEP_SPLIT_RE = re.compile(r"([/\s,、，;；|()\[\]{}<>:：]+)")
_ATOM_RE = re.compile(r"[A-Z]+|\d+(?:\.\d+)?|[一-鿿]+|\+")
_CAP_RE = re.compile(r"(?<![\d.])(\d+)\s*(GB|G|TB|T)(?![A-Z])")
_CAPACITY_TOKEN_RE = re.compile(r"^\d+(GB|TB)$")
_BARE_MODEL_RE = re.compile(r"^(\d{1,3})([A-Z+]{0,5})$")
# 沒寫品牌字首的機型寫法:數字 + 英文後綴(`11PM`、`13P`、`11PROMAX`)。是不是機型由機型主檔決定,這裡只認形狀
_BARE_TOKEN_RE = re.compile(r"^\d{1,3}[A-Z]{1,8}$")
# 用空白隔開打的那一種的開頭:`11`、`11PRO`(後面接 PRO / MAX …)
_BARE_HEAD_RE = re.compile(r"^\d{1,3}(?:%s)?$" % "|".join(sorted(_SUFFIX_WORDS)))
_MODEL_HEAD_RE = re.compile(r"^[A-Z]+\d")
_ALPHA_RE = re.compile(r"^[A-Z]+$")
_CJK_RE = re.compile(r"^[一-鿿]+$")


@dataclass(frozen=True)
class Features:
    """一段文字拆出來的特徵。三個集合互不重疊。"""

    codes: frozenset = frozenset()
    colors: frozenset = frozenset()
    words: frozenset = frozenset()
    # 接續機型留下的裸寫法(RENO15/15F 的「15F」)。只用來滿足查詢,不算商品特徵。
    aux: frozenset = frozenset()
    # 用空白接起來的型號是由哪兩塊接的:(SONY10VI, SONY, 10VI)。
    # 同一個東西有人寫 `SONY 10-VI`、有人寫 `SONY/10-VI`,兩邊要對得起來。
    joined: frozenset = frozenset()
    # 只留中文的原字串,給「沒切出來但字是連著的」做包含比對
    compact: str = ""
    # 沒寫品牌字首的機型寫法:(寫法, 它在 words 裡是哪幾個字)。
    #   `11PM` → ("11PM", ("11PM",));`11 PRO MAX` → ("11PROMAX", ("11", "PRO", "MAX"));`16+` → ("16+", ("16",))
    # **words 完全不變**(這些字照樣在 words 裡,照字面比對的路跟以前一模一樣);
    # 多記這一份只是讓比對去問機型主檔:主檔認得、而且就是商品的機型,才算機型對上。
    bare: frozenset = frozenset()

    @property
    def empty(self) -> bool:
        return not (self.codes or self.colors or self.words)

    @property
    def size(self) -> int:
        return len(self.codes) + len(self.colors) + len(self.words)

    @property
    def kinds(self) -> int:
        """有幾「種」特徵。只有一種(只寫機型 / 只寫顏色)算太籠統的叫法。"""
        return sum(1 for s in (self.codes, self.colors, self.words) if s)


def has_capacity(features: "Features") -> bool:
    """這段文字有沒有寫容量(256GB、1TB)。手機 / 平板的品號一定有;皮套、保護貼這些配件沒有。"""
    return any(_CAPACITY_TOKEN_RE.match(w) for w in features.words)


def _norm_capacity(m: re.Match) -> str:
    num, unit = m.group(1), m.group(2)
    if unit in ("GB", "G") and num in _CAPACITY_GB:
        return f"{num}GB"
    if unit in ("TB", "T") and num in _CAPACITY_TB:
        return f"{num}TB"
    return m.group(0)


def _join_hyphens(s: str) -> str:
    """連字號:型號裡的抹掉(RENO-16、S4-MINI、TYPE-C),其餘當分隔。

    左右都是數字(IP6-4.7)是分隔;碰到中文(IP6SP-軟質邊框)也是分隔。
    """
    out = []
    for i, ch in enumerate(s):
        if ch not in "-_":
            out.append(ch)
            continue
        left = s[i - 1] if i > 0 else ""
        right = s[i + 1] if i + 1 < len(s) else ""
        both_alnum = (
            left.isascii() and left.isalnum() and right.isascii() and right.isalnum()
        )
        if both_alnum and not (left.isdigit() and right.isdigit()):
            continue
        out.append(" ")
    return "".join(out)


def _join_spaced_models(segments: list[str], separators: list[str]):
    """把用空白隔開的機型接回去:`RENO 16 PRO` → `RENO16PRO`。

    只接空白,不接斜線:斜線在店內品名是欄位分隔(`IPAD/PRO/11吋`)。
    separators[i] 是 segments[i] 後面的分隔符。
    回傳 (接好的片段, {接好的片段: (前半, 後半)})。
    """
    out: list[str] = []
    parts: dict[str, tuple[str, str]] = {}
    i = 0
    while i < len(segments):
        seg = segments[i]
        head = ""
        if _ALPHA_RE.match(seg) and i + 1 < len(segments) and separators[i] == " ":
            m = _BARE_MODEL_RE.match(segments[i + 1])
            if m and m.group(2) not in _UNITS:
                head = seg
                seg += segments[i + 1]
                i += 1
        # 後綴詞(PRO / MAX …)接在已經是型號的片段後面
        while (
            _MODEL_HEAD_RE.match(seg)
            and i + 1 < len(segments)
            and separators[i] == " "
            and segments[i + 1] in _SUFFIX_WORDS
        ):
            seg += segments[i + 1]
            i += 1
        if head:
            parts[seg] = (head, seg[len(head):])
        out.append(seg)
        i += 1
    return out, parts


def _spaced_bare(segments: list[str], separators: list[str]) -> list[tuple[str, tuple]]:
    """用空白隔開打的沒字首機型:`11 PRO MAX`、`13 PRO` → [("11PROMAX", ("11", "PRO", "MAX"))]。

    只看、不改 segments(那幾塊照樣各自是一個字)。前面有英文字首的(`RENO 16 PRO`、`DAP 13 PRO`)
    會被 `_join_spaced_models` 接成一個型號、那幾塊不再是 words 裡的字 —— 由呼叫的地方濾掉。
    """
    out = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        if _BARE_HEAD_RE.match(seg):
            pieces = [seg]
            j = i
            while (
                j + 1 < len(segments)
                and separators[j] == " "
                and segments[j + 1] in _SUFFIX_WORDS
            ):
                pieces.append(segments[j + 1])
                j += 1
            if len(pieces) > 1:
                out.append(("".join(pieces), tuple(pieces)))
                i = j
        i += 1
    return out


def _segment(run: str, terms: frozenset) -> list[str]:
    """照詞典做最長比對切詞;不認得的字連在一起當一塊。"""
    out: list[str] = []
    unknown = ""
    i = 0
    max_len = max((len(t) for t in terms), default=1)
    while i < len(run):
        hit = ""
        for n in range(min(max_len, len(run) - i), 1, -1):
            if run[i:i + n] in terms:
                hit = run[i:i + n]
                break
        # 單字詞(殼、貼)只在片段結尾才認,否則會把別的詞切碎
        if not hit and i == len(run) - 1 and run[i] in terms:
            hit = run[i]
        if hit:
            if unknown:
                out.append(unknown)
                unknown = ""
            out.append(hit)
            i += len(hit)
        else:
            unknown += run[i]
            i += 1
    if unknown:
        out.append(unknown)
    return out


def _split_cjk(run: str, terms: frozenset) -> tuple[list[str], list[str]]:
    """一段中文 → (顏色, 其他詞)。

    先照詞典切開,再看切出來的每一塊是不是顏色。「側翻藍」會被已知詞「側翻」
    切成 側翻 + 藍;「丁香紫」「天空藍」前面沒有認得的詞、整塊留著,就當成
    **另一個顏色**,不等於紫 / 藍。

    單一個顏色字只有被已知詞或片段邊界夾住才會獨立成一塊,所以 紅米、黑鯊、
    藍牙、金屬 這些開頭帶顏色字的詞不會被誤拆。
    """
    colors: list[str] = []
    words: list[str] = []
    for part in _segment(run, terms):
        bare = part[:-1] if part.endswith("色") and len(part) > 1 else part
        if part in _COLOR_CANON:
            colors.append(_COLOR_CANON[part])
        elif (
            len(bare) >= 2
            and part not in terms
            and bare not in _NOT_COLOR
            and bare[-1] in _SINGLE_COLORS
        ):
            colors.append(bare)  # 帶修飾的顏色(丁香紫、象牙白)
        else:
            words.append(part)
    return colors, words


@lru_cache(maxsize=50000)
def _parse(text: str, terms: frozenset) -> Features:
    s = unicodedata.normalize("NFKC", text or "").upper()
    s = _CAP_RE.sub(_norm_capacity, s)
    s = _join_hyphens(s)

    segments: list[str] = []
    separators: list[str] = []
    pieces = _SEP_SPLIT_RE.split(s)
    for k in range(0, len(pieces), 2):
        if not pieces[k]:
            continue
        sep = pieces[k + 1] if k + 1 < len(pieces) else ""
        segments.append(pieces[k])
        separators.append("" if not sep else (" " if not sep.strip() else "/"))
    spaced_bare = _spaced_bare(segments, separators)
    segments, joined_parts = _join_spaced_models(segments, separators)

    codes: set[str] = set()
    colors: set[str] = set()
    words: set[str] = set()
    aux: set[str] = set()
    bare_writings: set[tuple] = set()   # 沒字首的機型寫法(見 Features.bare)
    cjk_parts: list[str] = []
    prev_prefix = ""  # 上一個片段的型號字首(RENO15/15F 的 15F 要補回 RENO)

    for seg in segments:
        atoms = _ATOM_RE.findall(seg)
        if not atoms:
            continue

        # 省略字首的接續機型:RENO15/15F、IP13P/13PM、IP7/8
        bare = _BARE_MODEL_RE.match(seg)
        if bare and prev_prefix and bare.group(2) not in _UNITS:
            codes.add(prev_prefix + seg)
            aux.add(seg)
            continue

        seg_prefix = ""
        i = 0
        while i < len(atoms):
            a = atoms[i]
            nxt = atoms[i + 1] if i + 1 < len(atoms) else ""
            if _ALPHA_RE.match(a) and nxt and nxt[0].isdigit():
                # 英文 + 數字 = 型號;後面黏著的英文 / + 也算進去(13PM、10P+)
                code = a + nxt
                j = i + 2
                while j < len(atoms) and (atoms[j] == "+" or _ALPHA_RE.match(atoms[j])):
                    code += atoms[j]
                    j += 1
                codes.add(code)
                seg_prefix = seg_prefix or a
                i = j
            elif a[0].isdigit():
                if nxt and _ALPHA_RE.match(nxt):
                    words.add(a + nxt)  # 規格(20W、128GB)或沒字首的型號(10C)
                    if nxt not in _UNITS and _BARE_TOKEN_RE.match(a + nxt):
                        bare_writings.add((a + nxt, (a + nxt,)))
                    i += 2
                elif nxt == "+" and a.isdigit() and len(a) <= 3:
                    words.add(a)  # 跟以前一樣只留數字
                    bare_writings.add((a + "+", (a,)))  # 16+ = 16 Plus
                    i += 2
                elif nxt and _CJK_RE.match(nxt) and nxt[0] in _CJK_UNITS:
                    words.add(a + nxt[0])  # 11吋、3代
                    rest = nxt[1:]
                    if rest:
                        c, w = _split_cjk(rest, terms)
                        colors.update(c)
                        words.update(w)
                        cjk_parts.append(rest)
                    i += 2
                else:
                    words.add(a)
                    i += 1
            elif _CJK_RE.match(a):
                c, w = _split_cjk(a, terms)
                colors.update(c)
                words.update(w)
                cjk_parts.append(a)
                i += 1
            elif a == "+":
                i += 1
            else:
                words.add(a)
                i += 1
        prev_prefix = seg_prefix

    words = {_WORD_SYNONYMS.get(w, w) for w in words}
    joined = {(c, *joined_parts[c]) for c in codes if c in joined_parts}
    for _, head, rest in joined:
        aux.update((head, rest))
    # 空白隔開的那一種:每一塊都真的是 words 裡的字才算;`11PRO MAX` 講的是 11 Pro Max,不再另外當成 11PRO
    for token, pieces in spaced_bare:
        if all(piece in words for piece in pieces):
            bare_writings.discard((pieces[0], (pieces[0],)))
            bare_writings.add((token, pieces))
    return Features(
        codes=frozenset(codes),
        colors=frozenset(colors),
        words=frozenset(words - colors),
        aux=frozenset(aux - codes - words),
        joined=frozenset(joined),
        compact="".join(cjk_parts),
        bare=frozenset(bare_writings),
    )


_DEFAULT_TERMS = frozenset(_BASE_TERMS)


def build_terms(category_names=()) -> frozenset:
    """詞典 = 內建款式詞 + 這個租戶自己的類別名稱(沿用類別主檔)。"""
    extra = set()
    for name in category_names:
        for part in re.split(r"[/\s]+", unicodedata.normalize("NFKC", name or "")):
            if len(part) >= 2 and _CJK_RE.match(part):
                extra.add(part)
    return frozenset(_DEFAULT_TERMS | extra) if extra else _DEFAULT_TERMS


def parse_features(text: str, terms: frozenset = _DEFAULT_TERMS) -> Features:
    """一段文字(查詢或品名)→ 特徵。查詢端與商品端一定要用同一份 terms。"""
    return _parse(text or "", terms)


def is_broad_phrase(text: str, terms: frozenset = _DEFAULT_TERMS) -> bool:
    """太籠統、不能學成「唯一別名」的叫法:只寫機型、只寫類別、只寫顏色。

    `reno16`、`皮套`、`藍` 都指到一大票商品。學成單一商品的別名後,下次打
    同樣的字會被直接帶到那一筆,其他款反而找不到。
    """
    f = parse_features(text, terms)
    return f.kinds <= 1


# ─────────────────────────── 比對 ───────────────────────────
IDENTIFIER = "identifier"  # 條碼 / 廠商料號 / 已確認別名 / 品號 —— 可靠識別
EXACT = "exact"            # 特徵完全一樣
COVERS = "covers"          # 輸入的都對得上,但商品還有輸入沒講到的特徵(資訊不足)
SUBSET = "subset"          # 反過來:既有商品的特徵都在輸入裡,輸入講得比較細
RELATED = "related"        # 機型相同但有特徵不同 / 對不上,要標明差異
_LEVEL_RANK = {IDENTIFIER: 0, EXACT: 1, COVERS: 2, SUBSET: 3, RELATED: 4}
# 「可能是同一款」:兩邊的特徵一邊包含另一邊、沒有任何明確不同
SAME_ITEM_LEVELS = (IDENTIFIER, EXACT, COVERS, SUBSET)


@dataclass
class Verdict:
    level: str
    score: int
    reasons: list = field(default_factory=list)
    differences: list = field(default_factory=list)
    # 有「明確不同」(顏色不同、容量不同),不只是缺資訊
    conflict: bool = False
    # 這個結果可能用到了「沒字首的機型寫法 / 單獨數字」(2026-10-07 加的認法;寧可多標)。
    # False = 一定跟以前一樣。True 不代表以前沒有這個結果(那幾個字可能照字面也對得上);
    # 要知道以前是什麼,用 `compare(..., plain=True)` 再比一次。
    via_new: bool = False

    def sort_key(self):
        return (_LEVEL_RANK[self.level], -self.score)


def _join(items) -> str:
    return "、".join(sorted(items))


def _no_ids(code):
    return frozenset()


def compare(q: Features, p: Features, *, soft=frozenset(), model_ids=_no_ids,
            linked_ids=frozenset(), plain=False, named_elsewhere=False) -> Verdict | None:
    """查詢特徵對一個商品的特徵。回 None = 不算候選。

    soft:商品的背景詞(類別名稱)。可以滿足查詢,但不算商品多出來的特徵。
    model_ids:型號字串 → 機型主檔 id 集合(認店內縮寫用);查不到回空集合。
    linked_ids:這個商品透過相容關係 / 機型欄位掛到的機型 id。
    plain:不認「沒字首的機型寫法 / 單獨數字」—— 就是 2026-10-07 之前的比法。
          防重複的對稱比對用它回答「這個結果以前有沒有」(見 `MatchContext.scan`)。
    named_elsewhere:`p` 是這個商品的其他叫法,而商品的主品名已經寫了型號 ——
          不能再從這個短的叫法替商品猜機型(主品名 `GOOGLE/PIXEL11PRO/電池`、叫法 `11PRO/電池`:11PRO 是 Pixel 的)。

    沒寫品牌字首的機型寫法(`11PM`、`11 pro max`、`DAP 13P`、單獨一個數字)—— 2026-10-07 加的,原則只有一條:
    **只會多對上,不會讓原本找得到的變成找不到**。主檔認得、而且就是這個商品的機型才算機型對上;
    其他情況那些字照原本當一般的字比(沒有機型主檔的公司因此完全不變)。
    """
    if q.empty:
        return None

    p_ids = frozenset(linked_ids)
    for c in p.codes:
        p_ids |= model_ids(c)
    # 品名裡沒寫字首的機型(`11PRO/認證電池`):機型主檔認得的,也算這個商品的機型。
    # 只在品名沒有寫別的型號時才這樣算:`11PRO` 可以是 iPhone 也可以是 Pixel,
    # `GOOGLE/PIXEL-11/11PRO黑` 已經寫了 PIXEL11(就算機型主檔還沒有這一支),就不把 11PRO 當成 iPhone 11 Pro。
    # 實測 3003 個真的品名,有這種寫法的 9 個:沒有別的型號的 6 個都對;有別的型號的 3 個裡 2 個會猜錯。寧可不猜。
    # 而且不能把商品的機型「擴大」:`11PRO` 在主檔裡同時是 iPhone 11 Pro 與 Pixel 11 Pro 時 ——
    # 商品已經指定機型(相容關係 / 機型欄位)的,只認其中指定的那一個;沒指定的就分不出來,不猜。
    p_bare: dict = {}
    if not p.codes and not plain and not named_elsewhere:
        for token, pieces in p.bare:
            ids = model_ids(token)
            if linked_ids:
                ids = ids & frozenset(linked_ids)
            elif len(ids) != 1:
                ids = frozenset()
            if ids:
                p_bare[token] = (ids, pieces)
                p_ids |= ids

    def named_in_product(ids) -> bool:
        """這個機型是品名自己寫的(不管哪一種寫法),不是靠「相容機型」關係掛上去的。"""
        return any(ids & model_ids(pc) for pc in p.codes) or any(
            ids & pids for pids, _ in p_bare.values()
        )

    q_ids = frozenset()
    q_parts = {c: (head, rest) for c, head, rest in q.joined}
    p_loose = p.words | p.aux
    hit_codes, miss_codes = set(), set()
    by_relation = False
    # 沒字首的寫法對上機型的:named = 寫了後綴的(11PM、13P);numbers = 只有數字(12),線索很弱
    named: set = set()
    numbers: set = set()
    # 用空白接起來的「型號」其實是「品牌 + 沒字首的機型」(`DAP 13P` 被接成 DAP13P):
    # 機型主檔不認得接起來的那一串、**而後半就是這個商品的機型** → 拆回一個字(DAP)加一個對上的機型(13P)。
    # 後半只有數字(`DAP 12`)時只當成 iPhone 那一代(弱線索,算進 numbers),而且多要一個條件:前半那個字在這個商品的品名裡。
    # 不是這個商品的機型就照原本的:這個型號沒對上。
    split_words: set = set()
    for c in q.codes:
        ids = model_ids(c)
        q_ids |= ids
        if c in p.codes or (c in q_parts and set(q_parts[c]) <= p_loose):
            hit_codes.add(c)
        elif ids and ids & p_ids:
            hit_codes.add(c)
            by_relation = by_relation or not named_in_product(ids)
        else:
            rest_ids, into = frozenset(), named
            if not ids and c in q_parts and not plain:
                head, rest = q_parts[c]
                if not rest.isdigit():
                    rest_ids = model_ids(rest)
                elif head in p_loose:
                    # 純數字不查主檔裡別牌的「12」(Reno 12、小米 12 都會登記成 12):那樣就變成有把握的對上了
                    rest_ids, into = model_ids("IP" + rest), numbers
            if rest_ids & p_ids:
                split_words.add(q_parts[c][0])
                into.add(q_parts[c][1])
                q_ids |= rest_ids
                by_relation = by_relation or not named_in_product(rest_ids)
            else:
                miss_codes.add(c)
    # 講了型號卻一個都對不上 → 不是同一款的候選(Reno16 不該帶出 Reno16 Pro)
    if q.codes and not (hit_codes or named or numbers):
        return None

    hit_colors = q.colors & p.colors
    miss_colors = q.colors - p.colors

    p_words = p.words | p.aux | soft
    q_words = q.words | split_words
    consumed: set = set()   # 已經當機型對上的那幾個字(下面不再當一般的字比一次)
    reserved: set = set()   # 屬於某個沒字首寫法的字(`11 PRO MAX` 的 11、`16+` 的 16):不能再被當成單獨一個數字
    for token, pieces in (() if plain else q.bare):
        reserved.update(pieces)
        ids = model_ids(token)
        if ids & p_ids:
            named.add(token)
            consumed.update(pieces)
            q_ids |= ids
            by_relation = by_relation or not named_in_product(ids)
    # 單獨一個數字(`犀牛盾 12 黑` 的 12):品名照字面沒有這個數字、而它剛好是這個商品的 iPhone 世代
    for w in (() if plain else q.words):
        if w.isdigit() and len(w) <= 2 and w not in p_words and w not in reserved:
            ids = model_ids("IP" + w)
            if ids & p_ids:
                numbers.add(w)
                consumed.add(w)
                q_ids |= ids
                by_relation = by_relation or not named_in_product(ids)

    hit_words, miss_words = set(), set()
    for w in q_words:
        if w in consumed:
            continue
        if w in p_words or (len(w) >= 2 and _CJK_RE.match(w) and w in p.compact):
            hit_words.add(w)
        else:
            miss_words.add(w)

    matched = len(hit_codes) + len(named) + len(numbers) + len(hit_colors) + len(hit_words)
    if not matched:
        return None

    # 有沒有「講明的機型」對上。只靠單獨一個數字的不算(數字太容易是別的意思)
    model_named = bool(hit_codes or named)
    # 寧可多標:品名那一邊認出沒字首的機型(p_bare)也算,它會讓有字首的型號對上、讓多出來的字變少
    via_new = bool(named or numbers or p_bare)
    reasons, differences = [], []
    if model_named:
        # 品名裡沒寫這個型號,是靠「相容機型」關係對上的,要講清楚
        reasons.append("相容機型相符" if by_relation else "機型相符")
    if numbers:
        reasons.append(f"數字 {_join(numbers)} 對上機型")
    if hit_colors:
        reasons.append("顏色相符")
    if hit_words:
        reasons.append(f"{_join(hit_words)} 相符")

    conflict = False
    if miss_codes:
        differences.append(f"機型對不上:{_join(miss_codes)}")
    if miss_colors:
        if p.colors:
            conflict = True
            differences.append(
                f"顏色不同(輸入 {_join(miss_colors)} / 商品 {_join(p.colors)})"
            )
        else:
            differences.append(f"商品沒寫顏色(輸入 {_join(miss_colors)})")
    q_caps = {w for w in miss_words if _CAPACITY_TOKEN_RE.match(w)}
    p_caps = {w for w in p.words if _CAPACITY_TOKEN_RE.match(w)}
    if q_caps and p_caps:
        conflict = True
        differences.append(f"容量不同(輸入 {_join(q_caps)} / 商品 {_join(p_caps)})")
        miss_words -= q_caps
    if miss_words:
        differences.append(f"商品沒有:{_join(miss_words)}")
    # 只要有哪一個機型是靠單獨一個數字認出來的:最多列為「相關」、講清楚是把數字當成機型比的 ——
    # 不能變成「同一款」(那會讓防重複擋錯:`某牌/保護貼/12` 的 12 可能是 12 片,不是 iPhone 12)。
    # 旁邊另外有講明的機型對上也一樣:那不能證明這個數字也是機型(`某牌/IP11PM/保護貼/12`)。
    if numbers:
        differences.append(f"只寫了數字 {_join(numbers)},當成 iPhone {_join(numbers)} 來比")

    if differences:
        # 沒講型號時,至少要對上兩項且過半,才值得拿出來當「相關」
        if not model_named and (matched < 2 or matched * 2 < q.size):
            return None
        score = max(40, 70 - 6 * len(differences))
        if numbers:
            score += 10     # 比「同品牌、別的機型」那種相關排前面
        return Verdict(RELATED, score, reasons, differences, conflict, via_new)

    # 商品自己的特徵裡,輸入沒講到的部分
    # 一邊用空白接成型號、另一邊用斜線分開寫的,兩塊都對上了就不算多出來
    q_loose = q.words | q.aux
    p_parts = {c: {head, rest} for c, head, rest in p.joined}
    via_parts = set()
    for c in hit_codes:
        via_parts.update(q_parts.get(c, ()))
    extra_codes = {
        c for c in p.codes
        if c not in q.codes
        and not (model_ids(c) and model_ids(c) & q_ids)
        and not (c in p_parts and p_parts[c] <= q_loose)
    }
    # 品名裡沒字首的機型,輸入用別的寫法講到了(`11PRO` 對 `iPhone 11 Pro`)→ 那幾個字不算商品多出來的
    same_model = set()
    for ids, pieces in p_bare.values():
        if ids & q_ids:
            same_model.update(pieces)
    extras = (
        extra_codes
        | (p.colors - q.colors)
        | (p.words - q_words - soft - via_parts - same_model)
    )
    if not extras:
        return Verdict(EXACT, 96, reasons, [], False, via_new)
    return Verdict(
        COVERS, max(85, 93 - 2 * len(extras)), reasons,
        [f"商品另有:{_join(extras)}"], False, via_new,
    )


# ─────────────────────────── 查資料庫 ───────────────────────────
@dataclass
class Candidate:
    product_id: int
    level: str
    score: int
    reasons: list
    differences: list
    conflict: bool
    is_active: bool
    sku: str = ""


@dataclass
class MatchResult:
    """`existing` 只會來自可靠識別;特徵比對再像也只是 `candidates`。"""

    EXISTING = "existing"
    CANDIDATES = "candidates"
    CONFLICT = "conflict"
    NONE = "none"

    status: str
    candidates: list

    @property
    def product_ids(self) -> list:
        return [c.product_id for c in self.candidates]


_NAME_ALIAS_KINDS = ("vendor_name", "legacy_name", "oem_model")
_REASON_NAME_ALIAS = "已確認的其他叫法"


def identifier_hits(tenant, text, supplier=None, barcode="", vendor_sku=""):
    """條碼 / 廠商料號 / 已確認別名 / 品號。回 {product_id: [原因]}。

    每一類都把**所有**命中的商品收進來,不 `.first()` 任選:兩個來源指到不同
    商品時要讓人看到衝突,而不是靜默挑一個。
    """
    from apps.catalog.models import Product, SupplierProduct

    from .models import ProductAlias
    from .normalize import alias_key

    hits: dict[int, list[str]] = defaultdict(list)
    products = Product.objects.for_tenant(tenant)
    aliases = ProductAlias.objects.for_tenant(tenant).filter(is_active=True, verified=True)

    text = (text or "").strip()
    barcode = (barcode or "").strip()
    # 搜尋框直接掃條碼的情況:整串都是數字且夠長,也當條碼查
    barcodes = {b for b in (barcode, text if text.isdigit() and len(text) >= 8 else "") if b}
    for b in barcodes:
        for pid in products.filter(barcode=b).values_list("id", flat=True):
            hits[pid].append("條碼相符")
        for pid in aliases.filter(
            kind=ProductAlias.Kind.BARCODE, normalized_value=alias_key(b)
        ).values_list("product_id", flat=True):
            hits[pid].append("條碼相符(已確認的對應)")

    vkey = alias_key(vendor_sku)
    if vkey:
        skus = aliases.filter(kind=ProductAlias.Kind.VENDOR_SKU, normalized_value=vkey)
        own = (
            list(skus.filter(supplier=supplier).values_list("product_id", flat=True))
            if supplier is not None else []
        )
        # 這家廠商自己的料號優先;沒有才看不分廠商的
        for pid in own or skus.filter(supplier__isnull=True).values_list(
            "product_id", flat=True
        ):
            hits[pid].append("廠商料號相符")
        if supplier is not None:
            for pid in SupplierProduct.objects.for_tenant(tenant).filter(
                is_active=True, supplier=supplier, vendor_sku_key=vkey
            ).values_list("product_id", flat=True):
                hits[pid].append("廠商料號相符(上次進貨來源)")

    tkey = alias_key(text)
    if tkey:
        named = aliases.filter(kind__in=_NAME_ALIAS_KINDS, normalized_value=tkey)
        own = list(named.filter(supplier=supplier).values_list("product_id", flat=True)) \
            if supplier is not None else []
        # 這家廠商自己的叫法優先於通用叫法;都沒有才看通用
        for pid in own or named.filter(supplier__isnull=True).values_list(
            "product_id", flat=True
        ):
            hits[pid].append(_REASON_NAME_ALIAS)
        for pid in products.filter(sku__iexact=text).values_list("id", flat=True):
            hits[pid].append("品號相符")
    return hits


def _wants_reverse(v) -> bool:
    """防重複的對稱比對:正向是這種結果時,要不要再反過來比一次(既有商品的特徵是不是都在這個品名裡)。"""
    return v is None or (v.level == RELATED and not v.conflict)


class MatchContext:
    """一個租戶的比對資料:詞典、機型縮寫索引、每個商品拆好的特徵。

    一次查詢建一份就好;批次入口(匯入、型號展開)整批共用同一份,
    不然每一列都重讀一次全部商品,一千列就是一千次全表掃描。
    批次途中新建的商品用 `add()` 補進來,後面的列才看得到它。
    """

    def __init__(self, tenant, supplier=None):
        from apps.catalog.accessory_model_match import build_index
        from apps.catalog.models import Category, PhoneModel, Product, ProductRelation
        from django.db.models import Q

        from .models import ProductAlias

        self.tenant = tenant
        self.terms = build_terms(
            Category.objects.for_tenant(tenant).values_list("name", flat=True)
        )
        index = build_index(
            list(PhoneModel.objects.for_tenant(tenant).only("id", "name"))
        )
        self._model_ids = lru_cache(maxsize=None)(
            lambda code: frozenset(index.get(code) or ())
        )

        linked: dict[int, set] = defaultdict(set)
        for pid, mid in ProductRelation.objects.for_tenant(tenant).filter(
            host_model__isnull=False
        ).values_list("accessory_product_id", "host_model_id"):
            linked[pid].add(mid)

        alt_names: dict[int, list] = defaultdict(list)
        alias_qs = ProductAlias.objects.for_tenant(tenant).filter(
            is_active=True, kind__in=_NAME_ALIAS_KINDS
        )
        if supplier is not None:
            alias_qs = alias_qs.filter(Q(supplier__isnull=True) | Q(supplier=supplier))
        else:
            alias_qs = alias_qs.filter(supplier__isnull=True)
        for pid, value in alias_qs.values_list("product_id", "value"):
            alt_names[pid].append(value)

        self.rows = []
        self._row_at: dict[int, int] = {}   # 商品編號 → 它在 rows 的第幾列
        for pid, sku, name, spec, color, capacity, cat, active, pm_id, used in (
            Product.objects.for_tenant(tenant).values_list(
                "id", "sku", "name", "spec", "color", "capacity", "category__name",
                "is_active", "phone_model_id", "is_secondhand",
            ).iterator()
        ):
            self._append(
                pid, sku, name, spec, color, capacity, cat, active, used,
                frozenset(linked.get(pid, ())) | ({pm_id} if pm_id else frozenset()),
                alt_names.get(pid, ()),
            )

    def _append(self, pid, sku, name, spec, color, capacity, cat, active, used,
                linked_ids=frozenset(), alts=()):
        own = " ".join(x for x in (name, spec, color, capacity) if x)
        soft = parse_features(cat or "", self.terms).words | {cat or ""}
        self._row_at[pid] = len(self.rows)
        self.rows.append((
            pid, sku, active, used, parse_features(own, self.terms), soft, linked_ids,
            [(alt, parse_features(alt, self.terms)) for alt in alts],
        ))

    def states_capacity(self, product_id) -> bool:
        """這個商品有沒有寫容量:它自己的品名 / 規格 / 容量欄,**或它任何一個其他叫法** —— 比對看的就是這幾份。

        只看商品自己的欄位不夠:品名寫 `iPhone 17 256 黑色`(容量認不出來)、另外登記了一個叫法
        `iPhone 17 256GB 黑色 台版 全新` 的手機,是靠那個叫法對上的;它有寫容量。
        """
        _, _, _, _, mine, _, _, alts = self.rows[self._row_at[product_id]]
        return has_capacity(mine) or any(has_capacity(feats) for _, feats in alts)

    def add_planned(self, fake_id, name, is_secondhand=False):
        """預覽用:還沒真的建出來、但同一批後面的列要看得到的那一筆。"""
        self._append(fake_id, "", name, "", "", "", "", True, is_secondhand)

    def add(self, product):
        """批次途中新建的商品。"""
        self._append(
            product.id, product.sku, product.name, product.spec, product.color,
            product.capacity, product.category.name, product.is_active,
            product.is_secondhand,
        )

    def _forward(self, q, mine, soft, linked_ids, alts, plain=False):
        """查詢對一個商品(品名本身 + 它的其他叫法)最好的那個結果。"""
        best = compare(q, mine, soft=soft, model_ids=self._model_ids,
                       linked_ids=linked_ids, plain=plain)
        for alt, feats in alts:
            v = compare(q, feats, soft=soft, model_ids=self._model_ids,
                        linked_ids=linked_ids, plain=plain,
                        named_elsewhere=bool(mine.codes))
            if v is not None and (best is None or v.sort_key() < best.sort_key()):
                v.reasons = [f"其他叫法「{alt}」"] + v.reasons
                best = v
        return best

    def scan(self, text, *, is_secondhand=None, with_related=True, symmetric=False,
             limit=20, exclude_id=None):
        q = parse_features(text, self.terms)
        if q.empty:
            return []
        found: list[Candidate] = []
        for pid, sku, active, used, mine, soft, linked_ids, alts in self.rows:
            if pid == exclude_id:
                continue
            if is_secondhand is not None and used != is_secondhand:
                continue
            best = self._forward(q, mine, soft, linked_ids, alts)
            # 防重複的對稱比對:正向沒有結果、或只是「資訊不足的相關」時,反過來再比一次 ——
            # 既有商品的特徵都在這個品名裡,就是同一款(SUBSET)。正向是「相關、而且有明確不同」的不做(那是兩個不同的東西)。
            #
            # 新認得的寫法不能改掉這裡以前的結論,兩個方向都要守住:
            # (1) 以前靠反向成立的同一款不能不見:正向現在因為新認法冒出一個「相關(明確不同)」時,照樣去看反向 ——
            #     但只認**以前的比法**(plain)就成立的反向,不能用新認法在反向再多認一次
            #     (`11PM/透/黑` 對 `IP11PM/黑`:寫成 `IP11PM/透/黑` 時明明是顏色不同的兩個東西)。
            # (2) 以前不是同一款的不能變成同一款:要升成同一款之前,**以前的正向**也必須是會做反向比對的那一種
            #     (主品名顏色明確不同、現在只是被某個其他叫法的結果蓋過去的,不能升)。
            if symmetric and (
                _wants_reverse(best) or (best.level == RELATED and best.via_new)
            ):
                # 既有商品本身太籠統就不算,不然什麼新品都會被它擋:
                # 只叫「皮套」,或新品有寫機型而它沒有(「皮套 藍」對上
                # 「Reno16 側翻皮套 藍」)—— 少了機型,它不是同一款的舊寫法。
                generic = mine.kinds < 2 or (q.codes and not mine.codes)
                differs_now = best is not None and best.conflict
                back = None if generic else compare(
                    mine, q, model_ids=self._model_ids, plain=differs_now,
                )
                if back is not None and back.level in (EXACT, COVERS):
                    # 現在沒有正向結果的,以前也沒有(新認法只會多對上);用不到新認法的,以前就是這個結果
                    before = best
                    if best is not None and best.via_new:
                        before = self._forward(q, mine, soft, linked_ids, alts, plain=True)
                    if _wants_reverse(before):
                        best = Verdict(
                            SUBSET, 88, ["既有商品的特徵都在這個品名裡"],
                            [d.replace("商品另有", "這個品名多了") for d in back.differences],
                            False,
                        )
            if best is None or (best.level == RELATED and not with_related):
                continue
            found.append(Candidate(pid, best.level, best.score, best.reasons,
                                   best.differences, best.conflict, active, sku))
        found.sort(key=lambda c: (_LEVEL_RANK[c.level], -c.score, not c.is_active, c.sku))
        return found[:limit] if limit else found


def find_candidates(tenant, text="", *, supplier=None, barcode="", vendor_sku="",
                    is_secondhand=None, limit=20, with_related=True,
                    symmetric=False, context=None) -> MatchResult:
    """一段叫法 → 這個租戶裡可能是它的既有商品。

    零庫存與停用的商品**都會**被找出來:零庫存不代表沒建檔;賣完被停用、
    過一陣子再進貨是常態。能不能選用由各入口自己決定,這裡只負責找。

    `symmetric`:新增商品前查重用。搜尋時「輸入比商品講得細」只算相關
    (打了側翻,商品沒寫側翻);但建檔時那正是重複的樣子 —— 前一個人建了
    `Reno16 皮套 藍`,下一個人要建 `Reno16 側翻皮套 藍`。所以查重要兩個方向都看。
    """
    from apps.catalog.models import Product

    # ① 可靠識別
    hits = identifier_hits(tenant, text, supplier, barcode, vendor_sku)
    if hits:
        products = Product.objects.for_tenant(tenant)
        if is_secondhand is not None:
            products = products.filter(is_secondhand=is_secondhand)
        rows = {
            r[0]: r for r in products.filter(id__in=list(hits)).values_list(
                "id", "sku", "is_active"
            )
        }
        found = [
            Candidate(pid, IDENTIFIER, 100, sorted(set(reasons)), [], False,
                      rows[pid][2], rows[pid][1])
            for pid, reasons in hits.items() if pid in rows
        ]
        if len(found) == 1:
            only = found[0]
            if only.reasons == [_REASON_NAME_ALIAS] and (text or "").strip():
                # 「叫法」跟條碼不一樣,它是當時確認的、之後可能失效:記下「reno16 藍」
                # 時店裡只有側翻款,後來進了掀蓋款,同一句話就不再只指一個商品。
                # 所以每次都重看一次:現在還有別款也符合這句話,就退回候選讓人選,
                # 不讓舊別名把新款蓋掉。
                context = context or MatchContext(tenant, supplier)
                others = [
                    c for c in context.scan(
                        text, is_secondhand=is_secondhand, with_related=False, limit=limit
                    )
                    if c.product_id != only.product_id and c.level in (EXACT, COVERS)
                ]
                if others:
                    only.differences = ["另有相似商品,請確認是哪一款"]
                    return MatchResult(MatchResult.CANDIDATES, [only, *others])
            return MatchResult(MatchResult.EXISTING, found)
        if len(found) > 1:
            for c in found:
                c.conflict = True
                c.differences = ["同一個識別碼指到不同商品,請先確認哪一個才對"]
            found.sort(key=lambda c: (not c.is_active, c.sku))
            return MatchResult(MatchResult.CONFLICT, found)

    # ② 特徵比對
    if not (text or "").strip():
        return MatchResult(MatchResult.NONE, [])
    context = context or MatchContext(tenant, supplier)
    found = context.scan(
        text, is_secondhand=is_secondhand, with_related=with_related,
        symmetric=symmetric, limit=limit,
    )
    return MatchResult(MatchResult.CANDIDATES if found else MatchResult.NONE, found)
