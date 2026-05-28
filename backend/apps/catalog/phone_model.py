"""機型名稱萃取 helper。

用途:把「iPhone 13 Pro 128G 金色」這種品名,去除容量/顏色/中古機標記等變體尾段,
萃取出共同的「機型名稱」(例:iPhone 13 Pro),用於配件 - 主機相容性綁定。

優先序:
1. 若 Product.series 有填 → 用「series + generation」(系列 + 世代)
2. 否則 regex 解析 Product.name 剝掉變體尾段
"""
import re

# 容量:「128G」「256GB」「1TB」 + 允許 RAM/儲存 串接格式
# 分隔符僅支援 「/」(例:「12/512G」「8/256/512G」);
# 不收 「+」,避免「三星 S26+」這種 Plus 機型尾碼被誤吃成「RAM+儲存」
_CAPACITY_RE = re.compile(
    r"\s*(?:\d+\s*/\s*)*\d+\s*(?:G|GB|TB)\b", re.IGNORECASE
)

# 容量被剝後常剩下空的括號(全形 / 半形 / 方括號)— 移除
_EMPTY_PARENS_RE = re.compile(r"[\(\[（［]\s*[\)\]）］]")

# 末段顏色:支援 0~3 個 CJK 前綴 + 色字(漫遊紫 / 星空黑 / 鈦金 / 雪松白…),
# 或單獨漢字色字 + 可選「色」字,或英文常用色名
_COLOR_RE = re.compile(
    r"\s*(?:"
    r"(?:[一-鿿]{1,3})?[黑白金銀灰藍紅綠紫粉橙黃青棕褐]+色?"
    r"|Black|White|Gold|Silver|Grey|Gray|Blue|Red|Green|Purple"
    r"|Pink|Orange|Yellow|Bronze|Midnight|Starlight|Graphite|Sierra"
    r")\s*$",
    re.IGNORECASE,
)

# 「(中古)」「中古」尾段
_SECONDHAND_RE = re.compile(r"\s*\(?\s*中古\s*\)?\s*$")


def extract_phone_model_name(name: str) -> str:
    """從品名萃取機型名稱(去掉容量 / 顏色 / 中古機等變體尾段)。

    >>> extract_phone_model_name("iPhone 13 Pro 128G 金色")
    'iPhone 13 Pro'
    >>> extract_phone_model_name("iPhone 13 Pro 256G 黑色")
    'iPhone 13 Pro'
    >>> extract_phone_model_name("Samsung Galaxy A55 128G Black")
    'Samsung Galaxy A55'
    >>> extract_phone_model_name("iPhone 12 64G (中古)")
    'iPhone 12'
    """
    if not name:
        return ""
    s = name
    # 多輪剝除,直到字串不再變化(處理多種尾段疊加)
    prev = None
    while prev != s:
        prev = s
        s = _CAPACITY_RE.sub("", s)
        s = _EMPTY_PARENS_RE.sub("", s)
        s = _COLOR_RE.sub("", s)
        s = _SECONDHAND_RE.sub("", s)
        s = re.sub(r"\s*/\s*", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
    return s


# 品名 → 品牌 的關鍵字對照表(從上而下嘗試,先匹配先用)
_BRAND_KEYWORDS: list[tuple[str, str]] = [
    ("iPhone", "apple"),
    ("iPad", "apple"),
    ("Apple", "apple"),
    ("Galaxy", "samsung"),
    ("Samsung", "samsung"),
    ("三星", "samsung"),
    ("Redmi", "xiaomi"),
    ("紅米", "xiaomi"),
    ("Xiaomi", "xiaomi"),
    ("小米", "xiaomi"),
    ("OPPO", "oppo"),
    ("Reno", "oppo"),
    ("VIVO", "vivo"),
    ("ASUS", "asus"),
    ("ROG", "asus"),
    ("Zenfone", "asus"),
    ("華碩", "asus"),
    ("Pixel", "google"),
    ("Sony", "sony"),
    ("索尼", "sony"),
    ("Xperia", "sony"),
    ("HUAWEI", "huawei"),
    ("華為", "huawei"),
    ("Honor", "honor"),
    ("榮耀", "honor"),
    ("OnePlus", "oneplus"),
    ("Nothing", "nothing"),
    ("Realme", "realme"),
    ("Motorola", "motorola"),
    ("Moto", "motorola"),
    ("Nokia", "nokia"),
]


def infer_brand_from_name(name: str) -> str:
    """從品名前綴自動猜品牌 code(對應 Product.Brand choices)。

    比 Product.brand 欄位被遺漏填寫的情況用 — 主要供前端「批次建立 / 機型挑選」
    分組顯示,不會真的寫回 Product.brand。
    """
    if not name:
        return ""
    lower = name.lower()
    for kw, brand_code in _BRAND_KEYWORDS:
        if kw.lower() in lower:
            return brand_code
    return ""


def _smart_join(parts: list[str]) -> str:
    """組裝機型名稱片段;遇到 「+」「/」 開頭的後綴不加空格,其餘加空格。"""
    if not parts:
        return ""
    out = parts[0]
    for p in parts[1:]:
        if not p:
            continue
        if p[0] in "+/":
            out += p
        else:
            out += " " + p
    return out


def compute_phone_model_name(product) -> str:
    """從 Product 算出機型名稱。

    優先順序:
    1. (新框架)brand_id + series_id 都有 → 系列名 + 世代 + 後綴
       例:Galaxy S 26 / Galaxy S 26+ / Galaxy S 26 Ultra / iPhone 15 Pro Max
    2. 退回 regex 解析 Product.name
    """
    if product.series_id:
        parts: list[str] = []
        try:
            parts.append(product.series.name)
        except Exception:
            return extract_phone_model_name(product.name or "")
        if product.generation:
            parts.append(str(product.generation))
        if product.model_suffix:
            parts.append(product.model_suffix)
        return _smart_join(parts).strip()
    return extract_phone_model_name(product.name or "")


def compute_phone_model_key(product) -> str:
    """機型 key:lowercase 機型名稱,用於 dedup / 跨 SKU 連結。"""
    return compute_phone_model_name(product).strip().lower()
