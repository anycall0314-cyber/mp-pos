"""出貨:一次出貨 = 一張銷貨單(客戶 = 那個同行)。庫存與成本的帳只有銷貨單那一份,這裡記「哪張批發單的哪幾行、這一次出了幾個、哪幾台」。

紅隊(批發商立場)2026-10-14 第 2 條:**不用先打開哪一張單,直接刷那一台**(`scan` 找出它是哪一張單的哪一行);
找不到的那一台按「這台不出」(`orders.drop`),其餘的照樣出。

鎖的順序見 `base.py`:先鎖這一次要出的序號,才鎖批發單,最後才是銷貨過帳裡的庫存餘額。
"""
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers as drf_serializers

from apps.catalog.models import Category, Product
from apps.core.money import round_money
from apps.identity.normalize import normalize_serial
from apps.inventory.identifiers import codes_of, find_serial_ids
from apps.inventory.locking import lock_stock_rows
from apps.inventory.models import ProductSerial
from apps.sales.models import SalesOrder, SalesOrderItem, SalesOrderItemSerial, SalesOrderPayment
from apps.sales.services import SalesOrderError, commit_sales_order, void_sales_order

from . import orders, payments
from .base import ZERO, TradeError, credit_method, customer_for
from .models import TradeOrder, TradeOrderLine, TradeShipment, TradeShipmentLine, TradeShipmentSerial, TradeUnit

S = TradeOrder.Status
FREIGHT_NAME = "批發運費"
SYSTEM_CATEGORY = "SYS"
MAX_FEE = 99_999


def freight_product(tenant) -> Product:
    """運費那一行用的虛擬商品(一家公司一個;跟「收購二手」同一個系統類別)。"""
    found = Product.objects.filter(tenant=tenant, name=FREIGHT_NAME, is_virtual=True).order_by("id").first()
    if found is not None:
        return found
    category = Category.objects.filter(tenant=tenant, code=SYSTEM_CATEGORY).first() or Category.objects.create(
        tenant=tenant, code=SYSTEM_CATEGORY, name="系統項目", is_active=True, sort_order=9999)
    return Product.objects.create(
        tenant=tenant, category=category, name=FREIGHT_NAME, list_price=0, requires_serial=False, is_virtual=True,
        is_secondhand=False, counts_cash=True, counts_margin=False, is_active=True)


# ── 刷到一台:它是哪一張單的 ───────────────────────────────────────────────────
def scan(tenant, warehouse, code) -> dict:
    """刷到的碼是哪一台、可以出在哪幾行(由舊到新)。中古機 = 訂著它的那一行;全新機 = 訂了這個商品、還沒出完的每一行。"""
    ids = find_serial_ids(tenant, code if isinstance(code, str) else "")
    if not ids:
        raise TradeError("找不到這個碼")
    if len(ids) > 1:
        raise TradeError("這個碼對到不只一台,請改刷另一個碼(IMEI / SN)")
    serial = ProductSerial.objects.select_related("product", "warehouse").prefetch_related("identifiers").get(pk=ids[0])
    held = TradeOrderLine.objects.filter(tenant=tenant, unit=serial, holding=True).select_related("order").first()
    if held is not None:
        lines = [held]
    else:
        lines = list(TradeOrderLine.objects.filter(
            tenant=tenant, product=serial.product, unit__isnull=True, order__status__in=orders.OPEN_STATES)
            .select_related("order").order_by("order_id", "line_no", "id"))
        lines = [line for line in lines if line.open_qty > 0]
    if not lines:
        raise TradeError(f"{serial.serial_no}({serial.product.name})沒有同行訂")
    if all(line.order.status == S.PENDING for line in lines):
        raise TradeError(f"{serial.serial_no} 是 {lines[0].order.no} 訂的,那張單還沒接單")
    if serial.status != ProductSerial.Status.IN_STOCK:
        raise TradeError(f"{serial.serial_no} 現在是「{serial.get_status_display()}」,不能出貨")
    if warehouse is not None and serial.warehouse_id != warehouse.id:
        where = serial.warehouse.name if serial.warehouse_id else "別的地方"
        raise TradeError(f"{serial.serial_no} 在「{where}」,要由那一家出貨")
    return {
        "serial": serial.id, "serial_no": serial.serial_no, **codes_of(serial), "name": serial.product.name,
        "lines": [{"order": line.order_id, "order_no": line.order.no, "line": line.id, "open_qty": line.open_qty}
                  for line in lines if line.order.status == S.ACCEPTED],
    }


