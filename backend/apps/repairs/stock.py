"""自家庫存的機器送去整理(2026-10-29)。

owner:「中古機當下回收,依收購價入庫,但由於機況實在太差,後續整理完後再銷售,整理有可能外包廠商或自行維修」
→ 整理花的錢加進那一台的成本(收購價 + 整理費 = 這一台的成本),賣掉時毛利照這個總數算。同一天定:「工資先不算」。

做法:開維修單時選「自家庫存」、刷那一台(`RepairOrder.stock_serial`)。
- 建單(`start`):那一台 在庫 → 整理中(`ProductSerial.Status.REFURB`):還掛在原門市、算庫存、平均成本照算;
  不能賣、不能調撥、不能送廠商換貨、盤點不用刷(盤點單另外列出來)。只收「在庫」的(已退的先確認可賣);
  鎖在門市的帳號只能刷自己門市的。
- 完工(`finish`):加進那一台成本的金額 = 維修毛利那一套的「零件成本 + 委外費用」(`services.money_of` 的
  parts + outside,實際成本;工資、內部結算價不算);那一台 整理中 → 在庫;商品的平均成本照加權平均把這筆加進去
  (除以帳上的台數,跟進貨同一套)。金額記在單上(`stock_cost_added`)。
- 重開(`undo`):照記下來的金額扣回去,那一台 在庫 → 整理中;已經不是在庫(賣掉、調撥中、又送去整理…)就不能重開。
- 作廢(`release`,還沒完工才能作廢):那一台 整理中 → 在庫。
- 每一步寫一筆「整理」異動:不寫門市、不動數量,只是序號履歷上的紀錄;備註不寫金額。
- 不收客人的錢(實付一定 0、沒有收款方式),不算維修月報(`report.completed`)。

鎖的順序照 `inventory/locking.py`:維修單 → 商品(零件與那一台的商品一次)→ 那一台 → 庫存餘額。
呼叫端先 `prepare()` 拿到那一台(還沒鎖),把它的商品、編號放進同一次 `lock_stock_rows`,鎖完 `reread()` 才檢查。
"""
from decimal import Decimal

from apps.inventory.locking import lock_stock_rows
from apps.inventory.models import COSTED_STATUSES, ProductSerial, StockMovement

S = ProductSerial.Status
REF = "repair_order_refurb"
CENTS = Decimal("0.01")


class StockRepairError(ValueError):
    """不能這樣做(訊息直接給畫面)。"""


def prepare(order):
    """這張單整理的那一台(帶商品;還沒鎖)。不是自家庫存的單回 None。"""
    if not order.stock_serial_id:
        return None
    serial = (ProductSerial.objects.select_related("product")
              .filter(tenant_id=order.tenant_id, pk=order.stock_serial_id).first())
    if serial is None:
        raise StockRepairError("找不到這張單整理的那一台")
    return serial


def reread(serial):
    """鎖到之後重讀會變的欄位。"""
    serial.refresh_from_db(fields=["status", "warehouse", "purchase_unit_cost"])


def cost_of(order) -> Decimal:
    """完工時加進那一台成本的金額:零件成本 + 委外費用(實際成本;跟維修毛利同一套,工資不算)。"""
    from .services import money_of

    money = money_of(order)
    return (money["parts"] + money["outside"]).quantize(CENTS)


def _record(order, serial, note):
    StockMovement.objects.create(
        tenant_id=order.tenant_id, serial=serial, qty=1, movement_type=StockMovement.MovementType.REFURB,
        ref_doc_type=REF, ref_doc_id=order.pk, note=f"{order.no} {note}"[:200],
    )


def _add_cost(serial, delta):
    """那一台的成本加 delta;商品的平均成本照加權平均一起動(呼叫端已鎖好商品與那一台)。"""
    if not delta:
        return
    serial.purchase_unit_cost = (serial.purchase_unit_cost + delta).quantize(CENTS)
    product = serial.product
    n = ProductSerial.objects.filter(tenant_id=serial.tenant_id, product=product, status__in=COSTED_STATUSES).count()
    if n:
        total = product.weighted_avg_cost * n + delta
        product.weighted_avg_cost = max((total / n).quantize(CENTS), Decimal("0"))
        product.save(update_fields=["weighted_avg_cost"])


