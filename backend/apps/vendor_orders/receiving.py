"""到貨入庫(第二步):廠商的貨到了,照那張叫貨單開進貨單。

owner 2026-10-10 定的:
- **成本 = 店家實際付給廠商的金額**(含稅,不除 1.05)→ 進貨單課稅別用「未稅」,單價照放;
  單價以廠商那張單**現在**的明細為準(廠商事後會改單、改價),入庫的人改不到。
- 貨到付款的單,進貨單記成現金付款(是不是貨到付款看廠商那張單**現在**的,不是叫貨當下記的)。
- 運費算不算進成本:每家門市固定一種做法(`VendorLink.freight_into_cost`,管理員設)。

動手前紅隊(三個視角)改掉的:
- 預設入庫的數量 = 廠商已出、這家店還沒入的(不是整張還沒入的);比已出的多只提醒不擋。
- 一張叫貨單可以分好幾次入庫;送錯、對不上的那幾行這次不入,留在叫貨單上,另外記一句「到貨問題」。
- 分次入庫時運費照這一次貨款的比例算,最後一次拿剩下的(不是第一次就整筆壓上去)。

庫存與成本的帳只有進貨單那一份:這裡組好內容,交給既有的 `PurchaseOrderSerializer` + `commit_purchase_order`。
"""
import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers as drf_serializers

from apps.catalog.models import Product, SupplierProduct
from apps.core.money import round_money
from apps.identity.normalize import alias_key
from apps.identity.services import _vendor_sku_owner
from apps.parties.models import Supplier
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.serializers import PurchaseOrderSerializer
from apps.purchasing.services import PurchaseOrderError, commit_purchase_order
from apps.tenants.models import PaymentMethod

from . import secrets, services, vendors
from .models import VendorLink, VendorOrder, VendorReceipt, VendorReceiptItem
from .services import VendorError

CENT = Decimal("0.01")
ZERO = Decimal("0")
ORDER_NO = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
CASH_ON_DELIVERY = "貨到付款"


@dataclass
class Line:
    """廠商那張單現在的一行(同一個料號 + 規格 + 是不是免費補發的幾行併成一行)。"""
    sku: str
    spec_id: object
    is_reissue: bool
    spec_label: str = ""
    name: str = ""
    unit: str = ""
    pack_qty: int = 1
    qty: int = 0
    shipped: int = 0
    amount: Decimal = ZERO          # 這一行實際要付的錢(免費補發的是 0)

    @property
    def key(self) -> str:
        return line_key(self.sku, self.spec_id, self.is_reissue)

    @property
    def unit_price(self) -> Decimal:
        return (self.amount / self.qty).quantize(CENT) if self.qty else ZERO

    @property
    def vendor_sku(self) -> str:
        return vendor_sku_of(self.sku, self.spec_id)

    @property
    def title(self) -> str:
        return " ".join(x for x in (self.name, self.spec_label) if x)


def line_key(sku, spec_id, is_reissue) -> str:
    return f"{sku}|{'' if spec_id is None else spec_id}|{'r' if is_reissue else 'p'}"


def vendor_sku_of(sku, spec_id) -> str:
    """記在供應商商品對照上的料號:有規格的一個規格一個(同一個料號底下每一格是不同的膜)。"""
    return sku if spec_id is None else f"{sku}#spec{spec_id}"


def _fee(row: dict) -> Decimal:
    return (services._price(row.get("shipping_fee")) or ZERO).quantize(CENT)


def _payment(order, row: dict) -> str:
    """這張單**現在**的付款方式:以廠商現在回的為準(月結事後改成貨到付款,現金要記得到;複審 2026-10-10),
    廠商沒回這一格才用叫貨當下記的。"""
    live = row.get("payment_method")
    return live.strip()[:20] if isinstance(live, str) and live.strip() else order.payment_method


