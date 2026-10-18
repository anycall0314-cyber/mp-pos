"""平台型號庫 → 一家公司的品號(M1-C;owner 2026-10-15「然後你幫我展開含中古機，2026出產的才有拆封機」)。

owner 定的:品況 = 全新、中古機(**中古機也分顏色**、**不展開「中古機(保固內)」**);**2026 年以後上市的手機再加「已拆封」**
(2026-10-16 改:「2026以後出的手機都要建立已拆封，後續新機上市都要，僅手機就好，其他類別不需要」;平板、手錶不建)。
**耳機、手環、其他穿戴**(2026-10-16 owner 選「只建全新、按數量」):只建全新、分顏色、**不記序號**(進貨、盤點照數量),
品名「型號 顏色 全新」(沒有容量那一格);放「穿戴」(還沒改的公司放「耳機/音訊」「穿戴/周邊」)。公司本來就在賣的那幾款放 `holds` 不建。
品名「型號 容量 顏色 品況」。只建主機的品號,不建配件 / 維修零件的佔位商品。
**不寫台版**(owner 2026-10-17:「手機平板穿戴幾乎百分之99以上一定是台版，不需要去特別多個欄位去填他是哪個國家版本，品名也不需要」);
以前建的品名有「台版」,比對有沒有建過時當成同一個(`bare_name`)。

- **一支手機在一家公司只有一個機型**:先用 `PhoneModel.device_uid` 對;沒對的照 `links`(人 / Jev 對好的:公司機型名稱 → 型號庫編號)寫上;
  名稱完全一樣(大小寫不算)的直接對。`holds` = 還沒對清楚、可能是公司某個舊機型的那幾支,**先不展開**(展開了會多一個同一支的機型,庫存拆兩半)。
- **公司已經有品號的機型**:容量 / 顏色照公司自己的(型號庫的寫法可能不一樣:「黑色」/「黑色鈦金屬」),只補缺的品況;型號庫多出來的容量 / 顏色列出來、不建。
- 新的機型:品牌照名稱找(沒有就建),系列 / 世代 / 後綴從型號名稱拆(組回來就是型號庫的名稱;開頭是數字的接品牌字)。
- **售價**(紅隊第 2 條):全新 / 已拆封只帶型號庫裡寫明是「原廠建議價 / 官網定價」、同一個容量的那一筆;其他都是 0。中古機 0(收購時一台一台定)。
- 一支一個交易:中途停掉,做好的留著,重跑接著做(品名已經有的不再建)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils.text import slugify

from . import brand_names
from .models import Brand, Category, Condition, DeviceModel, PhoneModel, PhoneSeries, Product
from .category_template import link_brand
from .phone_model import _smart_join
from .services_model_bundle import _get_or_create_phone_model

_REGION_WORD = re.compile(r"(?<!\S)(台版|臺版|台灣版)(?!\S)")
NEW, USED, OPENED = "全新", "中古機", "已拆封"


def bare_name(name: str) -> str:
    """比對品名有沒有建過用:拿掉「台版」(以前建的品名有寫)、空白併成一個。"""
    return " ".join(_REGION_WORD.sub(" ", name or "").split())
# 型號庫的類別 → 公司的類別(照順序找第一個有的):手錶、手環、耳機都進「穿戴」(owner 2026-10-16「都進穿戴」);
# 還沒改成穿戴的公司照舊放「手錶」「耳機/音訊」「穿戴/周邊」
CATEGORY_OF = {DeviceModel.Category.PHONE: ("手機",), DeviceModel.Category.TABLET: ("平板",),
               DeviceModel.Category.WATCH: ("穿戴", "手錶"), DeviceModel.Category.HEADPHONES: ("穿戴", "耳機/音訊"),
               DeviceModel.Category.BAND: ("穿戴", "穿戴/周邊"), DeviceModel.Category.OTHER: ("穿戴", "穿戴/周邊")}
# 只建全新、按數量(不記序號、沒有容量那一格)
BY_QTY = (DeviceModel.Category.HEADPHONES, DeviceModel.Category.BAND, DeviceModel.Category.OTHER)
ALL_CATEGORIES = tuple(CATEGORY_OF)
# 寫明是原廠 / 官網定價的才帶進全新的售價(紅隊第 2 條);順序 = 同一個容量好幾筆時先用哪一種
MSRP_KINDS = ("source_stated_manufacturer_msrp", "official_regular_catalog_price",
              "official_regular_catalog_price_not_verified_original_msrp")
OPENED_FROM = 2026   # 這一年以後上市的手機才建已拆封(owner 2026-10-16;平板、手錶不建)
NO_COLOR = "不分色"
NO_CAPACITY = "標準版"
SUFFIX_MAX = 30


class ExpandError(Exception):
    """整批不能做的原因(可以直接給人看)。"""


@dataclass
class Report:
    devices: int = 0
    new_models: int = 0
    linked: int = 0
    held: int = 0
    created: dict = field(default_factory=dict)      # {品況: 幾個}
    extra_variants: list = field(default_factory=list)  # (機型, 型號庫多的容量 / 顏色)
    problems: list = field(default_factory=list)

    def add(self, cond, n=1):
        self.created[cond] = self.created.get(cond, 0) + n


def conditions_for(device: DeviceModel, *, new_for_old: bool = True) -> list[str]:
    """這一支要展開哪幾種品況。`new_for_old=False`:草稿補進來的舊機(2018 以前)不建全新。"""
    if device.category in BY_QTY:
        return [NEW]
    out = [NEW, USED]
    if not new_for_old and (device.data or {}).get("origin") == "m1-draft":
        out = [USED]
    year = device.launched[:4]
    if device.category == DeviceModel.Category.PHONE and year.isdigit() and int(year) >= OPENED_FROM:
        out.insert(1, OPENED)
    return out


def capacities_for(device: DeviceModel) -> list[str]:
    data = device.data or {}
    if device.category in BY_QTY:
        return [""]
    if device.category == DeviceModel.Category.WATCH:
        base = "GPS" if device.brand.casefold() == "apple" else "藍牙"
        lte = "GPS+行動網路" if base == "GPS" else "LTE"
        return [base, lte] if "LTE" in (data.get("connectivity") or []) else [base]
    return list(data.get("capacities") or []) or [NO_CAPACITY]


def colors_for(device: DeviceModel) -> list[str]:
    return list(dict.fromkeys((device.data or {}).get("colors") or [])) or [NO_COLOR]


def msrp(device: DeviceModel, capacity: str) -> Decimal:
    rows = [p for p in (device.data or {}).get("prices") or [] if p.get("kind") in MSRP_KINDS
            and (p.get("storage") == capacity or (p.get("storage") is None and capacity in ("", NO_CAPACITY, "GPS", "藍牙")))]
    rows.sort(key=lambda p: MSRP_KINDS.index(p["kind"]))
    return Decimal(int(rows[0]["amount"])) if rows else Decimal(0)


def split_name(brand: str, name: str) -> tuple[str, int | None, str]:
    """型號名稱 → (系列, 世代, 後綴),照「新增手機型號」的組法組回來 = 原本的名稱(開頭是數字的前面接品牌)。
    系列 = 第一個含數字的字之前;那個字是純數字就是世代;其餘是後綴(超過 30 字就把前面的字併進系列)。"""
    words = name.split()
    at = next((i for i, w in enumerate(words) if re.search(r"\d", w)), len(words))
    series_words, rest = words[:at], words[at:]
    if not series_words:
        series_words = [brand]
    generation = None
    if rest and rest[0].isdigit() and len(rest[0]) <= 4:
        generation, rest = int(rest[0]), rest[1:]
    suffix = " ".join(rest)
    while len(suffix) > SUFFIX_MAX and generation is None and rest:
        series_words, rest = [*series_words, rest[0]], rest[1:]
        suffix = " ".join(rest)
    if len(suffix) > SUFFIX_MAX:
        raise ExpandError(f"{brand} {name}:型號名稱太長,拆不成系列 / 後綴")
    return " ".join(series_words), generation, suffix


def _brand(tenant, name: str) -> Brand:
    """照名字找這家公司的品牌(中文 / 英文 / 顯示名稱任一個一樣都算,`brand_names.find_brand`);沒有就建。"""
    found = brand_names.find_brand(tenant, name)
    if found is not None:
        return found
    return Brand.objects.create(tenant=tenant, code=brand_names.unique_code(tenant, name), name=name.strip())


def _series(tenant, brand: Brand, sname: str) -> PhoneSeries:
    key = sname.strip().casefold()
    for s in PhoneSeries.objects.for_tenant(tenant).filter(brand=brand):
        if (s.name or "").strip().casefold() == key:
            return s
    maxlen = PhoneSeries._meta.get_field("code").max_length or 20
    base = (slugify(f"{brand.code}-{sname}") or "series")[:maxlen]
    code, n = base, 1
    while PhoneSeries.objects.for_tenant(tenant).filter(code=code).exists():
        n += 1
        code = base[: maxlen - len(f"-{n}")] + f"-{n}"
    return PhoneSeries.objects.create(tenant=tenant, brand=brand, name=sname.strip(), code=code)


def name_key(name: str) -> str:
    """機型名稱只差空白 / 大小寫的算同一個(「Galaxy Tab S 10 Ultra」=「Galaxy Tab S10 Ultra」;公司的舊機型是系列 + 世代 + 後綴接空白組的)。"""
    return re.sub(r"\s+", "", name or "").casefold()


def _model_name(series_name: str, generation, suffix) -> str:
    """跟 `phone_model.compute_phone_model_name` 有系列時的組法一樣(試算時系列還沒存,不能用那一支)。"""
    return _smart_join([series_name, str(generation) if generation else "", suffix or ""]).strip()


def _lookups(tenant):
    conds = {c.name: c for c in Condition.objects.for_tenant(tenant).filter(is_active=True, name__in=[NEW, USED, OPENED])}
    missing = [n for n in (NEW, USED, OPENED) if n not in conds]
    if missing:
        raise ExpandError("這家公司沒有這幾種品況:" + "、".join(missing))
    cats = {c.name: c for c in Category.objects.for_tenant(tenant).filter(name__in={n for names in CATEGORY_OF.values() for n in names})}
    return conds, cats


def apply_links(tenant, links: dict[str, str], *, confirm: bool) -> list[str]:
    """把對好的(公司機型名稱 → 型號庫編號)寫進 `device_uid`。回問題(對不到的名稱、一支對到兩個機型、已經對到別支)。"""
    problems = []
    models = {pm.name.casefold(): pm for pm in PhoneModel.objects.for_tenant(tenant)}
    devices = set(DeviceModel.objects.filter(uid__in=links.values()).values_list("uid", flat=True))
    # 公司裡已經對好的也算(複審 P1:分兩次對照,第二次把另一個機型對到同一支)
    taken = {pm.device_uid: pm.name for pm in models.values() if pm.device_uid}
    used = {}
    for name, uid in links.items():
        pm = models.get(name.casefold())
        if pm is None:
            problems.append(f"公司沒有這個機型:{name}")
        elif uid not in devices:
            problems.append(f"型號庫沒有這一支:{name} → {uid}")
        elif pm.device_uid and pm.device_uid != uid:
            problems.append(f"「{name}」已經對到另一支,不改")
        elif uid in used:
            problems.append(f"同一支對到兩個機型:{used[uid]}、{name}")
        elif taken.get(uid, pm.name) != pm.name:
            problems.append(f"這一支已經對到「{taken[uid]}」,不能再對到「{name}」")
        else:
            used[uid] = name
    if problems or not confirm:
        return problems
    for name, uid in links.items():
        pm = models[name.casefold()]
        if pm.device_uid != uid:
            pm.device_uid = uid
            pm.save(update_fields=["device_uid", "updated_at"])
    return []


def expand(tenant, *, categories=ALL_CATEGORIES, links=None, holds=(), new_for_old=True,
           confirm=False, uids=None, add_variants=()) -> Report:
    """展開。confirm=False 只算(不寫任何東西)。寫之前先跑 `apply_links`;試算時 `links` 照算(還沒寫進去)。
    `uids` = 只展開這幾支(自動更新加進來的);`add_variants` = 這幾支型號庫多出來的容量 / 顏色也建
    (自動更新盯新機時用:那幾個品號原本就是照型號庫的寫法建的,不會跟公司自己的寫法撞)。"""
    conds, cats = _lookups(tenant)
    held = set(holds)
    devices = DeviceModel.objects.filter(is_active=True, category__in=categories)
    if uids is not None:
        devices = devices.filter(uid__in=list(uids))
    devices = list(devices.order_by("category", "brand", "name"))
    models = list(PhoneModel.objects.for_tenant(tenant))
    by_uid = {pm.device_uid: pm for pm in models if pm.device_uid}
    # 還沒對的機型照「只差空白也算同一個」查;公司自己有兩個只差空白的 → 那個名稱不自動對(看不出是哪一個)
    by_name, twins = {}, set()
    for pm in models:
        if not pm.device_uid:
            key = name_key(pm.name)
            twins.update([key] if key in by_name else [])
            by_name[key] = pm
    names = {name_key(pm.name): pm for pm in models}   # 全部機型(含已經對到別支的):新建之前要看會不會撞
    for name, uid in (links or {}).items():
        pm = by_name.pop(name_key(name), None)
        if pm is not None and uid not in by_uid:
            by_uid[uid] = pm
    existing_names = {bare_name(n) for n in Product.objects.for_tenant(tenant).values_list("name", flat=True)}
    report = Report()
    for d in devices:
        if d.uid in held:
            report.held += 1
            continue
        category = next((cats[n] for n in CATEGORY_OF[d.category] if n in cats), None)
        if category is None:
            report.problems.append(f"這家公司沒有「{CATEGORY_OF[d.category][0]}」類別:{d}")
            continue
        report.devices += 1
        one = _One(tenant, d, category, conds, by_uid, by_name, existing_names, new_for_old, confirm, twins, names,
                   grow=d.uid in set(add_variants))
        try:
            if confirm:
                with transaction.atomic():
                    one.run()
            else:
                one.run()
        except (ExpandError, IntegrityError) as exc:
            report.problems.append(f"{d}:{exc}")
            continue
        one.merge_into(report)
    return report


class _One:
    """一支型號展開到這家公司。結果先記在自己身上,整支成功才併進報告、才更新查表(失敗的那一支整個收回)。"""

    def __init__(self, tenant, d, category, conds, by_uid, by_name, existing_names, new_for_old, confirm, twins=(), names=None,
                 grow=False):
        self.tenant, self.d, self.category, self.conds = tenant, d, category, conds
        self.by_uid, self.by_name, self.existing_names = by_uid, by_name, existing_names
        self.twins, self.names_all = set(twins), names if names is not None else {}
        self.new_for_old, self.confirm, self.grow = new_for_old, confirm, grow
        self.created: dict = {}
        self.names: list = []
        self.linked = self.new_model = False
        self.extra = None
        self.pm = None

    def run(self):
        d, tenant, confirm = self.d, self.tenant, self.confirm
        qty = d.category in BY_QTY
        pm = self.by_uid.get(d.uid)
        if pm is None:
            sname, generation, suffix = split_name(d.brand, d.name)
            model_name = _model_name(sname, generation, suffix)
            if not model_name:
                raise ExpandError("型號名稱是空的")
            # 名稱一樣(只差空白 / 大小寫)的舊機型 = 同一支:對上去
            keys = {name_key(d.name), name_key(model_name)}
            if keys & self.twins:
                raise ExpandError("公司有兩個只差空白的機型,看不出是哪一個,先不展開")
            pm = next((self.by_name[k] for k in keys if k in self.by_name), None)
            if pm is not None:
                self.linked = True
            else:
                clash = next((self.names_all[k] for k in keys if k in self.names_all), None)
                if clash is not None:
                    # 已經對到別支、名稱卻只差空白:建下去就是同一個名字兩個機型,先不建
                    raise ExpandError(f"名稱跟公司的「{clash.name}」只差空白,它已經對到型號庫另一支")
        if pm is not None:
            brand, series, generation, suffix, model_name = pm.brand, pm.series, pm.generation, pm.model_suffix, pm.name
            have = Product.objects.for_tenant(tenant).filter(phone_model=pm, requires_serial=not qty)
            have = list((have if qty else have.exclude(capacity="")).values_list("capacity", "color"))
        else:
            brand = _brand(tenant, d.brand) if confirm else None
            series = _series(tenant, brand, sname) if confirm else None
            have = []
        if have:
            caps = list(dict.fromkeys(c for c, _ in have))
            cols = list(dict.fromkeys(c for _, c in have if c)) or [NO_COLOR]
            extra = [c for c in capacities_for(d) if c not in caps] + [c for c in colors_for(d) if c not in cols]
            if self.grow:
                caps += [c for c in capacities_for(d) if c not in caps]
                cols += [c for c in colors_for(d) if c not in cols and c != NO_COLOR]
                cols = [c for c in cols if c != NO_COLOR] or [NO_COLOR]
            elif extra:
                self.extra = (model_name, extra)
        else:
            caps, cols = capacities_for(d), colors_for(d)
        todo = []
        for cname in conditions_for(d, new_for_old=self.new_for_old):
            cond = self.conds[cname]
            for cap in caps:
                for col in cols:
                    name = " ".join(x for x in (model_name, cap, col, cond.name) if x)
                    if bare_name(name) not in self.existing_names:
                        todo.append((cond, cap, col, name))
        if pm is None and not todo:
            return
        if confirm:
            if pm is None:
                pm = _get_or_create_phone_model(tenant, model_name, brand, series, generation, suffix)
                self.new_model = True
            if pm.device_uid and pm.device_uid != d.uid:
                raise ExpandError(f"機型「{model_name}」已經對到型號庫另一支")
            if pm.device_uid != d.uid:
                pm.device_uid = d.uid
                pm.save(update_fields=["device_uid", "updated_at"])
        elif pm is None:
            self.new_model = True
        self.pm = pm
        if confirm and todo and brand is not None:
            link_brand(self.category, brand)   # 品牌掛到類別底下(類別 → 品牌 → 型號)
        for cond, cap, col, name in todo:
            if confirm:
                Product.objects.create(
                    tenant=tenant, category=self.category, name=name,
                    spec=" ".join(x for x in (cap, col, cond.name) if x),
                    capacity=cap, color=col, phone_model=pm, brand=brand, series=series,
                    generation=generation or None, model_suffix=suffix or "", condition=cond,
                    is_secondhand=cond.is_secondhand, requires_serial=not qty,
                    list_price=Decimal(0) if cond.is_secondhand else msrp(d, cap),
                    accessory_type=Product.AccessoryType.NONE, warehouse_type=Product.WarehouseType.PRODUCT,
                )
            self.names.append(name)
            self.created[cond.name] = self.created.get(cond.name, 0) + 1

    def merge_into(self, report):
        for k, v in self.created.items():
            report.add(k, v)
        report.linked += self.linked
        report.new_models += self.new_model
        if self.extra:
            report.extra_variants.append(self.extra)
        self.existing_names.update(bare_name(n) for n in self.names)
        if self.pm is not None and self.pm.pk:
            self.by_uid[self.d.uid] = self.pm
            self.by_name.pop(name_key(self.pm.name), None)
            self.names_all[name_key(self.pm.name)] = self.pm
