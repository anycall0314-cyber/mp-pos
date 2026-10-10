"""廠商叫貨的規則(第一步:叫貨)。

**同一張叫貨單在廠商那邊只會成立一次**,靠的是三件事:
1. 畫面每開一張新單產生一把鑰匙(`request_key`);送給廠商的那一把(`vendor_key`)由它固定算出來。
2. 先把叫貨單存好(狀況「送出中」)才打廠商。廠商明確說成立 → 已成立;明確說不行 → **這一列刪掉**(沒有成立,鑰匙沒被用掉);
   沒有明確答覆(斷線、逾時、對方出錯)→「不確定」。
3. 「不確定」只能用**同一把鑰匙、同一把金鑰**再送:廠商那邊成立過會回同一個單號,沒成立過就是這一次成立。
   金鑰換過就不能再這樣確認(廠商的防重複是看「金鑰 + 鑰匙」),那一張停在不確定、請人到廠商查。

價錢一律不送:單價、運費、總額是廠商算的。畫面與這裡存的單價只是叫貨當下的牌價。
"""
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import moceo, secrets
from .models import VendorOrder, VendorOrderItem, VendorSecret

MAX_LINES = 100
MAX_PACKS = 9999
SENDING_GRACE = timedelta(seconds=90)       # 「送出中」超過這麼久沒有結果,當成那一次沒有回來(可以重送)
REQUEST_KEY = re.compile(r"^[A-Za-z0-9_-]{8,50}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SANDBOX_ONLY = "這裡是測試環境,只能用膜總裁的沙盒金鑰(到膜總裁後台產生金鑰時勾「沙盒」)"
CENT = Decimal("0.01")


class VendorError(Exception):
    """不讓做 / 沒做成(訊息是給使用者看的)。"""
    status = 400


class NotPlaced(VendorError):
    """廠商明確說這張單沒有成立(原因在訊息裡)。這張叫貨單沒有留下,鑰匙可以再用。"""


class Busy(VendorError):
    status = 409


# ── 金鑰與商品清單 ──────────────────────────────────────────────────────────
def key_of(link) -> str:
    raw = secrets.reveal(link) if link is not None else None
    if not raw:
        raise VendorError("這家門市還沒有設定膜總裁的金鑰,請管理員到「系統設定 → 叫貨串接」設定")
    return raw


def _read(call, *args):
    """打廠商「讀」的那幾支,把兩種失敗翻成給人看的話。"""
    try:
        return call(*args)
    except moceo.Unreachable:
        raise VendorError("連不到膜總裁,請稍後再試") from None
    except moceo.Refused as exc:
        if exc.status in (401, 403):
            raise VendorError("膜總裁不認得這家門市的金鑰(可能已經作廢),請管理員重新設定") from None
        raise VendorError(f"膜總裁:{exc.reason}") from None


def _price(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        price = Decimal(str(value)).quantize(CENT)
    except InvalidOperation:
        return None
    return price if price >= 0 else None


def rows_from(products) -> list[dict]:
    """廠商的商品清單 → 一列一個「訂得到的東西」。有規格的商品一個規格一列(下單要帶規格);
    `unit_price` 是 None = 這個帳號沒有這一項的報價(不能訂)。看不懂的列跳過,不猜。"""
    out = []
    for p in products if isinstance(products, list) else []:
        if not isinstance(p, dict):
            continue
        sku, name = p.get("sku"), p.get("name")
        if not isinstance(sku, str) or not sku.strip() or not isinstance(name, str):
            continue
        pack = p.get("pack_qty")
        base = {
            "sku": sku,
            "name": name,
            "kind": p["kind"] if isinstance(p.get("kind"), str) else "",
            "size": p["size"] if isinstance(p.get("size"), str) else "",
            "unit": p["unit"] if isinstance(p.get("unit"), str) else "",
            "pack_qty": pack if isinstance(pack, int) and not isinstance(pack, bool) and pack >= 1 else 1,
        }
        specs = [
            s for s in (p.get("specs") if isinstance(p.get("specs"), list) else [])
            if isinstance(s, dict) and isinstance(s.get("id"), int) and not isinstance(s.get("id"), bool)
        ]
        if not specs:
            out.append({**base, "key": sku, "spec_id": None, "spec_label": "", "unit_price": _price(p.get("unit_price"))})
        for s in specs:
            label = " ".join(x for x in (s.get("code"), s.get("name")) if isinstance(x, str) and x)
            out.append({**base, "key": f"{sku}#{s['id']}", "spec_id": s["id"], "spec_label": label,
                        "unit_price": _price(s.get("unit_price"))})
    return out


def _only_sandbox_here(sandbox) -> None:
    """測試環境(`VENDOR_SANDBOX_ONLY`)只收廠商明講是沙盒的金鑰:不然有人把正式金鑰貼到測試站,測試時下的就是真的單。"""
    if settings.VENDOR_SANDBOX_ONLY and sandbox is not True:
        raise VendorError(SANDBOX_ONLY)


def live_rows(link, key=None) -> list[dict]:
    listing = _read(moceo.products, key or key_of(link))
    # 這把金鑰是不是沙盒以廠商現在講的為準(廠商那邊改過設定的話跟著換)
    VendorSecret.objects.filter(link=link).exclude(sandbox=listing.sandbox).update(sandbox=listing.sandbox)
    _only_sandbox_here(listing.sandbox)
    return rows_from(listing.products)


def check_key(raw):
    """要存的金鑰:樣子要對、而且廠商認得(拿它打一次商品清單)。回 (整理過的原文, 廠商說是不是沙盒)。"""
    raw = raw.strip() if isinstance(raw, str) else ""
    if not moceo.looks_like_key(raw):
        raise VendorError("這不像膜總裁的金鑰(要以 mk_live_ 開頭、中間沒有空白)")
    try:
        listing = moceo.products(raw)
    except moceo.Unreachable:
        raise VendorError("連不到膜總裁,沒辦法確認這把金鑰,沒有存") from None
    except moceo.Refused as exc:
        if exc.status in (401, 403):
            raise VendorError("膜總裁不認得這把金鑰(打錯、或已經作廢),沒有存") from None
        raise VendorError(f"膜總裁:{exc.reason}(沒有存)") from None
    _only_sandbox_here(listing.sandbox)
    return raw, listing.sandbox


# ── 單頭:付款、取貨、收件、發票 ───────────────────────────────────────────────
def check_header(*, payment_method, delivery_method, ship_name, ship_phone, ship_address,
                 invoice_type, buyer_tax_id, buyer_name, invoice_email) -> None:
    if payment_method not in moceo.PAYMENT_METHODS:
        raise VendorError("付款方式只能是 月結 / 貨到付款 / 匯款")
    if delivery_method not in moceo.DELIVERY_METHODS:
        raise VendorError("取貨方式只能是 宅配 / 自取")
    if delivery_method == "宅配" and not (ship_name and ship_phone and ship_address):
        raise VendorError("宅配要有收件人、電話、地址(請管理員到「系統設定 → 叫貨串接」填)")
    if invoice_type not in moceo.INVOICE_TYPES:
        raise VendorError("發票只能是 個人 / 公司")
    if invoice_type == "公司" and not (buyer_tax_id and buyer_name):
        raise VendorError("公司發票要有統一編號與抬頭(請管理員到「系統設定 → 叫貨串接」填)")
    # 膜總裁每一張單都要發票信箱(沒有的話它那邊整張擋掉,而且講的不是人話)
    if not EMAIL.match(invoice_email or ""):
        raise VendorError("要有發票信箱(請管理員到「系統設定 → 叫貨串接」填)")


# ── 明細 ────────────────────────────────────────────────────────────────────
def _lines(rows: list[dict], wanted) -> list[dict]:
    """畫面送來的 [{key, packs}] → 要存的明細。品名、一包幾個、單價一律用廠商剛剛回的,不看畫面送來的。"""
    if not isinstance(wanted, list) or not wanted:
        raise VendorError("至少要叫一項")
    if len(wanted) > MAX_LINES:
        raise VendorError(f"一張叫貨單最多 {MAX_LINES} 項")
    by_key = {r["key"]: r for r in rows}
    seen, out = set(), []
    for line in wanted:
        key = line.get("key") if isinstance(line, dict) else None
        packs = line.get("packs") if isinstance(line, dict) else None
        if not isinstance(key, str) or key not in by_key:
            raise VendorError("有一項膜總裁現在沒有在賣(清單可能更新過),請重新整理再選")
        row = by_key[key]
        if key in seen:
            raise VendorError(f"「{row['name']}」重複了")
        seen.add(key)
        if isinstance(packs, bool) or not isinstance(packs, int) or not 1 <= packs <= MAX_PACKS:
            raise VendorError(f"「{row['name']}」的包數要是 1 到 {MAX_PACKS} 的整數")
        if row["unit_price"] is None:
            raise VendorError(f"「{row['name']}」這個帳號還沒有報價,不能叫")
        out.append({**row, "packs": packs, "qty": packs * row["pack_qty"]})
    return out


def goods_total(items) -> Decimal:
    return sum((Decimal(i["unit_price"]) * i["qty"] for i in items), Decimal("0")).quantize(CENT)


# ── 送出 ────────────────────────────────────────────────────────────────────
def _payload(order: VendorOrder) -> dict:
    body = {
        "idempotency_key": order.vendor_key,
        "items": [{"sku": i.sku, "spec_id": i.spec_id, "qty": i.qty} for i in order.items.all()],
        "payment_method": order.payment_method,
        "delivery_method": order.delivery_method,
        "invoice": {"type": order.invoice_type},
    }
    for field, name in (("buyer_tax_id", "buyer_tax_id"), ("buyer_name", "buyer_name"), ("invoice_email", "email")):
        if getattr(order, field):
            body["invoice"][name] = getattr(order, field)
    if order.delivery_method == "宅配":
        body["ship_to"] = {"name": order.ship_name, "phone": order.ship_phone, "address": order.ship_address}
    if order.note:
        body["note"] = order.note
    return body


def _mark_unknown(order: VendorOrder, why: str) -> VendorOrder:
    VendorOrder.objects.filter(pk=order.pk).exclude(state=VendorOrder.State.PLACED).update(
        state=VendorOrder.State.UNKNOWN, problem=why[:300], sending_since=None, updated_at=timezone.now())
    order.refresh_from_db()
    return order


def _send(order: VendorOrder, key: str, *, first: bool) -> VendorOrder:
    try:
        result = moceo.place(key, _payload(order))
    except moceo.Unreachable as exc:
        return _mark_unknown(order, str(exc))
    if isinstance(result, moceo.Rejected):
        # 第一次送就被擋 = 沒有成立。重送時只有「內容被擋」(400 / 422)能證明先前那一次也沒有成立
        #(廠商是先查這把鑰匙用過沒有、才檢查內容);金鑰無效、太頻繁這些證明不了,照舊是不確定。
        if first or result.status in (400, 422):
            order.delete()
            raise NotPlaced(f"膜總裁沒有收這張單:{result.reason}")
        return _mark_unknown(order, f"沒辦法確認:{result.reason}")
    total, fee = _price(result.total_amount), _price(result.shipping_fee)
    if total is None:
        # 重送拿到「已經成立」時廠商只回單號:總額另外查一次(查不到就先空著,更新進度時會補)
        try:
            total = _price(moceo.order(key, result.order_no).get("total_amount"))
        except (moceo.Unreachable, moceo.Refused):
            total = None
    order.state = VendorOrder.State.PLACED
    order.problem, order.sending_since = "", None
    order.vendor_order_no = result.order_no[:40]
    order.total_amount, order.shipping_fee = total, fee
    order.amount_matches = None if total is None or fee is None else (total - fee == order.expected_goods)
    order.is_test = result.sandbox
    order.save()
    return order


def place(*, tenant, user, link, request_key, lines, payment_method=None, delivery_method=None, note=""):
    """建立並送出一張叫貨單。回 (叫貨單, 是不是這一次新建的)。同一把鑰匙再來:已成立就回那一張,不確定就再送一次。"""
    if not isinstance(request_key, str) or not REQUEST_KEY.match(request_key):
        raise VendorError("這張叫貨單的編號不對,請重新整理頁面再試")
    existing = VendorOrder.objects.filter(tenant=tenant, request_key=request_key).first()
    if existing is not None:
        return _again(existing, link), False

    key = key_of(link)
    items = _lines(live_rows(link, key), lines)
    header = dict(
        payment_method=payment_method or link.payment_method,
        delivery_method=delivery_method or link.delivery_method,
        # 收件與發票只用管理員設定的那一份:畫面送什麼都不看(不然貨可以寄到任何地方)
        ship_name=link.ship_name, ship_phone=link.ship_phone, ship_address=link.ship_address,
        invoice_type=link.invoice_type, buyer_tax_id=link.buyer_tax_id, buyer_name=link.buyer_name,
        invoice_email=link.invoice_email,
    )
    check_header(**header)
    note = note.strip()[:200] if isinstance(note, str) else ""
    try:
        with transaction.atomic():
            order = VendorOrder.objects.create(
                tenant=tenant, provider=link.provider, link=link, warehouse=link.warehouse,
                request_key=request_key, vendor_key=f"pos-{tenant.code}-{request_key}"[:100],
                key_fingerprint=secrets.fingerprint(key),
                state=VendorOrder.State.SENDING, sending_since=timezone.now(),
                expected_goods=goods_total(items), note=note, created_by=user, **header,
            )
            VendorOrderItem.objects.bulk_create([
                VendorOrderItem(
                    tenant=tenant, order=order, line_no=n, sku=i["sku"], spec_id=i["spec_id"],
                    spec_label=i["spec_label"][:120], name=i["name"][:200], unit=i["unit"][:10],
                    pack_qty=i["pack_qty"], packs=i["packs"], qty=i["qty"], unit_price=i["unit_price"],
                ) for n, i in enumerate(items, start=1)
            ])
    except IntegrityError:
        # 同一把鑰匙的另一個請求剛好先建了(連按兩下)
        existing = VendorOrder.objects.filter(tenant=tenant, request_key=request_key).first()
        if existing is None:
            raise
        return _again(existing, link), False
    return _send(order, key, first=True), True


def _again(order: VendorOrder, link) -> VendorOrder:
    if link is not None and order.warehouse_id != link.warehouse_id:
        raise VendorError("這把鑰匙是另一家門市的叫貨單")
    return order if order.state == VendorOrder.State.PLACED else resend(order)


def resend(order: VendorOrder) -> VendorOrder:
    """「不確定」的那一張再送一次(同一把鑰匙)。已成立的原樣回。"""
    with transaction.atomic():
        locked = VendorOrder.objects.select_for_update().filter(pk=order.pk).first()
        if locked is None:
            raise VendorError("這張叫貨單已經不在了")
        if locked.state == VendorOrder.State.PLACED:
            return locked
        if (locked.state == VendorOrder.State.SENDING and locked.sending_since
                and timezone.now() - locked.sending_since < SENDING_GRACE):
            raise Busy("這張叫貨單正在送出,請稍等一下再看")
        locked.state, locked.sending_since = VendorOrder.State.SENDING, timezone.now()
        locked.save(update_fields=["state", "sending_since", "updated_at"])
    order = locked
    key = secrets.reveal(order.link)
    if not key:
        _mark_unknown(order, order.problem or "這家門市現在沒有金鑰")
        raise VendorError("這家門市現在沒有膜總裁的金鑰,沒辦法確認這張單;請管理員重新設定之後再送一次")
    if secrets.fingerprint(key) != order.key_fingerprint:
        _mark_unknown(order, "送出之後金鑰換過了")
        raise VendorError("這張叫貨單送出之後,這家門市的金鑰換過了,沒辦法用再送一次來確認。請到膜總裁查這張單有沒有成立")
    if settings.VENDOR_SANDBOX_ONLY:
        # 測試環境:再送之前重新問一次這把金鑰現在還是不是沙盒。同一把金鑰在廠商那邊可以被改成正式的(指紋不會變),
        # 那時候「再送一次」如果先前沒成立,這一次就會在廠商那邊成立一張真的單(複審抓到的)。
        try:
            live_rows(order.link, key)
        except VendorError as exc:
            _mark_unknown(order, order.problem or str(exc))
            raise
    return _send(order, key, first=False)


# ── 進度 ────────────────────────────────────────────────────────────────────
def _text(value, limit):
    return value[:limit] if isinstance(value, str) else ""


def _apply(order: VendorOrder, row: dict) -> None:
    order.vendor_status = _text(row.get("status"), 40)
    order.vendor_payment_status = _text(row.get("payment_status"), 40)
    order.vendor_logistics_status = _text(row.get("logistics_status"), 60)
    order.vendor_shipping_method = _text(row.get("shipping_method"), 40)
    order.vendor_tracking_no = _text(row.get("tracking_no"), 60)
    when = parse_datetime(row["ordered_at"]) if isinstance(row.get("ordered_at"), str) else None
    order.vendor_ordered_at = when or order.vendor_ordered_at
    if order.total_amount is None:
        order.total_amount = _price(row.get("total_amount"))
    order.status_checked_at = timezone.now()
    order.save()


def sync(tenant, link) -> list[dict]:
    """跟廠商要這個帳號最近的訂單:更新 POS 這邊叫貨單的進度,並回「不是從 POS 叫的」那幾張
    (電話、LINE、廠商後台代下的;老闆要看得到全貌)。別家門市從 POS 叫的不列在這裡(在那家門市自己的清單)。"""
    remote = [r for r in _read(moceo.orders, key_of(link), 100)
              if isinstance(r, dict) and isinstance(r.get("order_no"), str) and r["order_no"]]
    by_no = {r["order_no"]: r for r in remote}
    ours = set()
    for order in VendorOrder.objects.filter(
            tenant=tenant, provider=link.provider, state=VendorOrder.State.PLACED, vendor_order_no__in=by_no):
        _apply(order, by_no[order.vendor_order_no])
        ours.add(order.vendor_order_no)
    return [{
        "order_no": r["order_no"],
        "ordered_at": _text(r.get("ordered_at"), 40),
        "status": _text(r.get("status"), 40),
        "payment_status": _text(r.get("payment_status"), 40),
        "logistics_status": _text(r.get("logistics_status"), 60),
        "shipping_method": _text(r.get("shipping_method"), 40),
        "tracking_no": _text(r.get("tracking_no"), 60),
        "total_amount": None if _price(r.get("total_amount")) is None else str(_price(r.get("total_amount"))),
    } for r in remote if r["order_no"] not in ours]
