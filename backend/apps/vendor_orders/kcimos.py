"""kcimos(imos 保護貼的經銷下單網站)的商品快照 → 平台的半自動廠商價目表。

owner 2026-10-13:「再來我想做串接kcimos，帳號有三個，做手機玩家的串接就好」「未稅是我的實際成本」「Kcimos只有手機玩家看得到沒錯」

kcimos 沒有 API(舊式網頁、登入要驗證碼)。這裡只做「把抓下來的快照變成價目表」,**不連 kcimos**:
- 快照檔(`kcimos完整商品.json`,格式 `kcimos-catalog-snapshot/1.0`)是某一天、某一個登入帳號看到的商品與進價。
  **進價是那個帳號的,不能讓別家經銷商看到** → 廠商一建就是「只給指定的公司」(`Vendor.is_private`),跟價目在同一個交易裡寫進去。
- 料號 = `KCIMOS-<網站的商品編號>`(叫貨、連品名、收貨都認它);品名照網站原文(之後自動帶入購物車要對得回去)。
- 參考價 = 網站的採購價(未稅;owner:未稅就是他的成本)。**9999 以上(沒報價)與 0 元的不帶參考價** —— 收貨時一定要自己填實際單價。
- 「停產 / 請勿下單」的匯成停用(不能叫)。「缺貨請預購」「售完為止」會變,不匯(快照是舊的,寫上去反而誤導)。
- 可以重跑:料號一樣的更新、沒有的新增;快照裡不見的不動(只能停用、不能刪,叫貨單與對照靠料號認它)。
"""
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.tenants.models import Tenant

from . import vendors
from .models import Vendor, VendorItem

SCHEMA = "kcimos-catalog-snapshot/1.0"
CODE = "kcimos"
# 下單網站(沒有加密、沒有 API;流程實測在 docs/kcimos_下單流程實測.md)。小幫手只在這個來源的頁面裡跑,POS 也只對它開跨來源
SITE = {"origin": "http://kcimos.kv.idv.tw", "start": "/frontend/index.shtml", "label": "kcimos"}
SKU_PREFIX = "KCIMOS-"


def site_pk(sku: str) -> str | None:
    """價目表的料號 → 網站的商品編號(`KCIMOS-2685` → `2685`);不是這個樣子的回 None。"""
    pk = sku[len(SKU_PREFIX):] if isinstance(sku, str) and sku.startswith(SKU_PREFIX) else ""
    return pk if pk.isascii() and pk.isdigit() else None
NAME = "kcimos"
STOPPED = "停產／請勿下單"
# 網站上用 9999 / 9999999 表示「沒有報價」;當成正常進價會讓叫貨金額與成本大錯
NO_QUOTE_FROM = 9999
MAX_ORDER = 9999


class SnapshotError(Exception):
    """快照檔不對、或現在的狀態不能匯(講得出原因)。"""


def _text(value, limit) -> str:
    return " ".join(str(value or "").split())[:limit]


def ref_price(raw):
    """網站的採購價 → 參考價。沒報價(9999 以上)、0 元、不是正整數的 → None(不帶參考價)。"""
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0 or raw >= NO_QUOTE_FROM:
        return None
    return Decimal(raw)


def rows(snapshot) -> list[dict]:
    """快照 → 要寫進價目表的每一項。格式不對、商品編號重複或不是數字就整份不收。"""
    if not isinstance(snapshot, dict) or (snapshot.get("metadata") or {}).get("schema") != SCHEMA:
        raise SnapshotError(f"這不是 kcimos 的商品快照(要 {SCHEMA})")
    products = snapshot.get("products")
    if not isinstance(products, list) or not products:
        raise SnapshotError("快照裡沒有商品")
    out, seen = [], set()
    for index, p in enumerate(products):
        pk = str(p.get("supplier_product_id") or "") if isinstance(p, dict) else ""
        if not (pk.isascii() and pk.isdigit()):
            raise SnapshotError(f"第 {index + 1} 筆的商品編號不對")
        if pk in seen:
            raise SnapshotError(f"商品編號 {pk} 重複")
        seen.add(pk)
        name = _text(p.get("name"), 200)
        if not name:
            raise SnapshotError(f"商品 {pk} 沒有品名")
        flags = p.get("flags") if isinstance(p.get("flags"), list) else []
        out.append({
            "sku": f"{SKU_PREFIX}{pk}",
            "values": {
                "name": name,
                "kind": _text(p.get("category"), 40),
                "spec": _text(p.get("subcategory"), 120),
                "unit": "",
                "pack_qty": 1,          # 「一件五個」那兩項也是 1:POS 的一件要不要換成 5 個,連品名時人決定
                "ref_price": ref_price(p.get("purchase_price")),
                "is_active": STOPPED not in flags,
                "sort_order": min(index + 1, MAX_ORDER),
            },
        })
    return out


