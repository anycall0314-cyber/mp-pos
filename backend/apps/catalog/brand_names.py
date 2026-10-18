"""品牌的中文 / 英文名稱(owner 2026-10-17:「針對品牌可以有中文及英文的個別欄位填寫，填寫為選填，如果不填品牌視同無品牌」)。

- 兩格都選填、至少一格;顯示名稱(`Brand.name`)= 兩格都有寫「膜總裁 MOCEO」、只有一格就那一格。
- 只打一格的(表單「新廠牌」、整理舊品名、型號庫的品牌):「膜總裁 MOCEO」這種中文一段、英文一段的拆成兩格,
  其他有中文字的放中文、沒有的放英文(`split`)。
- 找品牌(`find_brand`):打的字跟某個品牌的中文、英文、或顯示名稱一樣(大小寫、空白不算)就是那一個,不另外建
  (紅隊:同一個廠牌中英文各打一次會變兩個)。
"""
from __future__ import annotations

import re

_CJK = re.compile(r"[㐀-鿿豈-﫿]")


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def tidy(text: str) -> str:
    return " ".join((text or "").split())


def fold(text: str) -> str:
    """比對用:去掉所有空白、不分大小寫(`AI 膜速箱` = `AI膜速箱`、`moceo` = `MOCEO`)。"""
    return "".join((text or "").split()).casefold()


def split(text: str) -> tuple[str, str]:
    """一格的名字 → (中文, 英文)。中文一段、英文一段(順序不拘)才拆;其他有中文字的整段算中文。"""
    words = tidy(text).split(" ") if tidy(text) else []
    if not words:
        return "", ""
    cjk = [has_cjk(w) for w in words]
    for cut in range(1, len(words)):
        left, right = cjk[:cut], cjk[cut:]
        if all(left) and not any(right):
            return " ".join(words[:cut]), " ".join(words[cut:])
        if not any(left) and all(right):
            return " ".join(words[cut:]), " ".join(words[:cut])
    whole = " ".join(words)
    return (whole, "") if any(cjk) else ("", whole)


def slots(text: str) -> dict:
    """一格的名字改到既有品牌上:只蓋它屬於的那一格(`Samsung` 不會把已經填好的「三星」清掉)。"""
    zh, en = split(text)
    return {k: v for k, v in (("name_zh", zh), ("name_en", en)) if v}


def join(zh: str, en: str) -> str:
    return " ".join(x for x in (tidy(zh), tidy(en)) if x)


def spellings(brand) -> set[str]:
    """這個品牌認得的寫法(比對用,已經 fold)。"""
    return {fold(s) for s in (brand.name, brand.name_zh, brand.name_en) if fold(s)}


def find_brand(tenant, text: str, *, exclude_id=None):
    """這家公司裡,中文 / 英文 / 顯示名稱跟 `text` 一樣的品牌;`text` 是「中文 英文」合起來的也認(拆開兩格各比一次)。"""
    from .models import Brand

    wanted = {fold(text)} | {fold(x) for x in split(text) if x}
    wanted.discard("")
    if not wanted:
        return None
    for b in Brand.objects.for_tenant(tenant).order_by("pk"):
        if b.pk != exclude_id and spellings(b) & wanted:
            return b
    return None


def unique_code(tenant, name: str) -> str:
    """新品牌的代碼(英數;中文名字的照「brand」編號)。"""
    from django.utils.text import slugify

    from .models import Brand

    maxlen = Brand._meta.get_field("code").max_length or 20
    base = (slugify(name) or "brand")[:maxlen]
    code, n = base, 1
    while Brand.objects.for_tenant(tenant).filter(code=code).exists():
        n += 1
        code = base[: maxlen - len(f"-{n}")] + f"-{n}"
    return code


class MergeError(Exception):
    pass


def merge(tenant, source_id: int, target_id: int) -> tuple[object, int]:
    """把一個品牌併到另一個(紅隊:同一個廠牌中英文各打一次裂成兩個、「太空盾 / 真太空盾」,沒有合併就修不回來)。

    商品、類別底下的掛法搬到 `target`;`target` 空著的中文 / 英文用 `source` 的補上;`source` 刪掉。
    手機品牌(底下有系列 / 型號)不併 —— 型號庫每天自動新增新機照品牌找,併錯了同一支手機會拆兩邊。回 (target, 搬了幾個商品)。
    """
    from django.db import transaction

    from .models import Brand, CategoryBrand, Product

    if source_id == target_id:
        raise MergeError("要併到另一個品牌")
    with transaction.atomic():
        rows = {b.pk: b for b in Brand.objects.for_tenant(tenant).filter(pk__in=[source_id, target_id])
                .select_for_update().order_by("pk")}
        source, target = rows.get(source_id), rows.get(target_id)
        if source is None or target is None:
            raise MergeError("沒有這個品牌")
        if source.series.exists() or source.phone_models.exists():
            raise MergeError(f"「{source.name}」底下有手機型號,不能合併")
        moved = Product.objects.filter(tenant=tenant, brand=source).update(brand=target)
        have = set(CategoryBrand.objects.filter(brand=target).values_list("category_id", flat=True))
        for link in CategoryBrand.objects.filter(brand=source):
            if link.category_id in have:
                link.delete()
            else:
                CategoryBrand.objects.filter(pk=link.pk).update(brand=target)
        zh, en = target.name_zh or source.name_zh, target.name_en or source.name_en
        source.delete()
        target.name_zh, target.name_en = zh, en
        target.save(update_fields=["name", "name_zh", "name_en", "updated_at"])
    return target, moved


def catalog_name(brand_name: str, name_zh: str = "", name_en: str = "") -> str:
    """給查表用的品牌字(型號庫 / 配件品名的品牌群組照英文寫:`Samsung`):有英文用英文,沒有用顯示名稱。"""
    return tidy(name_en) or tidy(brand_name) or tidy(name_zh)
