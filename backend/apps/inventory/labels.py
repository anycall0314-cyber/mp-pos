"""商品標籤要印什麼(50 × 30 mm 的那一張)。只讀:不動庫存、不動單據。

三個來源,回的都是同一種「一張標籤」:

- 一張進貨單:序號商品每一台一張;配件一行一筆、張數 = 進貨數量(畫面可以改張數)。
- 幾台設備:每一台一張(庫存查詢補印、個人收購存完印)。
- 一個配件商品 + 張數(庫存查詢補印)。

規則只有這一份(畫面只負責排版、畫條碼):

- 條碼的內容:有序號印主碼(有 IMEI 是 IMEI,沒有才是 SN)→ 沒有序號印原廠條碼 → 都沒有印品號。
- 售價:逐台定價的商品(中古機、已拆封)印那一台自己的售價,沒有才印建議售價;沒有價錢就不印。
  「那一台自己的售價」是 0(或負的)= 沒填:跟銷貨開單帶價的規則一樣(`> 0` 才用),不然標籤上的價錢會跟結帳帶出來的不一樣。
- 成色:只有逐台記機況的商品才印。
- 進貨單號與日期:那一台當初進貨的那一張;個人收購進來的印收購那一張單;配件補印沒有「哪一批」可言,不印(不猜)。
"""
from apps.catalog.models import Product
from apps.core.money import money_int

from .models import ProductSerial

# 一次最多幾台 / 一筆最多幾張:擋掉打錯的數字(多打一個 0 就是一整卷標籤)
MAX_UNITS = 300
MAX_COPIES = 500


class LabelError(Exception):
    """不讓印(原因會顯示給使用者)。"""


def _price(product, serial=None):
    """標籤上的售價(整數元);沒有價錢回 None(不印)。"""
    unit = None
    if serial is not None and product.tracks_unit_condition:
        unit = serial.custom_unit_price
    value = unit if unit is not None and unit > 0 else product.list_price
    if value is None or value <= 0:
        return None
    # 不到一塊錢的四捨五入是 0:一樣當沒有價錢,不印「$0」
    return money_int(value) or None


def _for_product(product, copies, source=None):
    barcode = (product.barcode or "").strip()
    return {
        "key": f"p{product.id}",
        "product_id": product.id,
        "serial_id": None,
        "name": product.name,
        "sku": product.sku,
        "code": barcode or product.sku,
        "code_kind": "barcode" if barcode else "sku",
        "last5": "",
        "price": _price(product),
        "grade": "",
        "doc_no": source[0] if source else "",
        "doc_date": source[1] if source else "",
        "copies": copies,
    }


def _source_of(serial):
    """這一台是哪一張單進來的:(單號, 日期);不知道就是 None。"""
    item = serial.purchase_order_item
    if item is not None:
        return item.po.no, item.po.doc_date.isoformat()
    so = serial.acquired_via_sales_order
    if so is not None:
        return so.no, so.doc_date.isoformat()
    return None


def _for_serial(serial):
    product = serial.product
    source = _source_of(serial)
    # 頭尾的空白不是碼的一部分(舊資料貼進來的):條碼跟字都用去掉之後的
    code = (serial.serial_no or "").strip()
    return {
        "key": f"s{serial.id}",
        "product_id": product.id,
        "serial_id": serial.id,
        "name": product.name,
        "sku": product.sku,
        "code": code,
        "code_kind": "serial",
        "last5": code[-5:],
        "price": _price(product, serial),
        "grade": serial.condition_grade if product.tracks_unit_condition else "",
        "doc_no": source[0] if source else "",
        "doc_date": source[1] if source else "",
        "copies": 1,
    }


def _serials(tenant):
    return (
        ProductSerial.objects.for_tenant(tenant)
        .exclude(status=ProductSerial.Status.VOID)
        .select_related(
            "product", "product__condition", "purchase_order_item__po", "acquired_via_sales_order",
        )
        # 進貨明細上那一整包序號清單(JSON)這裡用不到:一台帶一份太重
        .defer("purchase_order_item__serial_numbers")
    )


def for_purchase_order(tenant, po_id):
    """一張進貨單的標籤。回 (這張單的說明, 標籤清單, 要講出來的事)。"""
    from apps.purchasing.models import PurchaseOrder

    po = PurchaseOrder.objects.for_tenant(tenant).filter(pk=po_id).first()
    if po is None:
        raise LabelError("找不到這張進貨單")
    if po.is_void:
        raise LabelError("這張進貨單已作廢,不能印標籤")
    source = (po.no, po.doc_date.isoformat())
    units = list(_serials(tenant).filter(purchase_order_item__po=po).order_by("id")[:MAX_UNITS + 1])
    if len(units) > MAX_UNITS:
        raise LabelError(f"這張進貨單超過 {MAX_UNITS} 台,一次印不完;請到庫存查詢分批印")
    by_item = {}
    for serial in units:
        by_item.setdefault(serial.purchase_order_item_id, []).append(serial)
    labels, notes = [], []
    items = po.items.select_related("product", "product__condition").order_by("line_no", "id")
    for item in items:
        product = item.product
        if product.is_virtual or item.qty < 1:
            continue
        mine = by_item.get(item.id, [])
        # 這一行當初有沒有逐台入庫,看的是「這一行底下有沒有設備」,不是商品**現在**的設定:
        # 進貨之後有人把商品改成不追序號,這一行的每一台還是各有各的碼 —— 照商品現在的設定就會全部印成同一個商品條碼
        if mine or product.requires_serial:
            labels.extend(_for_serial(s) for s in mine)
            if len(mine) < item.qty:
                # 舊資料沒有逐台的序號、或那幾台已經作廢:照實講,不能看起來像整張都印了
                notes.append(f"{product.name}:進貨 {item.qty} 台,可以印的只有 {len(mine)} 台")
        else:
            label = _for_product(product, min(item.qty, MAX_COPIES), source)
            label["key"] = f"i{item.id}"
            labels.append(label)
            if item.qty > MAX_COPIES:
                notes.append(f"{product.name}:進貨 {item.qty} 件,一次最多印 {MAX_COPIES} 張")
    return {"kind": "po", "no": po.no}, labels, notes


def for_serials(tenant, serial_ids):
    """幾台設備,每一台一張;照送來的順序。"""
    ids = list(dict.fromkeys(serial_ids))
    if not ids:
        raise LabelError("沒有指定要印哪一台")
    if len(ids) > MAX_UNITS:
        raise LabelError(f"一次最多印 {MAX_UNITS} 台")
    found = {s.id: s for s in _serials(tenant).filter(pk__in=ids)}
    missing = [i for i in ids if i not in found]
    if missing:
        raise LabelError("找不到要印的設備(可能已經作廢)")
    return {"kind": "serials"}, [_for_serial(found[i]) for i in ids], []


def for_product(tenant, product_id, copies):
    """一個配件商品印幾張。序號商品要指定哪一台(每一台的碼不一樣)。"""
    product = (
        Product.objects.for_tenant(tenant).select_related("condition").filter(pk=product_id).first()
    )
    if product is None:
        raise LabelError("找不到這個商品")
    if product.is_virtual:
        raise LabelError("虛擬商品(手續費、折抵之類)沒有東西可以貼標籤")
    if product.requires_serial:
        raise LabelError("有序號的商品要選哪一台(每一台的條碼不一樣)")
    if not 1 <= copies <= MAX_COPIES:
        raise LabelError(f"張數要在 1 到 {MAX_COPIES} 之間")
    return {"kind": "product"}, [_for_product(product, copies)], []