def start(order, serial_id, *, own_warehouse_id=None):
    """建單那一刻(呼叫端已在交易內、單已存好):那一台 在庫 → 整理中。own_warehouse_id = 鎖在門市的帳號的門市。"""
    lock_stock_rows(order.tenant, serial_ids=[serial_id])
    serial = ProductSerial.objects.filter(tenant_id=order.tenant_id, pk=serial_id).first()
    if serial is None:
        raise StockRepairError("找不到這一台")
    if own_warehouse_id is not None and serial.warehouse_id != own_warehouse_id:
        raise StockRepairError("這一台不在你的門市")
    if serial.status != S.IN_STOCK or serial.warehouse_id is None:
        raise StockRepairError(f"這一台{serial.get_status_display()},不能送去整理")
    serial.status = S.REFURB
    serial.save(update_fields=["status", "updated_at"])
    _record(order, serial, "送去整理")


def finish(order, serial):
    """完工(呼叫端已鎖好單、商品、那一台,零件也扣好了):成本加進去、回到在庫。回加進去的金額(也記在單上)。"""
    if serial.status != S.REFURB or serial.warehouse_id is None:
        raise StockRepairError(f"這一台現在{serial.get_status_display()},跟維修單對不上,請管理員處理")
    cost = cost_of(order)
    _add_cost(serial, cost)
    serial.status = S.IN_STOCK
    serial.save(update_fields=["status", "purchase_unit_cost", "updated_at"])
    order.stock_cost_added = cost
    _record(order, serial, "整理完成")
    return cost


def undo(order, serial):
    """重開(呼叫端已鎖好):扣回完工時加的成本、回到整理中。"""
    if serial.status != S.IN_STOCK or serial.warehouse_id is None:
        raise StockRepairError(f"這一台已經{serial.get_status_display()},不能重開這張整理單")
    _add_cost(serial, -order.stock_cost_added)
    serial.status = S.REFURB
    serial.save(update_fields=["status", "purchase_unit_cost", "updated_at"])
    order.stock_cost_added = Decimal("0")
    _record(order, serial, "重開,整理成本扣回")


SEARCH_LIMIT = 20


def candidates(tenant, q, *, own_warehouse_id=None, limit=SEARCH_LIMIT):
    """打字找要送去整理的那一台(owner 2026-10-29:「打品名,或是打上序號前幾碼,會自動帶出最接近的手機」)。

    回 [(那一台, 是不是刷到的那一台)],最接近的排前面:碼完全相同 → 碼開頭相同 → 碼裡有這串 → 品名有打的每一段
    (不分大小寫、不看空白,品名短的先)。碼完全相同的不管能不能送都回來(畫面講為什麼不行;對到兩台就都不算刷到);
    其他的只回能送的:在庫、鎖在門市的帳號只看自己門市。什麼都沒打:能送的中古機,最近進來的先。
    """
    from django.db.models import Q, Value
    from django.db.models.functions import Length, Replace, Upper

    from apps.identity.normalize import normalize_serial
    from apps.inventory.identifiers import find_serial_ids
    from apps.inventory.models import ProductSerialIdentifier

    q = (q or "").strip()
    base = ProductSerial.objects.filter(tenant=tenant).select_related("product", "warehouse")
    ok = base.filter(status=S.IN_STOCK, warehouse__isnull=False)
    if own_warehouse_id is not None:
        ok = ok.filter(warehouse_id=own_warehouse_id)
    if not q:
        return [(s, False) for s in ok.filter(product__is_secondhand=True).order_by("-id")[:limit]]

    out = []

    def add(rows, scanned=False):
        rows = list(rows.exclude(pk__in=[s.pk for s, _ in out])[:limit - len(out)])
        out.extend((s, scanned) for s in rows)

    exact = find_serial_ids(tenant, q)
    add(base.filter(pk__in=exact).order_by("id"), scanned=len(exact) == 1)
    nv = normalize_serial(q)
    if len(nv) >= 3:
        codes = ProductSerialIdentifier.objects.filter(tenant=tenant)
        for look in ("startswith", "contains"):
            hit = codes.filter(**{f"normalized_value__{look}": nv}).values("serial_id")
            add(ok.filter(Q(pk__in=hit) | Q(**{f"serial_key__{look}": nv})).order_by("serial_key"))
    words = q.upper().split()
    named = ok.annotate(flat_name=Replace(Upper("product__name"), Value(" "), Value("")))
    for w in words:
        named = named.filter(Q(flat_name__contains=w) | Q(product__sku__iexact=w))
    if len(out) < limit:
        add(named.order_by(Length("product__name"), "product__name", "-id"))
    return out


def release(order, serial):
    """作廢(還沒完工;呼叫端已鎖好):回到在庫,成本不動。"""
    if serial.status != S.REFURB:
        raise StockRepairError(f"這一台現在{serial.get_status_display()},跟維修單對不上,請管理員處理")
    serial.status = S.IN_STOCK
    serial.save(update_fields=["status", "updated_at"])
    _record(order, serial, "取消整理")
