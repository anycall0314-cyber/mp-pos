"""機型名稱萃取 helper。

用途:把「iPhone 13 Pro 128G 金色」這種品名,去除容量/顏色/中古機標記等變體尾段,
萃取出共同的「機型名稱」(例:iPhone 13 Pro),用於配件 - 主機相容性綁定。

優先序:
1. 若 Product.series 有填 → 用「series + generation」(系列 + 世代)
2. 否則 regex 解析 Product.name 剝掉變體尾段
"""
import re

# 容量:「128G」「256GB」「1TB」(允許前後空白)
_CAPACITY_RE = re.compile(r"\s*\d+\s*(?:G|GB|TB)\b", re.IGNORECASE)

# 末段顏色:漢字「黑白金銀灰藍紅綠紫粉橙黃青棕褐」(可選「色」),或英文常用色名
_COLOR_RE = re.compile(
    r"\s*(?:"
    r"[黑白金銀灰藍紅綠紫粉橙黃青棕褐]+色?"
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
        s = _COLOR_RE.sub("", s)
        s = _SECONDHAND_RE.sub("", s)
        s = re.sub(r"\s*/\s*", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
    return s


def compute_phone_model_name(product) -> str:
    """從 Product 算出機型名稱。
    series 有填優先(配上 generation);否則退回 regex 解析 name。
    """
    if product.series:
        if product.generation:
            return f"{product.series} {product.generation}".strip()
        return product.series.strip()
    return extract_phone_model_name(product.name or "")


def compute_phone_model_key(product) -> str:
    """機型 key:lowercase 機型名稱,用於 dedup / 跨 SKU 連結。"""
    return compute_phone_model_name(product).strip().lower()