# ── 出貨 ────────────────────────────────────────────────────────────────────
def _wanted(lines) -> list[tuple[int, int, list[int]]]:
    if not isinstance(lines, list) or not lines:
        raise TradeError("這一次沒有要出的東西")
    out, seen = [], set()
    for row in lines:
        line_id = row.get("line") if isinstance(row, dict) else None
        qty = row.get("qty") if isinstance(row, dict) else None
        serials = row.get("serials", []) if isinstance(row, dict) else None
        ok = (isinstance(line_id, int) and not isinstance(line_id, bool) and isinstance(qty, int) and not isinstance(qty, bool)
              and qty >= 1 and isinstance(serials, list)
              and all(isinstance(x, int) and not isinstance(x, bool) for x in serials))
        if not ok or line_id in seen:
            raise TradeError("出貨的內容不對")
        seen.add(line_id)
        out.append((line_id, qty, serials))
    return out


def _fee(value) -> Decimal:
    if value in (None, ""):
        return ZERO
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_FEE:
        raise TradeError(f"運費要是 0 到 {MAX_FEE} 的整數")
    return Decimal(value)


def ship(*, tenant, user, order, request_key, warehouse, lines, shipping_fee=None, tracking_no="", shipping_method=""):
    """出一次貨。回 (這一次出貨, 是不是這一次新做的)。同一把鑰匙再來回同一次,不會出兩次。"""
    if not isinstance(request_key, str) or not orders.BUYER_KEY.match(request_key) or len(request_key) > 50:
        raise TradeError("這一次出貨的編號不對,請重新整理頁面再試")

    def done():
        found = TradeShipment.objects.filter(tenant=tenant, request_key=request_key).first()
        if found is not None and found.order_id != order.id:
            raise TradeError("這把鑰匙是另一張批發單的出貨")
        return found

    found = done()
    if found is not None:
        return found, False
    wanted = _wanted(lines)
    fee = _fee(shipping_fee)
    if warehouse.tenant_id != tenant.id or not warehouse.is_active:
        raise TradeError("出貨的門市不對")
    try:
        with transaction.atomic():
            lock_stock_rows(tenant, serial_ids=[x for _, _, serials in wanted for x in serials])
            order = orders._locked(order)
            found = done()
            if found is not None:
                return found, False
            if order.tenant_id != tenant.id:
                raise TradeError("這張批發單已經不在了")
            if order.status == S.PENDING:
                raise TradeError("這張單還沒接單")
            if order.status != S.ACCEPTED:
                raise TradeError(f"這張單現在是「{order.get_status_display()}」,不能出貨")
            by_id = {line.id: line for line in order.lines.select_related("product__condition")}
            picked = []
            for line_id, qty, serial_ids in wanted:
                line = by_id.get(line_id)
                if line is None:
                    raise TradeError("這張單沒有這一行(可能改過),請重新整理")
                if qty > line.open_qty:
                    raise TradeError(f"「{line.name}」還沒出的只有 {line.open_qty} 個")
                if line.unit_id:
                    if serial_ids != [line.unit_id]:
                        raise TradeError(f"「{line.name}」訂的是指定的那一台,要刷那一台")
                elif line.product.requires_serial:
                    if len(serial_ids) != qty or len(set(serial_ids)) != qty:
                        raise TradeError(f"「{line.name}」要出 {qty} 台,刷了 {len(set(serial_ids))} 台")
                elif serial_ids:
                    raise TradeError(f"「{line.name}」不用刷序號")
                picked.append((line, qty, serial_ids))
            used = [x for _, _, serial_ids in picked for x in serial_ids]
            if len(set(used)) != len(used):
                raise TradeError("同一台刷了兩次")
            serials = {s.id: s for s in ProductSerial.objects.filter(tenant=tenant, pk__in=used).prefetch_related("identifiers")}
            if len(serials) != len(used):
                raise TradeError("有一台找不到")
            customer = customer_for(order.partner)
            # 這一次要出的那幾台先放掉「訂著」(下面過帳時 `holds.before_sale` 才不會把自己擋下來;過帳失敗整段會退回)
            for line, _, _ in picked:
                if line.holding:
                    line.holding = False
                    line.save(update_fields=["holding", "updated_at"])
            goods = sum((round_money(line.unit_price * qty) for line, qty, _ in picked), ZERO)
            so = SalesOrder.objects.create(
                tenant=tenant, customer=customer, source_name=order.partner.name[:120], warehouse=warehouse,
                doc_date=date.today(), sales_type=SalesOrder.SalesType.SALE,
                tax_method=SalesOrder.TaxMethod.TAXABLE_INCLUDED, buyer_tax_id=order.buyer_tax_id[:20],
                note=f"批發 {order.no} 出貨"[:200], created_by=user if getattr(user, "is_authenticated", False) else None)
            n = 0
            for n, (line, qty, serial_ids) in enumerate(picked, start=1):
                item = SalesOrderItem.objects.create(
                    tenant=tenant, so=so, line_no=n, product=line.product, qty=qty, unit_price=line.unit_price,
                    amount=round_money(line.unit_price * qty))
                SalesOrderItemSerial.objects.bulk_create([
                    SalesOrderItemSerial(tenant=tenant, item=item, serial_id=serial_id, line_pos=pos)
                    for pos, serial_id in enumerate(serial_ids)])
            if fee > 0:
                SalesOrderItem.objects.create(
                    tenant=tenant, so=so, line_no=n + 1, product=freight_product(tenant), qty=1, unit_price=fee, amount=fee)
            if goods + fee != 0:
                SalesOrderPayment.objects.create(
                    tenant=tenant, so=so, line_no=1, method=credit_method(tenant).code, amount=goods + fee)
            commit_sales_order(so)
            count = TradeShipment.objects.filter(order=order).count()
            shipment = TradeShipment.objects.create(
                tenant=tenant, order=order, no=f"{order.no}-{count + 1}", warehouse=warehouse, sales_order=so,
                request_key=request_key, shipping_method=orders._text(shipping_method, 40),
                tracking_no=orders._text(tracking_no, 60), shipping_fee=fee, goods_amount=goods,
                created_by=user if getattr(user, "is_authenticated", False) else None)
            for line, qty, serial_ids in picked:
                line.shipped_qty += qty
                line.save(update_fields=["shipped_qty", "updated_at"])
                row = TradeShipmentLine.objects.create(tenant=tenant, shipment=shipment, line=line, qty=qty)
                rows = []
                for serial_id in serial_ids:
                    serial = serials[serial_id]
                    rows.append(TradeShipmentSerial(
                        tenant=tenant, shipment_line=row, serial=serial, **codes_of(serial), grade=serial.condition_grade,
                        battery=serial.battery_health, note=serial.condition_note[:200]))
                TradeShipmentSerial.objects.bulk_create(rows)
            orders._after_change(order)
    except SalesOrderError as exc:
        raise TradeError(str(exc)) from None
    except drf_serializers.ValidationError as exc:
        detail = exc.detail.get("detail") if isinstance(exc.detail, dict) else None
        raise TradeError(str(detail or "銷貨單開不出來")) from None
    except IntegrityError:
        found = done()               # 同一把鑰匙的另一個請求剛好先做完
        if found is None:
            raise
        return found, False
    return shipment, True


