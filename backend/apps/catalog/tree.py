"""商品頁「分類瀏覽」:類別 → 品牌(中項)→ 型號 → 商品(owner 2026-10-16)。

- 主機類別(手機 / 平板 / 穿戴):品牌 = 商品的品牌 → 型號 = 機型 → 右邊照品況列容量顏色(沿用 by-phone-model)。
- 配件類別:**依手機** = 適用機型的品牌 → 適用機型 → 這支能用的配件照配件廠牌分組;**依廠牌** = 商品的品牌(配件廠牌)→ 商品(旁邊寫適用機型)。
- 一般類別:只有依廠牌。
- 沒填品牌的放「無品牌」(owner 2026-10-17:「如果不填品牌視同無品牌」)、沒掛適用機型的放「未分」(id 都是 "none");類別底下掛了、還沒有商品的品牌也列(數量 0),照類別的排序在前。
"""
from __future__ import annotations

from collections import defaultdict

from .models import Category, CategoryBrand, Product, ProductRelation

NONE = "none"
NO_BRAND = "無品牌"
LIMIT = 500   # 一層最多列幾個商品(未分的舊資料可能上千個;多的請用搜尋)


def _products(qs, category):
    return qs.filter(category=category, is_active=True, is_virtual=False)


def _fits(product_ids) -> dict[int, list[tuple[int | None, str, int | None, str]]]:
    """配件 → [(機型編號, 機型名稱, 機型品牌編號, 機型品牌名稱)]。舊資料沒有機型編號的,用代表 SKU 的機型 / 品牌補。"""
    out = defaultdict(list)
    rels = (ProductRelation.objects.filter(accessory_product_id__in=product_ids)
            .select_related("host_model__brand", "host_product__brand", "host_product__phone_model").order_by("pk"))
    for r in rels:
        pm = r.host_model or (r.host_product.phone_model if r.host_product_id else None)
        brand = (pm.brand if pm is not None and pm.brand_id else None) or (r.host_product.brand if r.host_product_id else None)
        name = pm.name if pm is not None else (r.host_model_key or "")
        out[r.accessory_product_id].append((pm.pk if pm is not None else None, name,
                                            brand.pk if brand else None, brand.name if brand else ""))
    return out


def _brand_rows(category, counts: dict, names: dict) -> list[dict]:
    """類別底下掛的品牌照排序在前(沒有商品的也列),其他有商品的品牌照數量排在後面,無品牌最後。"""
    linked = list(CategoryBrand.objects.filter(category=category).select_related("brand").order_by("sort_order", "id"))
    rows = [{"id": link.brand_id, "name": link.brand.name, "count": counts.get(link.brand_id, 0)} for link in linked]
    seen = {link.brand_id for link in linked}
    rest = sorted((b for b in counts if b not in seen and b != NONE), key=lambda b: (-counts[b], names.get(b, "")))
    rows += [{"id": b, "name": names.get(b, ""), "count": counts[b]} for b in rest]
    if counts.get(NONE):
        rows.append({"id": NONE, "name": NO_BRAND, "count": counts[NONE]})
    return rows


def _product_row(p, fits) -> dict:
    return {"id": p.pk, "sku": p.sku, "name": p.name, "stock_qty": int(getattr(p, "stock_qty", 0) or 0),
            "maker": p.brand.name if p.brand_id else "", "fits": [f[1] for f in fits.get(p.pk, [])]}


def categories(tenant) -> dict:
    cats = list(Category.objects.for_tenant(tenant).filter(is_active=True).order_by("sort_order", "code"))
    counts = defaultdict(int)
    for cid in Product.objects.for_tenant(tenant).filter(is_active=True, is_virtual=False).values_list("category_id", flat=True):
        counts[cid] += 1
    return {"level": "categories",
            "items": [{"id": c.pk, "name": c.name, "kind": c.kind, "count": counts.get(c.pk, 0)} for c in cats]}


def browse(qs, category: Category, *, mode: str = "", brand: str = "", model: str = "") -> dict:
    """qs = 這家公司的商品(要帶 stock_qty,只在列到商品 / 型號那一層用);數品牌那一層用不帶庫存的,比較快。回下一層要列的東西。"""
    plain = Product.objects.for_tenant(category.tenant)
    kind = category.kind
    if kind == Category.Kind.DEVICE:
        return _device(plain if not brand else qs, category, brand)
    if kind == Category.Kind.ACCESSORY and mode != "maker":
        return _by_phone(qs if model or brand == NONE else plain, category, brand, model)
    return _by_maker(plain if not brand else qs, category, brand)


