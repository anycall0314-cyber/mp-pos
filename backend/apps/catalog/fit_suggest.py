"""新增配件時照品名先勾好適用機型(V2;owner 2026-10-18 我說「新增配件時，系統先照品名把適用機型勾好」,他回「你一路做完」)。

- 品名照店內寫法讀(`9H/IMOS/IP15PM`、`皮套/AIR4-7/PRO11`;規則在 `accessory_names.py`,跟整理舊商品、商品搜尋同一套),
  讀得出來的機型就是建議;寫得不夠清楚的(只寫 AIR、Pro 11 沒寫年份)不猜。
- 型號庫設了配件共用的(`device_share.py`):建議裡的機型、與表單上已經挑的機型,這一類跟著的那一格是同一套的新機也一起建議。
- 只建議、不寫任何東西:表單上看得到、可以拿掉,按儲存才存(`related_host_keys`)。
"""
from __future__ import annotations

from . import accessory_names as an
from . import device_share
from .brand_names import catalog_name
from .models import DeviceModel, PhoneModel


def tenant_index(tenant) -> an.ModelIndex:
    """這家公司啟用中的機型做成店內寫法的查表(型號庫的種類與上市年份一起給:平板只收平板、新 iPad 算第幾代)。"""
    rows = list(PhoneModel.objects.for_tenant(tenant).filter(is_active=True)
                .values_list("pk", "name", "brand__name", "brand__name_zh", "brand__name_en", "device_uid"))
    info = {uid: (cat, launched) for uid, cat, launched in
            DeviceModel.objects.filter(uid__in=[r[5] for r in rows if r[5]]).values_list("uid", "category", "launched")}
    return an.build_index([(pk, name, catalog_name(b or "", zh or "", en or ""), *info.get(uid, ("", "")))
                           for pk, name, b, zh, en, uid in rows])


def _rows(ids) -> list[dict]:
    return [{"model_key": m.match_key, "model_name": m.name}
            for m in PhoneModel.objects.filter(pk__in=list(ids)).order_by("name")]


def suggest(tenant, *, name: str = "", category=None, keys=()) -> dict:
    """回 {"models": 從品名讀到的機型, "shared": 共用設定帶出來的新機, "unsure": 寫得不夠清楚、沒猜的那幾段}。
    `keys` = 表單上已經挑的機型(機型 key);`category` = 這個配件的類別(決定跟螢幕還是機身)。"""
    found: set[int] = set()
    unsure: list[str] = []
    if name.strip():
        parsed = an.parse(name, tenant_index(tenant))
        found, unsure = set(parsed.models), list(parsed.unsure)
    picked = set(PhoneModel.objects.for_tenant(tenant).filter(match_key__in=[k.strip().lower() for k in keys if k.strip()])
                 .values_list("pk", flat=True))
    part = device_share.part_of(category)
    shared = device_share.followers(tenant.pk, found | picked, part) - found - picked
    return {"models": _rows(found), "shared": _rows(shared), "unsure": unsure}
