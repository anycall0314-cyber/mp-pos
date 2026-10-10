"""半自動的廠商:廠商那邊**什麼都不用改**(沒有可以接的系統;多半是租來的進銷存,沒有串接功能)。

owner 2026-10-10:「招商這塊最大的問題，就是要如何串接不同家供應商，初期採取半自動化MVP，後續可以再把它補齊成自動化」
「多數廠商有自己的進銷存，但都是租賃系統，規格也不明確，他們不會串接，甚至沒有串接的功能」。

跟全自動(standard.py + services.py + receiving.py)差在哪:
- **商品與價錢**:平台幫廠商建的價目表(`VendorItem`),所有店家同一份;價錢是**參考價**、可以是空的(沒報價也可以叫)。
- **開通**:沒有金鑰;管理員在叫貨串接按「開通」(`VendorLink.opened`)。
- **叫貨**:POS 自己成立一張叫貨單(`VendorOrder.manual=True`、單號 `VO-` + 流水),**不打任何外部系統**。
  成立之後要有人把內容傳給廠商(`order_text` 那一段貼到 LINE;2c 之後有接單信箱的會自動寄)—— 傳了沒記在單上(`sent_at`)。
- **進度**:靠人記一句;可以取消(只是 POS 這邊的標記)與恢復。沒有「更新進度」「再送一次」「把外面的單認進來」。
- **到貨入庫**:照店家叫的這張單列(不是問廠商);數量不預先帶;**實際單價入庫的人填**(預設參考價);可以填這一次的運費;
  **可以入這張單沒叫的品項**(換款、多送:價目表上的)。**比叫的多只提醒、不擋**(沒有廠商的系統可以對)。
  開出來的一樣是進貨單(未稅、成本 = 實際付的;貨到付款記現金;同一把鑰匙不入兩次;對照與「舊畫面」的保護跟全自動同一套)。
"""
import re
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers as drf_serializers

from apps.catalog.models import Product
from apps.identity.normalize import alias_key
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.serializers import PurchaseOrderSerializer
from apps.purchasing.services import PurchaseOrderError, commit_purchase_order
from apps.tenants.models import PaymentMethod

from . import services, standard, vendors
from .models import Vendor, VendorItem, VendorLink, VendorOrder, VendorOrderItem, VendorReceipt, VendorReceiptItem
from .receiving import (
    CASH_ON_DELIVERY, CENT, ZERO, Line, _fits, _in_lock_order, _lock_request, _map, _owner, _spread, _whole,
    line_key, received_by_line, supplier_for,
)
from .services import REQUEST_KEY, VendorError

MAX_PRICE = Decimal("9999999.99")
MAX_FREIGHT = 9_999_999
MAX_QTY = 99_999
NOTE_LIMIT = 200
ORDER_NO = "VO-{:06d}"
PLAIN_PRICE = re.compile(r"^\d{1,7}(\.\d{1,2})?$")


def is_manual(vendor) -> bool:
    return vendor is not None and vendor.protocol == Vendor.Protocol.MANUAL


def need_open(link, vendor) -> None:
    if link is None or not link.opened:
        raise VendorError(f"這家門市還沒有開通{vendor.name},請管理員到「系統設定 → 叫貨串接」開通")


# ── 商品清單(= 平台的價目表)────────────────────────────────────────────────
def _row(item: VendorItem) -> dict:
    """跟全自動的那一份同一個樣子(`services.rows_from`):畫面與對照分頁不用分兩套。料號就是 key(沒有規格這一層)。"""
    return {"key": item.sku, "sku": item.sku, "spec_id": None, "spec_label": item.spec, "name": item.name,
            "kind": item.kind, "size": "", "unit": item.unit, "pack_qty": item.pack_qty, "unit_price": item.ref_price}


def rows(vendor) -> list[dict]:
    return [_row(i) for i in VendorItem.objects.filter(vendor=vendor, is_active=True)]


def catalog_rows(link, vendor) -> list[dict]:
    """這家門市現在可以跟這家廠商叫的東西。半自動 = 價目表;全自動 = 現問它的系統。"""
    if is_manual(vendor):
        need_open(link, vendor)
        return rows(vendor)
    return services.live_rows(link, vendor)