# ── 買家收了多少 ────────────────────────────────────────────────────────────
def live_shipped(order: TradeOrder, *, without: TradeShipment | None = None) -> dict[int, int]:
    """這張單每一行現在算數的已出數量(沒取消、沒被整張銷退的那幾次出貨)。買家看到的「已出」是這個數。
    `without` = 不算這一次(問「少了這一次還剩多少」用)。"""
    live = payments.live_shipments(TradeShipment.objects.filter(order=order))
    if without is not None:
        live = live.exclude(pk=without.pk)
    rows = TradeShipmentLine.objects.filter(shipment__in=live).values("line_id").annotate(n=Sum("qty"))
    return {row["line_id"]: row["n"] or 0 for row in rows}


def _code_key(entry) -> str:
    if not isinstance(entry, dict):
        return ""
    code = entry.get("imei") if isinstance(entry.get("imei"), str) and entry["imei"].strip() else entry.get("sn")
    return normalize_serial(code) if isinstance(code, str) else ""


def report_received(order: TradeOrder, items) -> TradeOrder:
    """買家回報這張單**到現在為止**每一行收進庫存幾個、哪幾台(整張單現在的樣子,不是這一次多收的;沒列到的行 = 0)。
    收的不能比算數的已出多(取消的出貨、整張銷退掉的出貨不能再收)。"""
    if not isinstance(items, list) or len(items) > orders.MAX_LINES:
        raise TradeError("回報的內容不對", "bad_item")
    with transaction.atomic():
        order = orders._locked(order)
        lines = list(order.lines.all())
        spec_of = dict(TradeUnit.objects.filter(serial_id__in=[l.unit_id for l in lines if l.unit_id]).values_list("serial_id", "id"))
        by_key = {(line.sku, spec_of.get(line.unit_id)): line for line in lines}
        wanted, codes = {}, set()
        for row in items:
            sku = row.get("sku") if isinstance(row, dict) else None
            spec = row.get("spec_id") if isinstance(row, dict) else None
            qty = row.get("received_qty") if isinstance(row, dict) else None
            serials = row.get("serials", []) if isinstance(row, dict) else None
            line = by_key.get((sku, spec)) if isinstance(sku, str) else None
            if (line is None or line.id in wanted or isinstance(qty, bool) or not isinstance(qty, int) or qty < 0
                    or not isinstance(serials, list)):
                raise TradeError("回報的內容不對", "bad_item")
            keys = {_code_key(entry) for entry in serials}
            if "" in keys or len(keys) != len(serials) or (line.product.requires_serial and len(keys) != qty):
                raise TradeError(f"「{line.name}」回報的序號不對", "bad_item")
            wanted[line.id] = qty
            codes |= keys
        shipped = live_shipped(order)
        for line in lines:
            qty = wanted.get(line.id, 0)
            if qty > shipped.get(line.id, 0):
                raise TradeError(f"「{line.name}」收的({qty})比出的({shipped.get(line.id, 0)})多;取消的出貨不能入庫", "over_received")
            if qty != line.received_qty:
                line.received_qty = qty
                line.save(update_fields=["received_qty", "updated_at"])
        live = payments.live_shipments(TradeShipment.objects.filter(order=order))
        found = set()
        for unit in TradeShipmentSerial.objects.filter(shipment_line__shipment__in=live):
            key = normalize_serial(unit.imei or unit.sn)
            found.add(key)
            if unit.received != (key in codes):
                unit.received = key in codes
                unit.save(update_fields=["received", "updated_at"])
        if codes - found:
            raise TradeError("回報的序號有這張單沒有出的(可能已經取消出貨)", "over_received")
        # 已經不算數的出貨(取消的、整張銷退掉的)上面的那幾台一律不算已收
        TradeShipmentSerial.objects.filter(shipment_line__shipment__order=order, received=True) \
            .exclude(shipment_line__shipment__in=live).update(received=False)
    return order


