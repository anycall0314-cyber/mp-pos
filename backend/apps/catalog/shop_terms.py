r"""通訊行的常用寫法:查詢用的語彙表。

owner 2026-10-09:「庫存查詢系統不夠強大,還要再帶入通訊的常用語彙,比如 IP=IPHONE, U=Ultra, +=Plus」。

## 這支在做什麼

把人打的一串字拆成一個字一個字,每個字變成一條比對式(regex)。**每一條都要在商品的文字裡對得上**,對得上的意思是:

- 照字面出現(原本就找得到的那一種);或
- 用店裡另一種寫法出現(下面的語彙表),而且型號中間有沒有空白 / 連字號都算
  (`IP17PM` = `iPhone 17 Pro Max` = `IPHONE17 P MAX`)。

只會多找到,不會少找到:每個字的比對式都把「照字面」留著。

## 跟 `identity.product_match` 的分工

那一支是「認定是不是同一個商品」用的(防重複、進貨比對),要準:`IP17` ≠ `IP17PM`,而且要公司有機型主檔才認得簡寫。
這一支只給**查詢**用,要找得到:不需要機型主檔、打 `IP17` 連 `IP17PM` 也出來(字面本來就會)、不替人做任何決定。
兩支不共用規則,查詢的結果是兩邊合起來(見 `ProductViewSet.stock_matrix`)。

## 語彙是從舊系統的品名數出來的,不是猜的

15,312 個不重複品名:`IP` 當字首 3,419 次(`IPHONE` 486);數字後面接 `PM` 709、`+` 949、`U` 253、`P` 938;
`SAM` 2,005 / `三星` 609;`華為` 190 / `HUAWEI` 130;`紅米` 465;`ZF`(= ZenFone)182;容量寫 `G` 4,239 / `GB` 120;
顏色單寫一個字 3,462 / 加「色」123。新機在舊系統寫成 `APPLE-IPHONE11 P MAX灰256`、`APPLE-18PM/1TB/紅`、`三星-A07 4/128裸光紫`。

## 要加一個詞

在 `TERMS` 加一筆(三個欄位的意思寫在 `Term`),再到 `test_shop_terms.py` 補一個「打什麼 → 找得到什麼 / 找不到什麼」。
比對式兩邊都要能跑、而且意思要一樣:Python 的 `re`(測試)與 PostgreSQL 的 `~`(實際查詢)。
`TERMS` 裡照習慣寫大寫、`\d`、`\s`,交出去之前 `_portable()` 會把它們全部寫明:
大小寫變成 `[Ii][Pp]`(比對時**分大小寫**,不開「不分大小寫」)、數字變成 `[0-9]`、空白變成列出來的那四種。
不寫明的話兩邊對「哪些算空白 / 數字 / 同一個字母的大小寫」看法不一樣(U+0085、全形數字、土耳其文的 İ),會變成測試說找得到、實際查不到。
回頭看的條件(`(?<=…)`)只能固定一個字;群組只用 `(?:` `(?=` `(?!` `(?<=` `(?<!`;字元類別裡不放 `]`。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# 同一個型號裡可有可無的空白 / 連字號
SEP = r"[\s\-]*"

MAX_WORDS = 8
MAX_WORD_LEN = 40


@dataclass(frozen=True)
class Term:
    """一個詞的幾種寫法。三個欄位都是比對式的片段(寫大寫就好,交出去之前 `_portable()` 會把大小寫寫明)。"""

    label: str   # 給人看的:這個詞是什麼
    typed: str   # 人打的字裡怎麼認出它(在一個字裡,從某個位置開始比)
    inline: str  # 它的前後還接著別的字時(IP17PM 裡的 IP、PM),商品文字裡可能的寫法
    alone: str   # 整個字就只有它時(打「pro max」「U」「三星」),商品文字裡可能的寫法;自己帶前後條件,不然太鬆


def _brand(label: str, *latin: str, cjk: str) -> Term:
    names = "|".join(latin)
    text = rf"(?:(?<![A-Z])(?:{names})(?![A-Z])|{cjk})"
    return Term(label, typed=rf"(?<![A-Z])(?:{names})(?![A-Z])|{cjk}", inline=text, alone=text)


# 順序就是認的順序:長的、明確的排前面(PROMAX 要在 PRO 之前)
TERMS: tuple[Term, ...] = (
    Term(
        # 舊系統的新機寫成 `APPLE-18PM`、更早的寫成 `APPLE-I6S PLUS`:APPLE 後面直接接數字就是 iPhone
        "iPhone = IP(舊系統也寫成 APPLE-18PM、APPLE-I6S)",
        typed=r"(?<![A-Z])IPHONE|(?<![A-Z])IP(?=\d|X|SE|$)",
        inline=r"(?:IPHONE|IP|APPLE[\s\-]+I?(?=\d))",
        alone=rf"(?<![A-Z])(?:IPHONE|IP(?={SEP}(?:\d|X|SE))|APPLE[\s\-]+I?(?=\d))",
    ),
    Term(
        "Pro Max = PM = PMAX = P MAX",
        typed=r"(?<![A-Z])PRO\-?MAX(?![A-Z])|(?<![A-Z])P\-?MAX(?![A-Z])|(?<=\d)PM(?![A-Z])|^PM$",
        inline=rf"(?:PRO{SEP}MAX|P{SEP}MAX|PM)(?![A-Z])",
        alone=rf"(?:(?<![A-Z])PRO{SEP}MAX|(?<=\d){SEP}P{SEP}MAX|(?<=\d){SEP}PM)(?![A-Z])",
    ),
    Term(
        # 打 Pro 連 Pro Max 也出來:字面本來就會(PRO 是 PRO MAX 的開頭、17P 是 17PM 的開頭)
        "Pro = P(接在數字後面)",
        typed=r"(?<![A-Z])PRO(?![A-Z])|(?<=\d)P(?![A-Z])",
        inline=rf"(?:PRO(?:{SEP}MAX)?|P(?:{SEP}MAX|M)?)(?![A-Z])",
        alone=rf"(?:(?<![A-Z])PRO|(?<=\d){SEP}P(?:{SEP}MAX|M)?(?![A-Z]))",
    ),
    Term(
        # 單獨打「plus」時,`8+256G`(記憶體 + 容量)的那個加號不算
        "Plus = +",
        typed=r"(?<![A-Z])PLUS(?![A-Z])|\+",
        inline=r"(?:PLUS|\+)",
        alone=r"(?:(?<![A-Z])PLUS(?![A-Z])|(?<=[A-Z0-9])\+(?!\d))",
    ),
    Term(
        "Ultra = U(接在數字後面)",
        typed=r"(?<![A-Z])ULTRA(?![A-Z])|(?<=\d)U(?![A-Z])|^U$",
        inline=r"(?:ULTRA|U)(?![A-Z])",
        alone=rf"(?:(?<![A-Z])ULTRA|(?<=\d){SEP}U)(?![A-Z])",
    ),
    Term(
        "Z Fold = Fold",
        typed=r"(?<![A-Z])Z\-?FOLD(?![A-Z])|(?<![A-Z])FOLD(?![A-Z])",
        inline=rf"(?:Z{SEP})?FOLD",
        alone=rf"(?<![A-Z])(?:Z{SEP})?FOLD(?![A-Z])",
    ),
    Term(
        "Z Flip = Flip",
        typed=r"(?<![A-Z])Z\-?FLIP(?![A-Z])|(?<![A-Z])FLIP(?![A-Z])",
        inline=rf"(?:Z{SEP})?FLIP",
        alone=rf"(?<![A-Z])(?:Z{SEP})?FLIP(?![A-Z])",
    ),
    Term(
        "ZenFone = ZF",
        typed=r"(?<![A-Z])ZENFONE(?![A-Z])|(?<![A-Z])ZF(?=\d)",
        inline=r"(?:ZENFONE|ZF)",
        alone=rf"(?<![A-Z])(?:ZENFONE|ZF(?={SEP}\d))",
    ),
    _brand("三星 = SAM = Samsung = Galaxy", "SAMSUNG", "SAM", "GALAXY", cjk="三星"),
    _brand("華為 = Huawei", "HUAWEI", cjk="華為"),
    _brand("小米 = Xiaomi", "XIAOMI", cjk="小米"),
    _brand("紅米 = Redmi", "REDMI", cjk="紅米"),
    _brand("蘋果 = Apple", "APPLE", cjk="蘋果"),
    _brand("谷歌 = Google", "GOOGLE", cjk="谷歌"),
    _brand("華碩 = ASUS", "ASUS", cjk="華碩"),
    _brand("索尼 = Sony", "SONY", cjk="索尼"),
)
_TYPED = tuple((term, re.compile(term.typed)) for term in TERMS)

# 容量:256G = 256GB = 單寫 256(舊系統的新機寫「灰256」)。只認容量會有的數字,免得把 5G(網路)也當成容量。
_CAPACITY = re.compile(r"(?<![\d.])(8|16|32|64|128|256|512|1024)(?:GB|G)(?![A-Z])")
_CAPACITY_TB = re.compile(r"(?<![\d.])([12])(?:TB|T)(?![A-Z])")
# 顏色:黑色 = 黑(品名多半只寫一個字)
_COLOR = re.compile(r"([黑白藍灰粉銀綠金紫紅黃橘棕桃透])色")
_SPECIALS = (
    (_CAPACITY, lambda m: rf"(?<![\d.]){m.group(1)}(?:{SEP}GB?)?(?![A-Z0-9])"),
    (_CAPACITY_TB, lambda m: rf"(?<![\d.]){m.group(1)}{SEP}TB?(?![A-Z0-9])"),
    (_COLOR, lambda m: rf"{m.group(1)}色?"),
)

_ATOM = re.compile(r"[A-Z]+|\d+(?:\.\d+)?|[一-鿿]+|.", re.S)
_CJK = re.compile(r"[一-鿿]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SPLIT = re.compile(r"[\s/,、;|]+")
# 兩個字的詞先接起來,後面才認得出來
_PHRASES = ((re.compile(r"PRO\s+MAX(?![A-Z])"), "PROMAX"), (re.compile(r"(?<![A-Z])P\s+MAX(?![A-Z])"), "PMAX"))


# 當成空白的:半形空白、Tab、不斷行空白(從網頁貼上常有)、全形空白。寫明,不用 `\s`
_SPACES = " \t\u00a0\u3000"
_GROUP = re.compile(r"\(\?(?::|=|!|<=|<!)")


def _both_cases(c: str) -> str:
    forms = {c, *(v for v in (c.lower(), c.upper()) if len(v) == 1)}
    return c if len(forms) == 1 else "[" + "".join(sorted(forms)) + "]"


def _portable(pattern: str) -> str:
    """把比對式裡「靠引擎自己認」的東西全部寫明,兩個引擎的意思才會一樣(理由見最上面)。

    吃的是這一支自己組出來的比對式:人打的字都跳脫過(不會有沒跳脫的 `[`、`(`、`\\d`)。
    """
    out, i, n = [], 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":
            pair = pattern[i:i + 2]
            out.append("[0-9]" if pair == r"\d" else f"[{_SPACES}]" if pair == r"\s" else pair)
            i += 2
        elif c == "[":
            j = i + 1
            while pattern[j] != "]":
                j += 2 if pattern[j] == "\\" else 1
            body = pattern[i + 1:j].replace(r"\d", "0-9").replace(r"\s", _SPACES).replace("A-Z", "A-Za-z")
            out.append(f"[{body}]")
            i = j + 1
        elif pattern.startswith("(?", i):
            out.append(_GROUP.match(pattern, i).group())
            i += len(out[-1])
        else:
            out.append(_both_cases(c))
            i += 1
    return "".join(out)


def _special_at(word: str, i: int):
    for pattern, text in _SPECIALS:
        m = pattern.match(word, i)
        if m:
            return m, text(m)
    return None


def _term_at(word: str, i: int):
    for term, pattern in _TYPED:
        m = pattern.match(word, i)
        if m and m.end() > i:
            return m, term
    return None


def _pieces(word: str) -> list[tuple[Term | None, str]]:
    """一個字切成一段一段:(詞, 人打的那一段) 或 (None, 已經寫成比對式的那一段)。"""
    out: list[tuple[Term | None, str]] = []
    i, n = 0, len(word)
    while i < n:
        hit = _term_at(word, i)
        if hit:
            out.append((hit[1], hit[0].group()))
            i = hit[0].end()
            continue
        special = _special_at(word, i)
        if special:
            out.append((None, special[1]))
            i = special[0].end()
            continue
        if word[i] == "-" and out and i + 1 < n:
            i += 1          # 型號中間的連字號:有沒有都一樣(每一段之間本來就容許)
            continue
        end = _ATOM.match(word, i).end()
        if _CJK.match(word, i):
            # 一串中文裡面可能夾著認得的詞(原廠三星充電器、牛仔黑色):切到它前面為止
            for j in range(i + 1, end):
                if _term_at(word, j) or _special_at(word, j):
                    end = j
                    break
        out.append((None, re.escape(word[i:end])))
        i = end
    return out


def _word_pattern(word: str) -> str:
    if _NUMBER.fullmatch(word):
        # 單獨一個數字要是「那個數字」:打 17 不該對到日期碼 251017、打 256 不該對到 2560
        return rf"(?<![\d.]){re.escape(word)}(?!\d)"
    pieces = _pieces(word)
    literal = re.escape(word)
    if len(pieces) == 1:
        term, text = pieces[0]
        if term is None:
            return text
        # 整個字就是一個詞。很短的(U、PM、IP、+)照字面太鬆(「有 U 的都算」),只用帶條件的那一種
        return term.alone if len(word) <= 2 and word.isascii() else f"(?:{literal}|{term.alone})"
    expanded = SEP.join(text if term is None else term.inline for term, text in pieces)
    # 從一個字的開頭對起:`A17` 不該對到 `2.4A 17W`。字面那一種不受這個限制(原本找得到的照舊)
    head = word[0]
    guard = r"(?<![A-Z0-9])" if "A" <= head <= "Z" else r"(?<![\d.])" if head.isdigit() else ""
    return f"(?:{literal}|{guard}{expanded})"


def word_patterns(query: str) -> list[str]:
    """人打的字 → 每個字一條比對式(大小寫、空白、數字都寫明了;比對時**分大小寫**)。每一條都對得上才算找到。

    回空的 = 不用這一套(空的、字太多、太長),呼叫的人只照字面找。
    """
    text = unicodedata.normalize("NFKC", query or "").upper()
    for pattern, joined in _PHRASES:
        text = pattern.sub(joined, text)
    words = [w for w in _SPLIT.split(text) if w]
    if not words or len(words) > MAX_WORDS or any(len(w) > MAX_WORD_LEN for w in words):
        return []
    return [_portable(_word_pattern(w)) for w in words]


def matches(query: str, *texts: str) -> bool:
    """每個字都在這幾段文字的其中一段對得上(測試與量測用;實際查詢在資料庫裡比)。"""
    patterns = word_patterns(query)
    return bool(patterns) and all(
        any(re.search(p, t or "") for t in texts) for p in patterns
    )