# ── 叫貨 ────────────────────────────────────────────────────────────────────
def _header(link, payment_method, delivery_method) -> dict:
    header = dict(
        payment_method=payment_method or link.payment_method,
        delivery_method=delivery_method or link.delivery_method,
        # 收件只用管理員設定的那一份(跟全自動一樣:畫面送什麼都不看)
        ship_name=link.ship_name, ship_phone=link.ship_phone, ship_address=link.ship_address,
        invoice_type=link.invoice_type, buyer_tax_id=link.buyer_tax_id, buyer_name=link.buyer_name,
        invoice_email=link.invoice_email,
    )
    check_header(header["payment_method"], header["delivery_method"], link.ship_name, link.ship_phone, link.ship_address)
    return header


def check_header(payment_method, delivery_method, ship_name, ship_phone, ship_address) -> None:
    """半自動的單頭只管付款、取貨、收件(發票那幾格是全自動那一套要的,這裡不要求)。"""
    if payment_method not in standard.PAYMENT_METHODS:
        raise VendorError("付款方式只能是 月結 / 貨到付款 / 匯款")
    if delivery_method not in standard.DELIVERY_METHODS:
        raise VendorError("取貨方式只能是 宅配 / 自取")
    if delivery_method == "宅配" and not (ship_name and ship_phone and ship_address):
        raise VendorError("宅配要有收件人、電話、地址(請管理員到「系統設定 → 叫貨串接」填)")


def place(*, tenant, user, link, vendor, request_key, lines, payment_method=None, delivery_method=None, note=""):
    """成立一張叫貨單(POS 自己成立;不打任何外部系統)。回 (叫貨單, 是不是這一次新建的)。同一把鑰匙再來回同一張。"""
    if not isinstance(request_key, str) or not REQUEST_KEY.match(request_key):
        raise VendorError("這張叫貨單的編號不對,請重新整理頁面再試")
    existing = VendorOrder.objects.filter(tenant=tenant, request_key=request_key).first()
    if existing is not None:
        return _same(existing, link), False
    if not vendor.is_active:
        raise VendorError(f"「{vendor.name}」已經停用,不能叫新的貨")
    need_open(link, vendor)
    items = services._lines(rows(vendor), lines, vendor.name, unpriced_ok=True)
    header = _header(link, payment_method, delivery_method)
    note = note.strip()[:NOTE_LIMIT] if isinstance(note, str) else ""
    try:
        with transaction.atomic():
            order = VendorOrder.objects.create(
                tenant=tenant, provider=link.provider, link=link, warehouse=link.warehouse, manual=True,
                request_key=request_key, vendor_key=f"pos-{tenant.code}-{request_key}"[:100],
                state=VendorOrder.State.PLACED, expected_goods=services.goods_total(items), note=note,
                created_by=user, **header,
            )
            order.vendor_order_no = ORDER_NO.format(order.id)
            order.save(update_fields=["vendor_order_no"])
            VendorOrderItem.objects.bulk_create([
                VendorOrderItem(
                    tenant=tenant, order=order, line_no=n, sku=i["sku"], spec_id=None,
                    spec_label=i["spec_label"][:120], name=i["name"][:200], unit=i["unit"][:10],
                    pack_qty=i["pack_qty"], packs=i["packs"], qty=i["qty"], unit_price=i["unit_price"],
                ) for n, i in enumerate(items, start=1)
            ])
    except IntegrityError:
        # 同一把鑰匙的另一個請求剛好先建了(連按兩下)
        existing = VendorOrder.objects.filter(tenant=tenant, request_key=request_key).first()
        if existing is None:
            raise
        return _same(existing, link), False
    return order, True


def _same(order: VendorOrder, link) -> VendorOrder:
    if link is not None and order.warehouse_id != link.warehouse_id:
        raise VendorError("這把鑰匙是另一家門市的叫貨單")
    if link is not None and order.provider != link.provider:
        raise VendorError("這把鑰匙是另一家廠商的叫貨單")
    return order


def order_text(order: VendorOrder) -> str:
    """要傳給廠商的那一段(貼 LINE、寄信用同一份)。**不寫價錢**:價目表上的只是參考價,寫上去會被當成講好的價錢。"""
    out = [f"【叫貨】{order.tenant.name} {order.warehouse.name}",
           f"單號 {order.vendor_order_no}({timezone.localtime(order.created_at):%Y-%m-%d})"]
    for n, i in enumerate(order.items.all(), start=1):
        name = " ".join(x for x in (i.name, i.spec_label) if x)
        unit = i.unit or "個"
        qty = f"{i.packs} 包(共 {i.qty} {unit})" if i.pack_qty > 1 else f"{i.qty} {unit}"
        out.append(f"{n}. {name} × {qty}")
    if order.delivery_method == "宅配":
        out.append(f"收件:{order.ship_name} {order.ship_phone} {order.ship_address}")
    else:
        out.append(f"取貨:{order.delivery_method}")
    out.append(f"付款:{order.payment_method}")
    if order.note:
        out.append(f"備註:{order.note}")
    return "\n".join(out)


