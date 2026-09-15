"""把「廠商亂寫的字」正規化成穩定的比對鍵。

原則(對齊 docs/product-roadmap.md §7):只是寫法差異的東西,正規化後要能撞在一起
→ 判定成「同一個標的、只是別名」;真正的規格差異(容量/顏色/版本)交給識別引擎的
衝突檢查處理,不在這裡抹平。

這一層只做「無損的寫法統一」:全形→半形、大小寫、去空白與符號、容量單位統一。
顏色同義詞、屬性拆解等「有語意」的比對放識別引擎(services.py),不放這裡。
"""
import hashlib
import re
import unicodedata

# 常見容量寫法統一到 <數字>GB / <數字>TB。128g→128GB、1 tb→1TB。
_CAP_GB_RE = re.compile(r"(\d+)\s*(?:gb|g)\b", re.I)
_CAP_TB_RE = re.compile(r"(\d+)\s*(?:tb|t)\b", re.I)
# 比對鍵要丟掉的符號(空白、標點、全半形分隔)。保留英數與中日韓漢字。
_STRIP_RE = re.compile(r"[\s\-_/\\.,、，。:：;；|()\[\]{}<>#*'\"`~!?！？]+")


def _to_halfwidth(text: str) -> str:
    """全形英數 / 符號 → 半形(NFKC 一次搞定大部分)。"""
    return unicodedata.normalize("NFKC", text)


def normalize(text: str) -> str:
    """回傳穩定的比對鍵。空字串進、空字串出。

    範例:
        "APPLE IP15 128 BK"   → "appleip15128bk"
        "iPhone15 128G 黑"     → "iphone15128gb黑"
        " 128 gb "            → "128gb"
        "1 TB"                → "1tb"
    """
    if not text:
        return ""
    s = _to_halfwidth(str(text)).lower()
    s = _CAP_TB_RE.sub(lambda m: f"{m.group(1)}tb", s)
    s = _CAP_GB_RE.sub(lambda m: f"{m.group(1)}gb", s)
    s = _STRIP_RE.sub("", s)
    return s.strip()


# ProductAlias.value 的欄位長度(存原字用)
ALIAS_VALUE_MAX = 500
# ProductAlias.normalized_value 的欄位長度(存比對鍵用)
ALIAS_KEY_MAX = 200


def alias_key(value) -> str:
    """別名比對鍵。寫入端與查詢端都必須用這一支,結果才會一致。

    正規化後超過欄位長度時改存雜湊,**不是截斷**。截斷會把「前 200 字相同、
    尾巴是 128GB / 256GB」的兩個商品併成同一個 key,學了一個就自動對到另一個。
    另外 NFKC 展開會讓字變長(51 個「㍿」展開成 204 字),先截輸入再正規化
    仍可能超長而炸 DataError,雜湊一併解掉。
    """
    v = (str(value) if value is not None else "").strip()[:ALIAS_VALUE_MAX]
    norm = normalize(v)
    if len(norm) <= ALIAS_KEY_MAX:
        return norm
    return "sha256:" + hashlib.sha256(norm.encode("utf-8")).hexdigest()


def normalize_serial(text: str) -> str:
    """序號 / IMEI 比對用正規化:去空白 / 破折號 / 點,轉大寫。
    範例:"35 611111-1111 11" → "35611111111111"、"sn-ab.12" → "SNAB12"。
    """
    if not text:
        return ""
    return re.sub(r"[\s\-_.]+", "", str(text).strip()).upper()


def normalize_capacity(text: str) -> str:
    """把容量欄位正規化成比對用的值,例:"128 G" / "128gb" → "128gb"。
    無法辨識就回原字的正規化結果(至少大小寫去空白統一)。
    """
    if not text:
        return ""
    s = _to_halfwidth(str(text)).lower().strip()
    m = _CAP_TB_RE.search(s)
    if m:
        return f"{m.group(1)}tb"
    m = _CAP_GB_RE.search(s)
    if m:
        return f"{m.group(1)}gb"
    return _STRIP_RE.sub("", s)
