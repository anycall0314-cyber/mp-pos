"""一家公司現有商品的一次整理(M1-E 第二段,2026-10-16)。

owner 定的:「充電/線材」跟傳輸線「同一類,改名傳輸線」;手錶、手環、藍牙耳機「都進穿戴」;
配件記**配件廠牌**(`Product.brand`)與**適用機型**(`ProductRelation`),資料只在品名裡。紅隊:這是一家的一次搬家、不是產品功能。

順序(一個交易;沒有 `confirm` 就整個退回 = 試算):
1. (可選)類別的種類照另一家同名的類別(測試通訊行照手機玩家)。
2. 改名:充電/線材 → 傳輸線、手錶 → 穿戴(新的名字已經有就不改)。
3. 搬到穿戴:耳機/音訊、穿戴/周邊裡**型號庫的耳機、手環、手錶**(規則:那一支在型號庫的種類),
   加上 `answers["wear"]` 列的舊品名(Jev 判的、有把握的);品牌掛到穿戴底下,舊類別底下沒有商品的那幾個品牌拿掉。
4. 廠牌:還沒有品牌的,照品名機型前面的片段 —— 在 `answers["makers"]` 裡的(Jev 判的、有把握的);
   一般類別(與搬進穿戴的舊品名)的手機品牌字(`SAM`、`三星`)也算(原廠的線材、耳機)。已經有品牌的不動。
5. 適用機型:配件類別、還沒有適用機型的,照 `accessory_names` 的查表(只有規則,不猜);
   `answers["fits"]`(`{品名: [機型名稱]}`)= owner 指定的,照指定的掛(查表沒把握的那幾個 iPad 之類);
   已經掛了一部分的也補上缺的那幾台,已經掛的不拿掉。

可以重跑:改過的、有品牌的、有適用機型的都跳過(owner 指定的只補還沒掛的)。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.db import transaction

from . import accessory_names as an
from .category_template import link_brand
from .fit_suggest import tenant_index
from .models import Brand, Category, CategoryBrand, DeviceModel, PhoneModel, Product, ProductRelation

RENAMES = (("充電/線材", "傳輸線"), ("手錶", "穿戴"))
WEAR = "穿戴"
WEAR_FROM = ("耳機/音訊", "穿戴/周邊")
WEAR_KINDS = {DeviceModel.Category.HEADPHONES, DeviceModel.Category.BAND, DeviceModel.Category.WATCH,
              DeviceModel.Category.OTHER}

# 手機品牌群組 → 沒有現成品牌時用的名稱(有的話用公司裡已經有的那一個)
GROUP_NAMES = {
    "APPLE": "Apple", "SAMSUNG": "Samsung", "OPPO": "OPPO", "VIVO": "vivo", "XIAOMI": "Xiaomi", "REDMI": "Xiaomi",
    "POCO": "POCO", "REALME": "realme", "SONY": "Sony", "GOOGLE": "Google", "ASUS": "ASUS", "HUAWEI": "HUAWEI",
    "HTC": "HTC", "LG": "LG", "MOTO": "Motorola", "NOKIA": "Nokia", "SHARP": "SHARP", "SUGAR": "SUGAR",
    "HONOR": "HONOR", "NOTHING": "Nothing", "BENTEN": "Benten", "LENOVO": "Lenovo", "INFOCUS": "InFocus",
    "ONEPLUS": "OnePlus",
}


class TidyError(Exception):
    pass


@dataclass
class Report:
    kinds: list[str] = field(default_factory=list)
    renamed: list[str] = field(default_factory=list)
    moved: Counter = field(default_factory=Counter)        # 從哪個類別搬了幾個
    makers: Counter = field(default_factory=Counter)       # 廠牌 → 幾個商品
    fit_products: int = 0
    fit_links: int = 0
    no_fit: int = 0                                        # 配件類別裡對不到機型的
    unsure: list[tuple[str, str, str]] = field(default_factory=list)   # (類別, 品名, 寫得不夠清楚的那一段)
    rows: list[tuple[str, str, str, str]] = field(default_factory=list)   # (類別, 品名, 做了什麼, 內容)


def _maker_of(segments, makers: set[str], stop: int | None, phone_brands: bool):
    """品名機型前面(沒有機型的看前四段)的第一個廠牌。回 (廠牌字, 是不是手機品牌群組)。

    `phone_brands`:手機品牌字也算廠牌(一般類別:`旅充/三星/EP-T2510` 是三星原廠)。
    但「台」開頭的種類(台傳、台旅、台車、台座、台耳)是副廠 —— 手機玩家的品名裡,台X 後面寫得出廠牌的全是副廠牌
    (`台傳/ANKER`、`台旅/REMAX`、`台耳/LDNIO`);`台座/HTC/快充` 的 HTC 是「給 HTC 用」,不是 HTC 做的。"""
    if segments and segments[0].startswith("台"):
        phone_brands = False
    last = min(stop if stop is not None else 3, 4)
    for i, seg in enumerate(segments[: last + 1]):
        up = seg.strip().upper()
        if phone_brands:
            g = an.BRAND_ALIASES.get(up) or an._split_brand(seg)[0]
            if g:
                return g, True
        if up in makers:
            return seg.strip(), False
    return None, False


def _group_brand_names(tenant) -> dict[str, str]:
    """公司裡已經有的品牌 → 群組(`Samsung` → SAMSUNG);同一群組有好幾個,取商品最多的。"""
    out, best = {}, {}
    for b in Brand.objects.for_tenant(tenant):
        keys = [k.strip().casefold() for k in (b.name_en, b.name, b.name_zh)]   # 補了中文名(「三星 Samsung」)也認得
        g = next((an.CATALOG_BRAND_GROUP[k] for k in keys if k in an.CATALOG_BRAND_GROUP), None)
        if not g:
            continue
        n = b.products.count()
        if n > best.get(g, -1):
            out[g], best[g] = b.name, n
    if "XIAOMI" in out:
        out["REDMI"] = out["XIAOMI"]   # 型號庫的紅米大多掛在 Xiaomi 底下;舊品名的紅米耳機跟著放一起
    return out


def tidy(tenant, answers: dict, *, kinds_from=None, confirm: bool = False) -> Report:
    from .device_expand import _brand

    report = Report()
    makers = {str(t).strip().upper() for t in answers.get("makers") or []}
    wear_names = {str(n).strip() for n, v in (answers.get("wear") or {}).items() if v in ("earbuds", "watch")}
    with transaction.atomic():
        cats = lambda: {c.name.strip(): c for c in Category.objects.for_tenant(tenant)}   # noqa: E731

        # 1. 類別的種類照另一家
        if kinds_from is not None:
            src = {c.name.strip(): c for c in Category.objects.for_tenant(kinds_from)}
            renamed = dict(RENAMES)
            for name, c in cats().items():
                # 另一家可能已經整理過、改了名(手機玩家先跑,它的「充電/線材」已經是「傳輸線」)
                s = src.get(name) or src.get(renamed.get(name, ""))
                if s and (c.holds_devices, c.needs_host_model) != (s.holds_devices, s.needs_host_model):
                    Category.objects.filter(pk=c.pk).update(holds_devices=s.holds_devices, needs_host_model=s.needs_host_model)
                    report.kinds.append(f"{name}:{c.kind} → {s.kind}")

        # 2. 改名
        for old, new in RENAMES:
            now = cats()
            if old in now and new not in now:
                Category.objects.filter(pk=now[old].pk).update(name=new)
                report.renamed.append(f"{old} → {new}")

        # 3. 搬到穿戴
        now = cats()
        wear = now.get(WEAR)
        moved_brands = defaultdict(Counter)    # 舊類別 → 搬走的品牌
        moved_ids = set()
        if wear is not None and wear.holds_devices:
            uids = {d.uid for d in DeviceModel.objects.filter(category__in=WEAR_KINDS)}
            for src_name in WEAR_FROM:
                src = now.get(src_name)
                if src is None:
                    continue
                for p in Product.objects.for_tenant(tenant).filter(category=src).select_related("phone_model"):
                    by_catalog = p.phone_model_id and p.phone_model.device_uid in uids
                    if not by_catalog and p.name.strip() not in wear_names:
                        continue
                    p.category = wear
                    p.save(update_fields=["category"])
                    moved_ids.add(p.pk)
                    report.moved[src_name] += 1
                    report.rows.append((WEAR, p.name, "搬到穿戴", src_name + ("" if by_catalog else "(舊品名)")))
                    if p.brand_id:
                        moved_brands[src.pk][p.brand_id] += 1
            linked = Counter()
            for c in moved_brands.values():
                linked.update(c)
            for bid, _ in linked.most_common():
                link_brand(wear, Brand.objects.get(pk=bid))
            for src_pk, brands in moved_brands.items():
                for bid in brands:
                    if not Product.objects.filter(category_id=src_pk, brand_id=bid).exists():
                        CategoryBrand.objects.filter(category_id=src_pk, brand_id=bid).delete()

        # 4. 廠牌 + 5. 適用機型
        models = list(PhoneModel.objects.for_tenant(tenant).filter(is_active=True).select_related("brand"))
        idx = tenant_index(tenant)   # 同一批機型(這家公司啟用中的);型號庫的種類與上市年份一起給(新 iPad 算第幾代)
        key_of = {m.pk: m.match_key for m in models}
        by_name = {an.norm(m.name): m.pk for m in models}
        fixed, missing = {}, []
        for pname, names in (answers.get("fits") or {}).items():
            ids = [by_name.get(an.norm(n)) for n in names]
            missing += [n for n, i in zip(names, ids) if i is None]
            fixed[str(pname).strip()] = set(i for i in ids if i)
        if missing:
            raise TidyError("指定的適用機型找不到:" + "、".join(sorted(set(missing))))
        group_names = _group_brand_names(tenant)
        have = defaultdict(set)   # 配件 → 已經掛的機型
        for a, h in ProductRelation.objects.for_tenant(tenant).values_list("accessory_product_id", "host_model_id"):
            have[a].add(h)
        per_cat = defaultdict(lambda: defaultdict(list))   # 類別 → 廠牌名稱 → 商品
        new_rel = []
        for c in Category.objects.for_tenant(tenant):
            kind = c.kind
            qs = Product.objects.for_tenant(tenant).filter(category=c, is_active=True, is_virtual=False)
            if kind == Category.Kind.DEVICE:
                qs = qs.filter(pk__in=moved_ids)    # 主機類別只處理剛搬進來的舊品名(型號庫的本來就有品牌)
            for p in qs.select_related("phone_model"):
                if p.phone_model_id and p.phone_model.device_uid:
                    continue
                parsed = an.parse(p.name, idx)
                if p.brand_id is None:
                    general = kind != Category.Kind.ACCESSORY
                    maker, is_group = _maker_of(parsed.segments, makers, parsed.first_model_at, general)
                    if maker:
                        name = (group_names.get(maker) or GROUP_NAMES.get(maker, maker)) if is_group else maker
                        per_cat[c][name].append(p)
                pinned = fixed.get(p.name.strip())
                if kind == Category.Kind.ACCESSORY and (pinned or p.pk not in have):
                    # owner 指定的:已經掛了一部分的也補上缺的(`AIR4-7/PRO11` 的 Air 掛了、Pro 11 那一半沒掛);不拿掉已經掛的
                    fits = pinned - have[p.pk] if pinned else parsed.models
                    if fits:
                        report.fit_products += 1
                        for mid in sorted(fits):
                            new_rel.append(ProductRelation(tenant=tenant, host_model_id=mid, host_model_key=key_of[mid],
                                                           accessory_product=p))
                        how = "適用機型(指定)" if pinned else "適用機型"
                        report.rows.append((c.name, p.name, how, "、".join(sorted(idx.names[m] for m in fits))))
                    elif not pinned:
                        report.no_fit += 1
                        if parsed.unsure:
                            report.unsure.append((c.name, p.name, "、".join(parsed.unsure)))
        for c, by_name in per_cat.items():
            for name, products in sorted(by_name.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                brand = _brand(tenant, name)
                Product.objects.filter(pk__in=[p.pk for p in products]).update(brand=brand)
                link_brand(c, brand)
                report.makers[brand.name] += len(products)
                report.rows += [(c.name, p.name, "廠牌", brand.name) for p in products]
        ProductRelation.objects.bulk_create(new_rel, batch_size=500)
        report.fit_links = len(new_rel)
        if not confirm:
            transaction.set_rollback(True)
    return report