# ── 傳了沒、進度、取消 ──────────────────────────────────────────────────────
def _need_manual(order: VendorOrder) -> None:
    if not order.manual:
        raise VendorError("這張叫貨單是直接送到廠商系統的,不用人工標記")


def mark_sent(order: VendorOrder, user, sent) -> VendorOrder:
    """店員把叫貨內容貼給廠商之後按的(可以收回)。已經標過的不改時間與人。"""
    _need_manual(order)
    if not isinstance(sent, bool):
        raise VendorError("傳了沒只能是「已傳」或「還沒」")
    if sent and order.sent_at is None:
        order.sent_at, order.sent_how, order.sent_by = timezone.now(), "manual", user
    elif not sent:
        order.sent_at, order.sent_how, order.sent_by = None, "", None
    order.save(update_fields=["sent_at", "sent_how", "sent_by", "updated_at"])
    return order


def set_progress(order: VendorOrder, note) -> VendorOrder:
    _need_manual(order)
    if not isinstance(note, str) or len(note.strip()) > NOTE_LIMIT:
        raise VendorError(f"進度備註最多 {NOTE_LIMIT} 個字")
    order.progress_note = note.strip()
    order.save(update_fields=["progress_note", "updated_at"])
    return order


def set_cancelled(order: VendorOrder, user, cancelled) -> VendorOrder:
    """取消 / 恢復。只是 POS 這邊的標記(廠商不會知道,要自己講);取消的單貨到了照樣入得了庫。"""
    _need_manual(order)
    if not isinstance(cancelled, bool):
        raise VendorError("只能是「取消」或「恢復」")
    if cancelled and order.cancelled_at is None:
        order.cancelled_at, order.cancelled_by = timezone.now(), user
    elif not cancelled:
        order.cancelled_at, order.cancelled_by = None, None
    order.save(update_fields=["cancelled_at", "cancelled_by", "updated_at"])
    return order


# ── 到貨入庫 ────────────────────────────────────────────────────────────────
def _line(sku, spec, name, unit, pack_qty, qty=0, amount=ZERO) -> Line:
    return Line(sku=sku, spec_id=None, is_reissue=False, spec_label=spec, name=name, unit=unit, pack_qty=pack_qty,
                qty=qty, amount=amount)


def _money(value):
    return None if value is None else str(value)


def plan(tenant, order: VendorOrder) -> dict:
    """到貨入庫那一頁要的東西:店家叫的這張單的每一行(叫 / 已入)、這張單沒叫但入過的、還可以加的品項(價目表上的)。"""
    link = order.link
    got = received_by_line(order)
    ordered = {line_key(i.sku, None, False): i for i in order.items.all()}
    listed = {line_key(i.sku, None, False): i for i in VendorItem.objects.filter(vendor__code=order.provider)}
    lines = [(key, _line(i.sku, i.spec_label, i.name, i.unit, i.pack_qty), i.qty, i.unit_price) for key, i in ordered.items()]
    # 這張單沒叫、但入過的(換款、多送):也列出來(叫 0、已入 N),不然入過的東西在這一頁看不到
    for key in got:
        if key not in ordered and key in listed:
            i = listed[key]
            lines.append((key, _line(i.sku, i.spec, i.name, i.unit, i.pack_qty), 0, i.ref_price))
    extras = [(key, _line(i.sku, i.spec, i.name, i.unit, i.pack_qty), i.ref_price)
              for key, i in listed.items() if i.is_active and key not in ordered and key not in got]
    with transaction.atomic():          # 查對照會拿一把交易內的鎖
        owners = {l.key: _owner(tenant, link.supplier, l)
                  for l in _in_lock_order([l for _, l, *_ in lines] + [l for _, l, _ in extras])}

    def product(line):
        owner = owners[line.key]
        return None if owner is None else {"id": owner.id, "sku": owner.sku, "name": owner.name, "is_active": owner.is_active}

    def shape(key, line, qty, price, done):
        return {
            "key": key, "sku": line.sku, "spec_id": None, "spec_label": line.spec_label, "name": line.name,
            "unit": line.unit, "pack_qty": line.pack_qty, "is_reissue": False,
            "qty": qty, "shipped_qty": qty, "received_qty": done, "remaining_qty": qty - done,
            "suggested_qty": 0,                      # 半自動的不預先帶數量(沒有廠商說出了幾個;由人填,或按「全部到齊」)
            "unit_price": _money(price), "product": product(line),
        }

    return {
        "order": order.id,
        "vendor_order_no": order.vendor_order_no,
        "manual": True,
        "vendor_status": "", "vendor_logistics_status": "", "vendor_tracking_no": "",
        "payment_method": order.payment_method,
        "lines": [shape(key, line, qty, price, got.get(key, 0)) for key, line, qty, price in lines],
        # 這張單沒叫、價目表上有的:入庫時可以加(換款、多送)
        "extras": [shape(key, line, 0, price, 0) for key, line, price in extras],
        "shipping_fee": "0.00",
        "freight_into_cost": link.freight_into_cost,
        "freight_left": "0.00",
        "supplier": None if link.supplier is None else {"id": link.supplier_id, "name": link.supplier.name},
        "issue_note": order.issue_note,
    }


