"""品名連連看:這家廠商的每一個品項 ↔ 店裡的哪一個商品。

owner 2026-10-10:「要再針對供應商做品名連連看，店內品名A=供應商品名甲。指定好之後，後續下訂，只需收貨，即可直接入庫」。
連的結果就是既有的「供應商商品對照」(`catalog.SupplierProduct`),到貨入庫讀的是同一份 —— 這裡只是讓人**事先**一次連好、回頭看得到、改得了,
不用等第一次入庫才一行一行挑。

- 供應商 = 這家門市跟這家廠商的「入庫供應商」(串接上指定的;沒指定就用 / 建一筆跟廠商同名的)。
- 誰能連與改:能叫貨或能進貨的人(owner:「店員都可以」)。每一次改都留紀錄:舊的那一筆停用留著,備註寫誰、什麼時候、改指到哪。
- 只能連到入得了庫的商品(按數量管的一般商品:不追序號、不是中古、不是虛擬、沒停用)—— 跟到貨入庫同一條。
- **品名、規格、一包幾個一律用伺服器剛跟廠商要的(半自動的廠商 = 平台價目表上的),畫面只講「哪一個品項 → 哪一個商品」**;廠商現在沒有的品項不能連
  (舊單上才有的品項,到貨入庫那一頁照樣可以當場挑)。
- 改了對照不影響已經入庫的單(那些單記的是當時入到哪個商品)。
"""
from django.db import transaction
from django.db.models import Q

from apps.catalog.models import Product, SupplierProduct
from apps.identity.models import ProductAlias
from apps.identity.normalize import alias_key

from . import manual, services
from .receiving import NOT_CHECKED, Line, _fits, _map, _owner, _retire, supplier_for, vendor_sku_of
from .services import VendorError


def owners_of(tenant, supplier, vendor_skus) -> dict:
    """這些料號各自對到哪個商品(沒對到的不在裡面)。整批查一次,給清單用。

    **跟一筆一筆查的 `identity.services._vendor_sku_owner` 同一套先後**(有測試釘住兩邊一樣):
    先看已確認的別名(這家供應商自己的優先於不分廠商的),沒有才看供應商商品對照。
    """
    keys = {sku: alias_key(sku) for sku in vendor_skus}
    wanted = [key for key in set(keys.values()) if key]
    if supplier is None or not wanted:
        return {}
    own, generic, listed = {}, {}, {}
    aliases = (ProductAlias.objects.for_tenant(tenant)
               .filter(is_active=True, verified=True, kind=ProductAlias.Kind.VENDOR_SKU, normalized_value__in=wanted)
               .filter(Q(supplier__isnull=True) | Q(supplier=supplier)).select_related("product").order_by("id"))
    for alias in aliases:
        (generic if alias.supplier_id is None else own).setdefault(alias.normalized_value, alias.product)
    for row in (SupplierProduct.objects.for_tenant(tenant)
                .filter(is_active=True, supplier=supplier, vendor_sku_key__in=wanted)
                .select_related("product").order_by("id")):
        listed.setdefault(row.vendor_sku_key, row.product)
    found = {**listed, **generic, **own}
    return {sku: found[key] for sku, key in keys.items() if key in found}


def _product_data(product) -> dict | None:
    return None if product is None else {
        "id": product.id, "sku": product.sku, "name": product.name, "is_active": product.is_active}


def _row(item: dict, product) -> dict:
    """連連看的一列。**不帶價錢**(只是品名對品名;進價是叫貨那一頁的事)。"""
    return {
        "key": item["key"], "sku": item["sku"], "spec_id": item["spec_id"], "name": item["name"],
        "spec_label": item["spec_label"], "kind": item["kind"], "size": item["size"], "unit": item["unit"],
        "pack_qty": item["pack_qty"], "product": _product_data(product),
    }


def rows(tenant, link, vendor) -> dict:
    """連連看那一頁:這家廠商現在的每一個品項,與它對到的店內商品。"""
    items = manual.catalog_rows(link, vendor)
    owners = owners_of(tenant, link.supplier, [vendor_sku_of(i["sku"], i["spec_id"]) for i in items])
    return {
        "supplier": None if link.supplier_id is None else {"id": link.supplier_id, "name": link.supplier.name},
        "rows": [_row(i, owners.get(vendor_sku_of(i["sku"], i["spec_id"]))) for i in items],
    }


def set_product(*, tenant, user, link, vendor, key, product_id) -> dict:
    """把一個廠商品項連到一個店內商品(`product_id` 給 None = 解除)。回這一列現在的樣子。"""
    if not isinstance(key, str) or not key.strip():
        raise VendorError("要指定是哪一個品項")
    if not (product_id is None or (isinstance(product_id, int) and not isinstance(product_id, bool))):
        raise VendorError("商品不對")
    # 跟廠商要清單在交易與鎖之外(要等網路);半自動的廠商 = 平台的價目表
    item = next((i for i in manual.catalog_rows(link, vendor) if i["key"] == key), None)
    if item is None:
        raise VendorError(f"{vendor.name}現在沒有這個品項,請重新整理")
    line = Line(sku=item["sku"], spec_id=item["spec_id"], is_reissue=False, spec_label=item["spec_label"],
                name=item["name"], unit=item["unit"], pack_qty=item["pack_qty"])
    with transaction.atomic():
        supplier = supplier_for(link)
        if product_id is None:
            _retire(tenant, supplier, line, user, "解除對照")
            still = _owner(tenant, supplier, line)
            if still is not None:
                raise VendorError(f"「{line.title}」在商品的其他叫法裡對到「{still.name}」,要先到那個商品把這個叫法拿掉")
            return _row(item, None)
        product = Product.objects.filter(tenant=tenant, pk=product_id).first()
        if product is None:
            raise VendorError("找不到這個商品")
        _fits(product, line.title)
        _map(tenant, supplier, line, product, user, link.provider, seen=NOT_CHECKED)
        return _row(item, _owner(tenant, supplier, line))