def received_block(shipment: TradeShipment) -> str | None:
    """買家已經收進庫存的貨不能取消出貨、不能整張銷退(同一批貨不能兩家都在庫)。回為什麼不行(None = 可以)。
    呼叫的人要先鎖那張批發單(買家的回報也是鎖著它寫的)。"""
    why = "買家已經把這一次出的貨入庫了;要退貨請對方先作廢那張進貨單,再回來處理"
    if TradeShipmentSerial.objects.filter(shipment_line__shipment=shipment, received=True).exists():
        return why
    # 少了這一次之後,其餘算數的出貨要蓋得住買家已經收的
    # (不用「全部 − 這一次」:整張銷退走到這裡時銷退單已經建好,這一次本身已經不算數了)
    rest = live_shipped(shipment.order, without=shipment)
    for row in shipment.lines.select_related("line"):
        if row.line.received_qty > rest.get(row.line_id, 0):
            return why
    return None


def before_return(tenant, sales_order_id, error) -> None:
    """整張銷退之前(`sales.services.commit_sales_return` 一開始呼叫):這張銷貨單是批發出貨開的、而且買家已經入庫 → 擋。
    鎖的順序跟取消出貨一樣:那一次的序號 → 批發單(之後銷退才鎖銷貨單)。"""
    shipment = TradeShipment.objects.filter(tenant=tenant, sales_order_id=sales_order_id, is_void=False).select_related("order").first()
    if shipment is None:
        return
    lock_stock_rows(tenant, serial_ids=list(
        TradeShipmentSerial.objects.filter(shipment_line__shipment=shipment).values_list("serial_id", flat=True)))
    order = orders._locked(shipment.order)
    shipment.order = order
    why = received_block(shipment)
    if why:
        raise error(why)
    order.changed_at = timezone.now()                      # 買家那邊看到的已出會少掉這一次
    order.save(update_fields=["changed_at", "updated_at"])


