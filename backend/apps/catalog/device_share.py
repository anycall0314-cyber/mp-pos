"""配件跨型號共用(V1;owner 2026-10-17 問「當代建立時，不會知道下代名稱為何…但是可能共用配件，後續該怎麼維護」,
10-18 同意「新機出來時在型號庫設一次『配件跟上一支一樣』」並補「玻璃貼也有可能共用」)。

- 平台在型號庫的新機設「配件跟哪一支一樣」(`DeviceShare`),**螢幕 / 機身分開勾**(iPhone 16 的玻璃貼跟 15 一樣、殼不一樣)。
  同一類(手機 / 平板 / 手錶…)才可以。
- 每家店的配件類別跟著哪一個:`Category.shares_by`(螢幕 / 機身 / 不共用;空的 = 照類別名稱判斷,`part_of`)。
- **只做新機沿用舊機**:那幾類裡適用舊機的配件,加上新機;不把舊機補到只寫了新機的配件上(紅隊:專為新機進的殼不能變成舊機也能賣)。
- 什麼時候加(只有這三個時候,所以店裡拿掉的不會被加回來):設好的當下、勾了新的一格(只加新勾的那一格)、
  某家店之後才有這兩支其中一支機型(展開 / 每天自動新增新機時,`apply_for`)。
- **取消只是之後不再加,已經加上的不收回**(紅隊:收回會讓昨天搜得到的今天不見,店員不會幫忙核對)。
- 會接著傳下去:Air 9 跟 Air 8 一樣、Air 8 跟 Air 7 一樣 → Air 7 的配件加上 Air 8 的那一刻,也加上 Air 9(只傳剛加上的那幾個)。
- 每一家只動自己店裡的商品;還原中的公司不動(整個不做、講是哪一家)。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.db.models import Q

from .models import Category, DeviceModel, DeviceShare, PhoneModel, Product, ProductRelation

SCREEN, BODY = Category.SharesBy.SCREEN.value, Category.SharesBy.BODY.value
PART_LABELS = {SCREEN: "螢幕", BODY: "機身"}
# 照類別名稱判斷(店家沒有自己選的時候):鏡頭貼跟著機身(鏡頭位置);玻璃貼、保護貼跟著螢幕;殼、套、背蓋跟著機身;其他(維修料、包膜…)不共用
_BODY_FIRST = ("鏡頭",)
_SCREEN_WORDS = ("玻璃", "保護貼", "螢幕")
_BODY_WORDS = ("殼", "套", "背蓋", "背貼")


class ShareError(Exception):
    """設不了(原因可以直接給人看)。"""


def guess_part(name: str) -> str:
    name = name or ""
    if any(w in name for w in _BODY_FIRST):
        return BODY
    if any(w in name for w in _SCREEN_WORDS):
        return SCREEN
    if any(w in name for w in _BODY_WORDS):
        return BODY
    return ""


def part_of(category) -> str:
    """這一類的配件跟著新機的哪一個一樣:"screen" / "body" / ""(不共用)。只有配件類別有。"""
    if category is None or category.holds_devices or not category.needs_host_model:
        return ""
    if category.shares_by:
        return "" if category.shares_by == Category.SharesBy.NONE else category.shares_by
    return guess_part(category.name)


def parts_of(rule: DeviceShare) -> set[str]:
    return {p for p, on in ((SCREEN, rule.screen), (BODY, rule.body)) if on}


@dataclass
class Result:
    tenants: set = field(default_factory=set)
    products: set = field(default_factory=set)   # (公司, 商品):加上了至少一支新機的配件

    def as_dict(self) -> dict:
        return {"tenants": len(self.tenants), "products": len(self.products)}


def _models(tenant_id, uids) -> dict:
    return {pm.device_uid: pm for pm in PhoneModel.objects.filter(tenant_id=tenant_id, device_uid__in=list(uids))}


def _fitting(tenant_id, pm):
    """適用這個機型的配件(關係掛在機型上,或舊資料只記了機型 key)。"""
    return ProductRelation.objects.filter(tenant_id=tenant_id).filter(
        Q(host_model=pm) | Q(host_model_key=pm.match_key)).values("accessory_product_id")


def _spread(tenant_id, rule, parts, out: Result, *, only=None, seen=frozenset()) -> None:
    """這一家:`rule` 的舊機適用、類別跟著 `parts` 的配件加上新機;`only` = 只看這幾個商品(往下傳的時候)。"""
    pms = _models(tenant_id, {rule.device_uid, rule.same_as_uid})
    new, old = pms.get(rule.device_uid), pms.get(rule.same_as_uid)
    if new is None or old is None or not parts:
        return
    cats = [c.pk for c in Category.objects.filter(tenant_id=tenant_id, needs_host_model=True, holds_devices=False)
            if part_of(c) in parts]
    if not cats:
        return
    todo = Product.objects.filter(tenant_id=tenant_id, category_id__in=cats, pk__in=_fitting(tenant_id, old))
    if only is not None:
        todo = todo.filter(pk__in=list(only))
    # 鎖住那幾個商品(照編號;跟改商品的人排隊)才看哪幾個還沒有新機,看完才加
    ids = list(todo.select_for_update(no_key=True).order_by("pk").values_list("pk", flat=True))
    have = set(_fitting(tenant_id, new).filter(accessory_product_id__in=ids).values_list("accessory_product_id", flat=True))
    ids = [i for i in ids if i not in have]
    if not ids:
        return
    ProductRelation.objects.bulk_create(
        [ProductRelation(tenant_id=tenant_id, accessory_product_id=i, host_model=new, host_model_key=new.match_key) for i in ids],
        ignore_conflicts=True,
    )
    out.tenants.add(tenant_id)
    out.products.update((tenant_id, i) for i in ids)
    seen = seen | {rule.pk}
    for down in DeviceShare.objects.filter(same_as_uid=rule.device_uid).exclude(pk__in=seen).order_by("pk"):
        _spread(tenant_id, down, parts & parts_of(down), out, only=ids, seen=seen)


def _tenants_with(uid) -> list[int]:
    return sorted(set(PhoneModel.objects.filter(device_uid=uid).values_list("tenant_id", flat=True)))


def apply(rule: DeviceShare, parts: set[str], *, tenant_ids=None) -> Result:
    """把 `rule` 的這幾格套到有新機的每一家(或指定的那幾家)。一家一個交易。"""
    out = Result()
    for tid in tenant_ids if tenant_ids is not None else _tenants_with(rule.device_uid):
        with transaction.atomic():
            _spread(tid, rule, parts, out)
    return out


def apply_for(tenant, uid: str) -> int:
    """這家公司剛有(或剛對上)型號庫的 `uid` 這一支:跟它有關的每一條都對這一家套一次。回加上了幾個配件。
    先套「它是新機」的(從舊機帶過來),再套「它是舊機」的(帶到之後的新機)。呼叫的人自己包交易。"""
    out = Result()
    rules = list(DeviceShare.objects.filter(device_uid=uid).order_by("pk")) + \
        list(DeviceShare.objects.filter(same_as_uid=uid).exclude(device_uid=uid).order_by("pk"))
    for rule in rules:
        _spread(tenant.pk, rule, parts_of(rule), out)
    return len(out.products)


def _device(uid: str) -> DeviceModel:
    d = DeviceModel.objects.filter(uid=uid).first() if uid else None
    if d is None:
        raise ShareError("型號庫沒有這一支")
    return d


def _not_restoring(uid: str) -> None:
    from apps.backup.models import TenantMaintenance

    busy = (TenantMaintenance.objects.filter(active=True, tenant_id__in=_tenants_with(uid))
            .select_related("tenant").order_by("tenant_id").first())
    if busy is not None:
        raise ShareError(f"「{busy.tenant.name}」正在還原資料,等還原完再設")


def set_rule(device_uid: str, same_as_uid: str, *, screen: bool, body: bool, user=None) -> dict:
    """設(或改)一條:新機 `device_uid` 的配件跟 `same_as_uid` 一樣。新勾的那幾格當下套到每一家;拿掉的格只是之後不再加。
    回 {"rule": 那一條, "tenants": 加到幾家, "products": 幾個配件}。"""
    new, old = _device(device_uid), _device(same_as_uid)
    if new.uid == old.uid:
        raise ShareError("不能跟自己一樣")
    if new.category != old.category:
        raise ShareError(f"要同一類才能共用:{new} 是{new.get_category_display()}、{old} 是{old.get_category_display()}")
    if not (screen or body):
        raise ShareError("螢幕、機身至少勾一格;都不一樣就取消這一條")
    _not_restoring(new.uid)
    try:
        with transaction.atomic():
            rule = DeviceShare.objects.select_for_update().filter(device_uid=new.uid, same_as_uid=old.uid).first()
            before = parts_of(rule) if rule else set()
            if rule is None:
                rule = DeviceShare(device_uid=new.uid, same_as_uid=old.uid, created_by=user)
            rule.screen, rule.body = bool(screen), bool(body)
            rule.save()
    except IntegrityError:
        raise ShareError("同一條剛好有人在設,請再按一次") from None
    added = apply(rule, parts_of(rule) - before)
    return {"rule": rule, **added.as_dict()}


def remove_rule(pk: int) -> None:
    """取消一條:之後不再加;已經加到各家店的不收回。"""
    if not DeviceShare.objects.filter(pk=pk).delete()[0]:
        raise ShareError("沒有這一條")