def _whole(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def lines_of(items, who: str = "廠商") -> list[Line]:
    """廠商回的明細 → 行。**有一行看不懂就整張不給入**(少算一行,庫存就少一行,而且沒有人會發現)。"""
    if not isinstance(items, list) or not items:
        raise VendorError(f"{who}沒有回這張單的明細,先不要入庫")
    merged: dict[str, Line] = {}
    for row in items:
        sku = row.get("sku") if isinstance(row, dict) else None
        qty = _whole(row.get("qty")) if isinstance(row, dict) else None
        spec_id = row.get("spec_id") if isinstance(row, dict) else None
        price = services._price(row.get("unit_price")) if isinstance(row, dict) else None
        if (not isinstance(sku, str) or not sku.strip() or qty is None or qty < 1 or price is None
                or not (spec_id is None or _whole(spec_id) is not None)):
            raise VendorError(f"{who}回的明細有一行看不懂,先不要入庫")
        free = row.get("is_reissue") is True
        subtotal = services._price(row.get("subtotal"))
        amount = ZERO if free else (subtotal if subtotal is not None else price * qty)
        shipped = _whole(row.get("shipped_qty"))
        pack = _whole(row.get("pack_qty"))
        label = " ".join(x for x in (row.get("spec_code"), row.get("spec_name")) if isinstance(x, str) and x)
        line = merged.setdefault(line_key(sku, spec_id, free), Line(
            sku=sku, spec_id=spec_id, is_reissue=free, spec_label=label,
            name=row["name"] if isinstance(row.get("name"), str) else "",
            unit=row["unit"] if isinstance(row.get("unit"), str) else "",
            pack_qty=pack if pack and pack >= 1 else 1,
        ))
        line.qty += qty
        line.shipped += max(shipped or 0, 0)
        line.amount += amount
    return list(merged.values())


def received_by_line(order) -> dict[str, int]:
    """這張叫貨單每一行已經入庫幾個。**進貨單被作廢的那幾次不算**(那幾個回到還沒入庫)。"""
    rows = (VendorReceiptItem.objects
            .filter(receipt__order=order, receipt__purchase_order__is_void=False)
            .values("sku", "spec_id", "is_reissue").annotate(n=Sum("qty")))
    return {line_key(r["sku"], r["spec_id"], r["is_reissue"]): r["n"] for r in rows}


def freight_spent(order) -> Decimal:
    return (VendorReceipt.objects.filter(order=order, purchase_order__is_void=False)
            .aggregate(v=Sum("freight"))["v"] or ZERO)


def suggested_qty(qty: int, shipped: int, received: int) -> int:
    """這一次預設入幾個 = 廠商已出、這家店還沒入的(不會超過還沒入的)。"""
    return max(0, min(qty - received, shipped - received))


def _detail(order):
    if order.state != VendorOrder.State.PLACED or not order.vendor_order_no:
        raise VendorError("這張叫貨單還沒有確定成立,不能入庫")
    vendor = services.vendor_of(order.provider)          # 廠商停用了照樣可以入庫(貨已經叫了)
    found = services._read(vendor, "detail", services.key_of(order.link, vendor), order.vendor_order_no)
    return found, lines_of(found.order.get("items"), vendor.name)


def _in_lock_order(lines):
    """查對照會一行拿一把鎖:固定照料號的順序拿(兩張單同時入庫、行的順序相反,才不會互相等到死結)。"""
    return sorted(lines, key=lambda line: alias_key(line.vendor_sku))


def _owner(tenant, supplier, line: Line):
    return _vendor_sku_owner(tenant, supplier, line.vendor_sku) if supplier is not None else None


def plan(tenant, order) -> dict:
    """到貨入庫那一頁要的東西:廠商這張單現在的每一行、已出 / 已入 / 這次建議入幾個、對到店裡哪個品號。"""
    found, lines = _detail(order)
    row = found.order
    got = received_by_line(order)
    link = order.link
    fee = _fee(row)
    with transaction.atomic():          # 查對照會拿一把交易內的鎖
        owners = {line.key: _owner(tenant, link.supplier, line) for line in _in_lock_order(lines)}
    out = []
    for line in lines:
        done, owner = got.get(line.key, 0), owners[line.key]
        out.append({
            "key": line.key, "sku": line.sku, "spec_id": line.spec_id, "spec_label": line.spec_label,
            "name": line.name, "unit": line.unit, "pack_qty": line.pack_qty, "is_reissue": line.is_reissue,
            "qty": line.qty, "shipped_qty": line.shipped, "received_qty": done, "remaining_qty": line.qty - done,
            "suggested_qty": suggested_qty(line.qty, line.shipped, done),
            "unit_price": str(line.unit_price),
            "product": None if owner is None else {
                "id": owner.id, "sku": owner.sku, "name": owner.name, "is_active": owner.is_active},
        })
    return {
        "order": order.id,
        "vendor_order_no": order.vendor_order_no,
        # 廠商現在回的(不是 POS 上次記的)
        "vendor_status": services._text(row.get("status"), 40),
        "vendor_logistics_status": services._text(row.get("logistics_status"), 60),
        "vendor_tracking_no": services._text(row.get("tracking_no"), 60),
        "payment_method": _payment(order, row),
        "lines": out,
        "shipping_fee": str(fee),
        "freight_into_cost": link.freight_into_cost,
        "freight_left": str(max(fee - freight_spent(order), ZERO).quantize(CENT)),
        "supplier": None if link.supplier is None else {"id": link.supplier_id, "name": link.supplier.name},
        "issue_note": order.issue_note,
    }


# ── 入庫 ────────────────────────────────────────────────────────────────────
def supplier_for(link):
    """這家門市跟這家廠商進貨記在哪個供應商底下;沒指定過就用 / 建一筆跟廠商同名的。"""
    if link.supplier_id:
        return link.supplier
    link = VendorLink.objects.select_for_update().get(pk=link.pk)     # 兩張單同時第一次入庫,只建一筆
    if link.supplier_id:
        return link.supplier
    name = vendors.name_of(link.provider)[:120]
    supplier = (Supplier.objects.filter(tenant=link.tenant, name=name).order_by("id").first()
                or Supplier.objects.create(tenant=link.tenant, name=name))
    link.supplier = supplier
    link.save(update_fields=["supplier", "updated_at"])
    return supplier


def _fits(product, title) -> None:
    """叫貨來的膜只入到按數量管的一般商品。"""
    if not product.is_active:
        raise VendorError(f"「{product.name}」已經停用,不能入庫")
    if product.requires_serial or product.is_secondhand or product.is_virtual:
        raise VendorError(f"「{title}」不能對到「{product.name}」:只能入到按數量管的一般商品(不追序號、不是中古機、不是虛擬商品)")


def _remember(tenant, supplier, line: Line, product, user, supplier_platform: str) -> None:
    SupplierProduct.objects.create(
        tenant=tenant, product=product, supplier=supplier, platform=supplier_platform, vendor_sku=line.vendor_sku[:80],
        variant=line.spec_label[:200], source_name=line.name[:300], pack_qty=line.pack_qty,
        confirmed_by=user, confirmed_at=timezone.now(),
    )


def _retire(tenant, supplier, line: Line, user, why: str) -> None:
    """把這個料號現在的對照停用。**不刪**:留著當紀錄,備註寫誰、什麼時候、為什麼(改對照誰都可以做,所以每一次都要查得到)。"""
    stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    who = user.get_username() if user is not None else ""
    SupplierProduct.objects.filter(
        tenant=tenant, supplier=supplier, is_active=True, vendor_sku_key=alias_key(line.vendor_sku)[:200],
    ).update(is_active=False, note=f"{stamp} {who} {why}"[:200], updated_at=timezone.now())


NOT_CHECKED = object()        # `_map(seen=…)`:這個人是明講要換(連連看那一頁),不用核對他看到的是誰


def _map(tenant, supplier, line: Line, product, user, platform: str, *, seen) -> None:
    """這一行對到哪個品號。沒對過 → 記住;對過、這次指到別的 → 舊的停用留著、記新的。
    能叫貨或能進貨的人都可以改(owner 2026-10-10:「店員都可以」;原本是只有管理員能改)。

    `seen` = 送這個請求的人**畫面上看到**這個料號對到誰(商品編號;None = 他看到的是還沒對過)。
    誰都能改之後,入庫面板開著的那段時間對照可能被別人改掉或解除 —— **他看到的跟現在的不一樣 = 他看的是舊畫面:不入、對照也不動**,請他重開。
    不這樣擋:甲看到的是對到 A、乙改成 B(或解除)、甲按確認 → 貨入到 A、乙的修正被悄悄改回去。
    送來的品號就是現在對到的那一個 → 沒有東西要改,不用核對。連連看那一頁是明講要換,給 `NOT_CHECKED`。
    """
    owner = _owner(tenant, supplier, line)
    if owner is not None and owner.id == product.id:
        return
    if seen is not NOT_CHECKED and seen != (owner.id if owner is not None else None):
        if owner is None:
            raise VendorError(f"「{line.title}」的對照剛被解除,請重新打開再試")
        raise VendorError(f"「{line.title}」現在對到的是「{owner.name}」(對照剛被改過),請重新打開再試")
    if owner is not None:
        _retire(tenant, supplier, line, user, f"改對到 {product.sku}")
        still = _owner(tenant, supplier, line)
        if still is not None and still.id != product.id:
            raise VendorError(f"「{line.title}」在商品的其他叫法裡已經對到「{still.name}」,要先到那個商品把這個叫法拿掉")
        if still is not None:
            return
    _remember(tenant, supplier, line, product, user, platform)


def _freight_share(link, fee: Decimal, spent: Decimal, lines, got, picked) -> Decimal:
    """這一次入庫要算進成本的運費。沒有要算、沒有運費、這一次沒有付錢的貨 → 0。
    這一次之後整張入完 → 剩下的全部;不然照這一次貨款佔整張貨款的比例(四捨五入到元),不超過剩下的。"""
    left = max(fee - spent, ZERO)
    paid_now = sum((line.unit_price * qty for line, qty in picked if not line.is_reissue), ZERO)
    if not link.freight_into_cost or left <= 0 or paid_now <= 0:
        return ZERO
    now = {line.key: qty for line, qty in picked}
    if all(got.get(line.key, 0) + now.get(line.key, 0) >= line.qty for line in lines):
        return left
    paid_all = sum((line.amount for line in lines if not line.is_reissue), ZERO)
    return min(left, round_money(fee * paid_now / paid_all)) if paid_all > 0 else ZERO


def _spread(share: Decimal, picked) -> dict[str, Decimal]:
    """把這一次的運費照各行貨款的比例分下去(整數元);最後一行拿剩下的(加起來一定等於這一次的運費)。
    進貨單的單價只到分:一行超過一百個時,那一行的金額可能跟「貨款 + 運費」差一塊錢(成本本來就是平均值)。"""
    paid = [(line, qty) for line, qty in picked if not line.is_reissue and line.unit_price * qty > 0]
    total = sum((line.unit_price * qty for line, qty in paid), ZERO)
    out, used = {}, ZERO
    for n, (line, qty) in enumerate(paid, start=1):
        part = share - used if n == len(paid) else min(share - used, round_money(share * line.unit_price * qty / total))
        out[line.key] = part
        used += part
    return out


def _wanted(lines) -> list[tuple[str, int, int, object]]:
    """畫面送來的每一行 → (哪一行, 幾個, 入到哪個品號, 他看到這一行原本對到誰)。
    `was` 沒帶 = 他看到的是還沒對過(None)。"""
    if not isinstance(lines, list) or not lines:
        raise VendorError("這一次沒有要入庫的東西")
    seen, out = set(), []
    for row in lines:
        key = row.get("key") if isinstance(row, dict) else None
        qty = _whole(row.get("qty")) if isinstance(row, dict) else None
        product = _whole(row.get("product")) if isinstance(row, dict) else None
        if not isinstance(key, str) or qty is None or qty < 1 or product is None:
            raise VendorError("入庫的內容不完整(每一行要有數量與對到的品號)")
        was = row.get("was")
        if was is not None and (_whole(was) is None or was < 1):
            raise VendorError("入庫的內容不完整(原本對到的品號不對)")
        if key in seen:
            raise VendorError("同一行重複了")
        seen.add(key)
        out.append((key, qty, product, was))
    return out


def _lock_request(tenant, request_key) -> None:
    """同一把鑰匙的入庫請求一次只跑一個,到那個請求整個結束(交易結束)才放。

    畫面在「上一次沒有拿到答覆」時會拿同一把鑰匙再送一次,而且把這一次的答覆當成定論:被擋(400)= 上一次也沒入,
    之後可以開新的一次。上一次如果其實還在跑(伺服器還在等廠商回明細),沒有這把鎖的話,再送的這一次會自己去問廠商、
    自己失敗、回 400 —— 然後上一次才成立,畫面卻已經當成沒入(複審第二輪之後補的)。
    有這把鎖:再送的這一次先等上一次跑完,再看那把鑰匙有沒有入過。
    只擋同一把鑰匙;握著它等廠商不會卡到別人(叫貨單那一列的鎖還是等問完廠商才拿)。
    """
    if connection.vendor != "postgresql":
        return
    digest = hashlib.sha256(f"vendor-receive:{tenant.id}:{request_key}".encode("utf-8")).digest()
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [int.from_bytes(digest[:8], "big", signed=True)])