def void(shipment: TradeShipment, user) -> TradeShipment:
    """取消一次出貨:銷貨單作廢、貨回到庫存、那幾行回到還沒出(中古機回到被這張單訂著)。買家已經入庫的不能取消。"""
    serial_ids = list(TradeShipmentSerial.objects.filter(shipment_line__shipment=shipment).values_list("serial_id", flat=True))
    try:
        with transaction.atomic():
            lock_stock_rows(shipment.tenant, serial_ids=serial_ids)
            order = orders._locked(shipment.order)
            shipment = TradeShipment.objects.select_related("sales_order").get(pk=shipment.pk)
            if shipment.is_void:
                raise TradeError("這一次出貨已經取消過了")
            shipment.order = order
            why = received_block(shipment)
            if why:
                raise TradeError(why, "received")
            so = shipment.sales_order
            so.trade_void_ok = True
            void_sales_order(so, user)
            for row in shipment.lines.select_related("line"):
                line = row.line
                line.shipped_qty -= row.qty
                line.holding = bool(line.unit_id) and line.open_qty > 0
                line.save(update_fields=["shipped_qty", "holding", "updated_at"])
            TradeUnit.objects.filter(tenant=shipment.tenant, serial_id__in=serial_ids).update(is_listed=True, updated_at=timezone.now())
            shipment.is_void, shipment.voided_at = True, timezone.now()
            shipment.save(update_fields=["is_void", "voided_at", "updated_at"])
            if order.status == S.SHIPPED:
                order.status, order.closed_at = S.ACCEPTED, None
            order.changed_at = timezone.now()
            order.save(update_fields=["status", "closed_at", "changed_at", "updated_at"])
    except SalesOrderError as exc:
        raise TradeError(str(exc)) from None
    return shipment