_LOOK_UP = object()


def plan(snapshot, only_for: list[str], vendor=_LOOK_UP) -> dict:
    """算出要做什麼(不寫資料庫):每一項是新增 / 更新 / 一樣,以及幾項停用、幾項沒有參考價。
    `vendor` = 已經鎖住的那一列(`apply` 給的:鎖住之後才核對);沒給就自己查(預覽)。"""
    wanted = rows(snapshot)
    codes = [c for c in dict.fromkeys(c.strip() for c in only_for) if c]
    if not codes:
        raise SnapshotError("要講這份價目是給哪一家公司的(公司代碼)")
    missing = [c for c in codes if not Tenant.objects.filter(code=c).exists()]
    if missing:
        raise SnapshotError(f"沒有這家公司:{'、'.join(missing)}")
    if vendor is _LOOK_UP:
        vendor = Vendor.objects.filter(code=CODE).first()
    if vendor is not None:
        if vendor.protocol != Vendor.Protocol.MANUAL:
            raise SnapshotError("名單上的 kcimos 不是半自動的廠商,不能匯")
        if not vendor.is_private:
            raise SnapshotError("名單上的 kcimos 現在是每一家公司都看得到;先在平台把它改成「只給指定的公司」再匯(這份是特定帳號的進價)")
        if vendors.company_codes(vendor) != codes:
            raise SnapshotError(
                f"名單上的 kcimos 現在是給 {'、'.join(vendors.company_codes(vendor)) or '(沒有人)'},跟這一次講的 {'、'.join(codes)} 不一樣;"
                "要換給別家公司請先在平台改(換了帳號進價也不同)")
    have = {i.sku: i for i in VendorItem.objects.filter(vendor=vendor)} if vendor is not None else {}
    new, changed, same = [], [], 0
    for row in wanted:
        item = have.get(row["sku"])
        if item is None:
            new.append(row)
        elif any(getattr(item, name) != value for name, value in row["values"].items()):
            changed.append(row)
        else:
            same += 1
    return {
        "codes": codes, "vendor_exists": vendor is not None, "rows": wanted, "new": new, "changed": changed, "same": same,
        "stopped": sum(1 for r in wanted if not r["values"]["is_active"]),
        "unpriced": sum(1 for r in wanted if r["values"]["ref_price"] is None),
        "left_alone": len(set(have) - {r["sku"] for r in wanted}),
    }


@transaction.atomic
def apply(snapshot, only_for: list[str]) -> dict:
    """照 `plan` 寫進去。廠商不存在就建(一建就是「只給指定的公司」),跟價目在同一個交易裡:沒有「建好了還沒設名單」的那一刻。

    **先鎖住廠商那一列、才核對它是不是只給這幾家公司**(複審 2026-10-13):先核對再鎖的話,中間平台管理員把它改成全部公司都看得到,價目就寫進一家公開的廠商。
    還沒有這家廠商時沒有列可以鎖:自己建,代碼是唯一的 —— 同時有人也建了一家 kcimos,這裡就整個不做(不把價目寫進別人剛建的那一家)。"""
    vendor = Vendor.objects.select_for_update().filter(code=CODE).first()
    todo = plan(snapshot, only_for, vendor)
    if vendor is None:
        try:
            with transaction.atomic():
                vendor = Vendor.objects.create(
                    code=CODE, name=NAME, protocol=Vendor.Protocol.MANUAL, is_private=True, only_for=",".join(todo["codes"]),
                    contact="價目是未稅價;下單在 kcimos 網站", sort_order=50)
        except IntegrityError:
            raise SnapshotError("剛剛有人建了 kcimos 這家廠商:什麼都沒有匯。請先在平台確認它是「只給指定的公司」,再跑一次") from None
    have = {i.sku: i for i in VendorItem.objects.filter(vendor=vendor)}
    for row in todo["new"]:
        VendorItem.objects.create(vendor=vendor, sku=row["sku"], **row["values"])
    for row in todo["changed"]:
        item = have[row["sku"]]
        for name, value in row["values"].items():
            setattr(item, name, value)
        item.save(update_fields=[*row["values"], "updated_at"])
    return todo