def receive(*, tenant, user, order, request_key, lines):
    """照這張叫貨單開一張進貨單。回 (這一次入庫, 是不是這一次新做的)。同一把鑰匙再來回同一次,不會入兩次。
    丟 `VendorError` = 這把鑰匙沒有入過、這一次也沒有入(畫面靠這個決定可不可以開新的一次)。"""
    if not isinstance(request_key, str) or not services.REQUEST_KEY.match(request_key):
        raise VendorError("這一次入庫的編號不對,請重新整理頁面再試")
    with transaction.atomic():
        _lock_request(tenant, request_key)
        return _receive(tenant=tenant, user=user, order=order, request_key=request_key, lines=lines)


def _receive(*, tenant, user, order, request_key, lines):
    done = VendorReceipt.objects.filter(tenant=tenant, request_key=request_key).first()
    if done is not None:
        if done.order_id != order.id:
            raise VendorError("這把鑰匙是另一張叫貨單的入庫")
        return done, False
    wanted = _wanted(lines)
    who = vendors.name_of(order.provider)
    found, vendor_lines = _detail(order)          # 廠商這張單現在的樣子(還沒拿叫貨單那一列的鎖:不能握著它等外面的系統)
    by_key = {line.key: line for line in vendor_lines}
    fee = _fee(found.order)
    try:
        with transaction.atomic():
            locked = VendorOrder.objects.select_for_update().get(pk=order.pk)
            done = VendorReceipt.objects.filter(tenant=tenant, request_key=request_key).first()
            if done is not None:
                return done, False
            supplier = supplier_for(locked.link)
            link = VendorLink.objects.get(pk=locked.link_id)
            got = received_by_line(locked)
            products = {p.id: p for p in Product.objects.filter(tenant=tenant, pk__in=[w[2] for w in wanted])}
            for key, *_ in wanted:
                if key not in by_key:
                    raise VendorError(f"{who}那張單現在沒有這一行(可能改過單),請重新打開入庫再試")
            picked = []
            for key, qty, product_id, was in sorted(wanted, key=lambda w: alias_key(by_key[w[0]].vendor_sku)):
                line = by_key[key]
                left = line.qty - got.get(key, 0)
                if qty > left:
                    raise VendorError(f"「{line.title}」最多還能入 {max(left, 0)} 個(叫 {line.qty}、已經入 {line.qty - left})")
                product = products.get(product_id)
                if product is None:
                    raise VendorError(f"「{line.title}」對到的商品找不到")
                _fits(product, line.title)
                _map(tenant, supplier, line, product, user, locked.provider, seen=was)
                picked.append((line, qty, product))
            share = _freight_share(link, fee, freight_spent(locked), vendor_lines, got, [(l, q) for l, q, _ in picked])
            extra = _spread(share, [(l, q) for l, q, _ in picked])
            items = []
            for line, qty, product in picked:
                if line.is_reissue:        # 瑕疵補發:數量照入、不計價(平均成本被攤低)
                    items.append({"product": product.id, "qty": qty, "billed_qty": 0, "unit_price": "0"})
                else:
                    cost = ((line.unit_price * qty + extra.get(line.key, ZERO)) / qty).quantize(CENT)
                    items.append({"product": product.id, "qty": qty, "unit_price": str(cost)})
            cash = None
            pay = _payment(locked, found.order)
            if pay == CASH_ON_DELIVERY:
                cash = (PaymentMethod.objects.filter(tenant=tenant, kind=PaymentMethod.Kind.CASH, is_active=True)
                        .order_by("sort_order", "id").first())
            note = f"{who} {locked.vendor_order_no} 到貨入庫"
            if fee > 0 and not link.freight_into_cost:
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
                    tenant=tenant, receipt=receipt, sku=line.sku[:80], spec_id=line.spec_id, is_reissue=line.is_reissue,
                    name=line.title[:200], qty=qty, unit_price=line.unit_price, product=product,
                ) for line, qty, product in picked
            ])
            services._apply(locked, found.order)       # 順手把廠商那邊現在的進度記回來
            if pay != locked.payment_method:           # 付款方式被廠商改過:叫貨紀錄跟著寫現在的(跟進貨單一致)
                locked.payment_method = pay
                locked.save(update_fields=["payment_method", "updated_at"])
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