def _price(value) -> Decimal | None:
    """入庫的人填的實際單價:0 到上限、最多兩位小數。數字或字串都收;其他回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and not PLAIN_PRICE.match(value.strip()):
        return None                 # 字只收一般的寫法(123 / 123.5 / 123.45);科學記號、千分位、正負號都不收
    try:
        price = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if not price.is_finite() or price < 0 or price > MAX_PRICE or price != price.quantize(CENT):
        return None
    return price.quantize(CENT)


def _wanted(lines) -> list[tuple[str, int, int, object, Decimal]]:
    """畫面送來的每一行 → (哪一行, 幾個, 入到哪個品號, 他看到這一行原本對到誰, 實際單價)。"""
    if not isinstance(lines, list) or not lines:
        raise VendorError("這一次沒有要入庫的東西")
    seen, out = set(), []
    for row in lines:
        key = row.get("key") if isinstance(row, dict) else None
        qty = _whole(row.get("qty")) if isinstance(row, dict) else None
        product = _whole(row.get("product")) if isinstance(row, dict) else None
        if not isinstance(key, str) or qty is None or not 1 <= qty <= MAX_QTY or product is None:
            raise VendorError("入庫的內容不完整(每一行要有數量與對到的品號)")
        price = _price(row.get("unit_price"))
        if price is None:
            raise VendorError("每一行都要填實際的單價(沒有收錢的填 0)")
        was = row.get("was")
        if was is not None and (_whole(was) is None or was < 1):
            raise VendorError("入庫的內容不完整(原本對到的品號不對)")
        if key in seen:
            raise VendorError("同一行重複了")
        seen.add(key)
        out.append((key, qty, product, was, price))
    return out


def _freight(value) -> Decimal:
    """這一次的運費(整數元;沒填 = 0)。"""
    if value in (None, ""):
        return ZERO
    n = _whole(value)
    if n is None or not 0 <= n <= MAX_FREIGHT:
        raise VendorError(f"運費要是 0 到 {MAX_FREIGHT} 的整數")
    return Decimal(n)


def receive(*, tenant, user, order: VendorOrder, request_key, lines, freight=None):
    """把這一次到的貨入庫:開一張進貨單。回 (這一次入庫, 是不是這一次新做的)。同一把鑰匙再來回同一次。"""
    if not order.manual:
        raise VendorError("這張叫貨單不是半自動的")
    if not isinstance(request_key, str) or not REQUEST_KEY.match(request_key):
        raise VendorError("這一次入庫的編號不對,請重新打開入庫再試")
    with transaction.atomic():
        _lock_request(tenant, request_key)
        return _receive(tenant=tenant, user=user, order=order, request_key=request_key, lines=lines, freight=freight)


def _receive(*, tenant, user, order, request_key, lines, freight):
    done = VendorReceipt.objects.filter(tenant=tenant, request_key=request_key).first()
    if done is not None:
        if done.order_id != order.id:
            raise VendorError("這把鑰匙是另一張叫貨單的入庫")
        return done, False
    wanted = _wanted(lines)
    fee = _freight(freight)
    who = vendors.name_of(order.provider)
    try:
        with transaction.atomic():
            locked = VendorOrder.objects.select_for_update().get(pk=order.pk)
            done = VendorReceipt.objects.filter(tenant=tenant, request_key=request_key).first()
            if done is not None:
                return done, False
            supplier = supplier_for(locked.link)
            link = VendorLink.objects.get(pk=locked.link_id)
            ordered = {line_key(i.sku, None, False): (i.sku, i.spec_label, i.name, i.unit, i.pack_qty) for i in locked.items.all()}
            got = received_by_line(locked)
            listed = {line_key(i.sku, None, False): i for i in VendorItem.objects.filter(vendor__code=locked.provider)}
            products = {p.id: p for p in Product.objects.filter(tenant=tenant, pk__in=[w[2] for w in wanted])}
            sources = {}
            for key, *_ in wanted:
                if key in ordered:
                    sources[key] = ordered[key]
                elif key in listed and (listed[key].is_active or key in got):
                    i = listed[key]            # 這張單沒叫的:要是價目表上現在有的(或這張單先前入過的)
                    sources[key] = (i.sku, i.spec, i.name, i.unit, i.pack_qty)
                else:
                    raise VendorError(f"有一項不在這張叫貨單上、{who}的價目表上現在也沒有,請重新打開入庫再試")
            picked = []
            for key, qty, product_id, was, price in sorted(wanted, key=lambda w: alias_key(sources[w[0]][0])):
                line = _line(*sources[key], qty=qty, amount=price * qty)
                product = products.get(product_id)
                if product is None:
                    raise VendorError(f"「{line.title}」對到的商品找不到")
                _fits(product, line.title)
                _map(tenant, supplier, line, product, user, locked.provider, seen=was)
                picked.append((line, qty, product, price))
            # 運費:這一次填多少就是多少(沒有廠商的單可以對);算不算進成本照門市的設定。全部都是沒收錢的貨 → 沒有地方攤,不算
            extra = _spread(fee, [(l, q) for l, q, _, _ in picked]) if link.freight_into_cost and fee > 0 else {}
            share = sum(extra.values(), ZERO)
            items = []
            for line, qty, product, price in picked:
                if price == 0:              # 沒收錢的(贈品、補寄):數量照入、不計價
                    items.append({"product": product.id, "qty": qty, "billed_qty": 0, "unit_price": "0"})
                else:
                    cost = ((price * qty + extra.get(line.key, ZERO)) / qty).quantize(CENT)
                    items.append({"product": product.id, "qty": qty, "unit_price": str(cost)})
            cash = None
            if locked.payment_method == CASH_ON_DELIVERY:
                cash = (PaymentMethod.objects.filter(tenant=tenant, kind=PaymentMethod.Kind.CASH, is_active=True)
                        .order_by("sort_order", "id").first())
            note = f"{who} {locked.vendor_order_no} 到貨入庫"
            if fee > 0 and share == 0:
                note += f"(運費 {fee:.0f} 沒有算進成本)"
            form = PurchaseOrderSerializer(data={
                "supplier": supplier.id, "warehouse": locked.warehouse_id,
                # 未稅:單價照放、不除 1.05 —— 成本 = 實際付出去的金額(owner 2026-10-10)
                "tax_method": PurchaseOrder.TaxMethod.UNTAXED,
                "payment_method": cash.id if cash else None, "note": note[:200], "items": items,
            })
            form.is_valid(raise_exception=True)
            form.save(tenant=tenant, created_by=user)
            commit_purchase_order(form.instance)
            receipt = VendorReceipt.objects.create(
                tenant=tenant, order=locked, purchase_order=form.instance, request_key=request_key,
                freight=share, created_by=user,
            )
            VendorReceiptItem.objects.bulk_create([
                VendorReceiptItem(
                    tenant=tenant, receipt=receipt, sku=line.sku[:80], spec_id=None, is_reissue=False,
                    name=line.title[:200], qty=qty, unit_price=price, product=product,
                ) for line, qty, product, price in picked
            ])
    except PurchaseOrderError as exc:
        raise VendorError(str(exc)) from None
    except drf_serializers.ValidationError as exc:
        raise VendorError(f"進貨單開不出來:{exc.detail}") from None
    except IntegrityError:
        # 同一把鑰匙的另一個請求剛好先做完
        done = VendorReceipt.objects.filter(tenant=tenant, request_key=request_key).first()
        if done is None:
            raise
        return done, False
    return receipt, True