def _device(qs, category, brand):
    rows = _products(qs, category).select_related("brand", "phone_model", "series")
    if not brand:
        models = defaultdict(set)
        names = {}
        for p in rows:
            b = p.brand_id or NONE
            names[b] = p.brand.name if p.brand_id else ""
            models[b].add(p.phone_model_key or f"p{p.pk}")
        return {"level": "brands", "items": _brand_rows(category, {b: len(v) for b, v in models.items()}, names)}
    rows = rows.filter(brand=None) if brand == NONE else rows.filter(brand_id=brand)
    groups = {}
    for p in rows:
        key = p.phone_model_key or ""
        g = groups.setdefault(key, {"key": key, "name": p.phone_model_name if key else p.name, "sku_count": 0, "stock_qty": 0,
                                    "product_id": None if key else p.pk})
        g["sku_count"] += 1
        g["stock_qty"] += int(getattr(p, "stock_qty", 0) or 0)
    return {"level": "models", "items": sorted(groups.values(), key=lambda g: g["name"])}


def _by_phone(qs, category, brand, model):
    rows = list(_products(qs, category).select_related("brand"))
    fits = _fits([p.pk for p in rows])
    if not brand:
        counts, names = defaultdict(set), {}
        for p in rows:
            for _, _, bid, bname in fits.get(p.pk) or [(None, "", NONE, "")]:
                counts[bid or NONE].add(p.pk)
                names[bid or NONE] = bname
        # 依手機那一層的品牌是適用機型的品牌,不是類別底下掛的配件廠牌 → 不併類別的品牌清單
        items = sorted(({"id": b, "name": names[b], "count": len(v)} for b, v in counts.items() if b != NONE),
                       key=lambda r: (-r["count"], r["name"]))
        if counts.get(NONE):
            items.append({"id": NONE, "name": "未分", "count": len(counts[NONE])})
        return {"level": "brands", "mode": "phone", "items": items}
    if brand == NONE:
        # 沒掛適用機型的,或掛的機型沒有品牌的(上面就是這樣算進「未分」的)
        return _grouped([p for p in rows if not fits.get(p.pk) or any(not bid for _, _, bid, _ in fits[p.pk])], fits)
    if not model:
        models = defaultdict(set)
        names = {}
        for p in rows:
            for mid, mname, bid, _ in fits.get(p.pk, []):
                if str(bid) == brand:
                    models[mid or mname].add(p.pk)
                    names[mid or mname] = mname
        items = sorted(({"id": m, "name": names[m], "count": len(v)} for m, v in models.items()), key=lambda r: r["name"])
        return {"level": "models", "mode": "phone", "items": items}
    picked = [p for p in rows if any(str(mid or mname) == model and str(bid) == brand for mid, mname, bid, _ in fits.get(p.pk, []))]
    return _grouped(picked, fits)


def _grouped(products, fits) -> dict:
    """依手機最後一層:照配件廠牌分組(無品牌最後)。"""
    groups = defaultdict(list)
    for p in products[:LIMIT]:
        groups[p.brand.name if p.brand_id else ""].append(_product_row(p, fits))
    items = [{"maker": m or NO_BRAND, "products": sorted(v, key=lambda r: r["name"])}
             for m, v in sorted(groups.items(), key=lambda kv: (kv[0] == "", kv[0]))]
    return {"level": "products", "grouped": True, "total": len(products), "items": items}


def _by_maker(qs, category, brand):
    rows = _products(qs, category).select_related("brand")
    if not brand:
        counts, names = defaultdict(int), {}
        for bid, bname in rows.values_list("brand_id", "brand__name"):
            counts[bid or NONE] += 1
            names[bid or NONE] = bname or ""
        return {"level": "brands", "mode": "maker", "items": _brand_rows(category, counts, names)}
    rows = rows.filter(brand=None) if brand == NONE else rows.filter(brand_id=brand)
    total = rows.count()
    picked = list(rows.order_by("name")[:LIMIT])
    fits = _fits([p.pk for p in picked])
    return {"level": "products", "grouped": False, "total": total, "items": [_product_row(p, fits) for p in picked]}