# ── 不是從 POS 叫的單 ────────────────────────────────────────────────────────
def outside_key(provider: str, order_no: str) -> str:
    """認進來的單沒有畫面的鑰匙,自己編一把:**一家廠商的一個單號一把**。
    兩家廠商各自編號,單號可以一模一樣 —— 只用單號編的話,第二家的那一張會撞到「一家公司裡鑰匙不重複」而認不進來(複審 2026-10-10)。
    用雜湊不用直接接起來:「廠商代碼 + 單號」可能比欄位長,截掉會撞。"""
    digest = hashlib.sha256(f"{provider}\n{order_no}".encode("utf-8")).hexdigest()
    return f"outside-{digest[:40]}"


def adopt(*, tenant, user, link, order_no):
    """把廠商那邊「不是從這裡叫的」一張單認進來(電話、LINE、廠商代下的),之後才能到貨入庫。明細不存,每次跟廠商要。"""
    order_no = order_no.strip() if isinstance(order_no, str) else ""
    if not ORDER_NO.match(order_no):
        raise VendorError("單號不對")

    def existing():
        return VendorOrder.objects.filter(tenant=tenant, provider=link.provider, vendor_order_no=order_no) \
            .select_related("warehouse").first()

    def mine(order):
        if order.warehouse_id != link.warehouse_id:
            raise VendorError(f"這張單已經在「{order.warehouse.name}」那一家")
        return order

    order = existing()
    if order is not None:
        return mine(order)
    vendor = services.vendor_of(link.provider)
    key = services.key_of(link, vendor)
    found = services._read(vendor, "detail", key, order_no)
    lines = lines_of(found.order.get("items"), vendor.name)
    row = found.order
    text = lambda name, limit: row[name][:limit] if isinstance(row.get(name), str) else ""      # noqa: E731
    try:
        with transaction.atomic():
            order = VendorOrder(
                tenant=tenant, provider=link.provider, link=link, warehouse=link.warehouse,
                source=VendorOrder.Source.OUTSIDE, state=VendorOrder.State.PLACED,
                request_key=outside_key(link.provider, order_no), vendor_key="", key_fingerprint=secrets.fingerprint(key),
                vendor_order_no=order_no, expected_goods=sum((line.amount for line in lines), ZERO),
                payment_method=text("payment_method", 20), delivery_method=text("delivery_method", 20),
                invoice_type="", is_test=found.sandbox, created_by=user,
                shipping_fee=services._price(row.get("shipping_fee")),       # 總額由下面的 _set_progress 填
            )
            services._set_progress(order, row)
            order.save()
    except IntegrityError:
        order = existing()
        if order is None:
            raise
        return mine(order)
    return order


def set_issue(order, note) -> VendorOrder:
    order.issue_note = note.strip()[:300] if isinstance(note, str) else ""
    order.save(update_fields=["issue_note", "updated_at"])
    return order
