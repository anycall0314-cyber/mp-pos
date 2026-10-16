"""平台給新公司的類別範本(owner 2026-10-16):「類別：手機 平板 穿戴 皮套 玻璃貼 空壓殼 傳輸線
類別下再建立中項填寫品牌 品牌後才是型號 類別，品牌可以自由建立，只是你幫我建立好範本」。

- 只在**新建公司**時套(平台管理 → 經銷商 → 新增);已經在用的公司不自動補(紅隊第 3 條:會多出一排近義類別、報表拆開)。
- 主機類別的預設品牌從平台型號庫帶(型號多的排前面);配件 / 一般類別的廠牌各家自己加。
- 名稱已經有的類別不動;代碼被用掉了就換一個。可以重跑,已經有的不重建。
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count

from .models import Category, CategoryBrand, DeviceModel

DEVICE, ACCESSORY, GENERAL = Category.Kind.DEVICE, Category.Kind.ACCESSORY, Category.Kind.GENERAL

# (代碼, 名稱, 種類, 主機類別從型號庫的哪幾類帶品牌);手錶、手環、藍牙耳機都在穿戴(owner 2026-10-16「都進穿戴」)
TEMPLATE = [
    ("PH", "手機", DEVICE, ("phone",)),
    ("PD", "平板", DEVICE, ("tablet",)),
    ("WR", "穿戴", DEVICE, ("watch", "band", "headphones", "other")),
    ("LC", "皮套", ACCESSORY, ()),
    ("PP", "玻璃貼", ACCESSORY, ()),
    ("CA", "空壓殼", ACCESSORY, ()),
    ("CH", "傳輸線", GENERAL, ()),     # 充電頭也在這裡(owner:「同一類，改名傳輸線」)
]


def flags_of(kind: str) -> dict:
    """種類 → 類別的兩個欄位(主機類別、要不要掛相容機型)。"""
    return {"holds_devices": kind == DEVICE, "needs_host_model": kind == ACCESSORY}


def catalog_brands(device_categories) -> list[str]:
    """型號庫裡這幾類的品牌,型號多的排前面。"""
    rows = (DeviceModel.objects.filter(is_active=True, category__in=device_categories)
            .values("brand").annotate(n=Count("id")).order_by("-n", "brand"))
    return [r["brand"] for r in rows]


def link_brand(category: Category, brand) -> CategoryBrand:
    """把品牌掛到類別底下(已經掛了就照舊);新掛的排最後。"""
    link = CategoryBrand.objects.filter(category=category, brand=brand).first()
    if link is None:
        last = CategoryBrand.objects.filter(category=category).order_by("-sort_order").first()
        link = CategoryBrand.objects.create(tenant=category.tenant, category=category, brand=brand,
                                            sort_order=(last.sort_order + 1) if last else 0)
    return link


@transaction.atomic
def apply(tenant) -> dict:
    """把範本套到這家公司。回 {"categories": 新建幾個, "brands": 新掛幾個}。"""
    from .device_expand import _brand

    made = {"categories": 0, "brands": 0}
    have = {c.name.strip(): c for c in Category.objects.for_tenant(tenant)}
    codes = set(Category.objects.for_tenant(tenant).values_list("code", flat=True))
    for i, (code, name, kind, device_categories) in enumerate(TEMPLATE):
        category = have.get(name)
        if category is None:
            use, n = code, 1
            while use in codes:
                n += 1
                use = f"{code}{n}"
            category = Category.objects.create(tenant=tenant, code=use, name=name, sort_order=(i + 1) * 10, **flags_of(kind))
            codes.add(use)
            made["categories"] += 1
        before = CategoryBrand.objects.filter(category=category).count()
        for brand_name in catalog_brands(device_categories) if device_categories else []:
            link_brand(category, _brand(tenant, brand_name))
        made["brands"] += CategoryBrand.objects.filter(category=category).count() - before
    return made
