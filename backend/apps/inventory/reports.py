"""庫存三張:進銷存表、異動查詢、序號查詢(owner 2026-10-12:取舊歐睿 MM019 / MM017 / MM020 的優點)。

數字只有一個來源:庫存異動紀錄(`StockMovement`)。每一種異動算哪一類、動到哪家門市、算在哪一欄,
只有 `flows.py` 那一份;這裡只負責把條件變成查詢、把結果排成畫面要的樣子。三張都只讀,不改任何資料。
"""
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta

from django.db import connection, transaction
from django.db.models import BooleanField, Case, Count, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.catalog.models import Product
from apps.identity.normalize import normalize_serial

from . import flows
from .identifiers import codes_of
from .models import ProductSerial, ProductSerialIdentifier, StockBalance, StockMovement, Warehouse

MAX_DAYS = 366          # 期間一次最多看一年
FLOW_MAX_ROWS = 5000    # 進銷存表一次最多列幾個商品
EXPORT_MAX = 20000      # 異動查詢 / 序號查詢匯出一次最多幾列
CODE_SEARCH_MIN = 3     # 用序號找:至少打幾個字才比對登記的碼(跟序號搜尋同一個門檻)

# 帳上還在門市裡的序號狀態(跟每日庫存快照同一組;調撥中的不掛在任何門市)
IN_STORE = (ProductSerial.Status.IN_STOCK, ProductSerial.Status.RETURNED, ProductSerial.Status.RMA)


class ReportError(Exception):
    """條件不對(日期顛倒、期間太長…)。訊息直接給畫面。"""


def parse_day(raw, fallback):
    raw = (raw or "").strip()
    if not raw:
        return fallback
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ReportError("日期格式不對")


def parse_range(params, start_key="from", end_key="to"):
    """起日、迄日(沒給 = 這個月 1 號到今天)。"""
    today = timezone.localdate()
    start = parse_day(params.get(start_key), today.replace(day=1))
    end = parse_day(params.get(end_key), today)
    if start > end:
        raise ReportError("起日不能晚於迄日")
    if (end - start).days >= MAX_DAYS:
        raise ReportError("一次最多看一年")
    return start, end


def optional_range(params, start_key, end_key):
    """可以不填的日期條件(序號查詢的進貨日、賣出日):兩格都沒填 = 不篩。只填一格 = 那一邊不限。"""
    start = parse_day(params.get(start_key), None)
    end = parse_day(params.get(end_key), None)
    if start and end and start > end:
        raise ReportError("起日不能晚於迄日")
    return start, end


def day_start(day):
    """這一天在店裡的時區是從哪一刻開始。"""
    return timezone.make_aware(datetime.combine(day, time.min))


def parse_id(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise ReportError("條件不對")
    return int(raw)


def words(search):
    return [w for w in (search or "").split() if w][:8]


def product_q(tenant, category_id, search, prefix=""):
    """照品類、品號 / 品名(空白隔開的每一段都要有)篩商品。prefix = 從那張表怎麼走到商品。沒有條件 → None。"""
    p = f"{prefix}__" if prefix else ""
    q = None
    if category_id is not None:
        q = Q(**{f"{p}category_id": category_id})
    for w in words(search):
        hit = Q(**{f"{p}sku__icontains": w}) | Q(**{f"{p}name__icontains": w})
        q = hit if q is None else q & hit
    return q


# ─────────────────────────────────────────────────────────
# 進銷存表
# ─────────────────────────────────────────────────────────

@contextmanager
def one_moment():
    """裡面的每一個查詢看到的都是同一個時間點的資料(只讀)。

    進銷存表先讀異動、再讀現在的庫存;中間剛好有人開單的話,那一張單的庫存已經扣了、異動卻沒算到,
    期初就會差那一筆。資料庫的「可重複讀」讓整張表是同一刻的樣子。已經在交易裡(測試)就照原樣。
    """
    if connection.in_atomic_block or connection.vendor != "postgresql":
        yield
        return
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield


def _current_stock(tenant, warehouse_id):
    """現在帳上在門市裡的數量:{商品: 數量},以及其中序號商品「已退」的數量。"""
    serials = ProductSerial.objects.filter(
        tenant=tenant, status__in=IN_STORE, warehouse__isnull=False)
    balances = StockBalance.objects.filter(
        tenant=tenant, qty__gt=0, product__requires_serial=False, product__is_virtual=False)
    if warehouse_id is not None:
        serials = serials.filter(warehouse_id=warehouse_id)
        balances = balances.filter(warehouse_id=warehouse_id)
    stock, returned = defaultdict(int), defaultdict(int)
    for pid, n, back in serials.order_by().values("product_id").annotate(
        n=Count("id"), back=Count("id", filter=Q(status=ProductSerial.Status.RETURNED)),
    ).values_list("product_id", "n", "back"):
        stock[pid] += n
        if back:
            returned[pid] += back
    for pid, qty in balances.order_by().values("product_id").annotate(
        q=Sum("qty")).values_list("product_id", "q"):
        stock[pid] += qty
    return stock, returned


def _current_transit(tenant):
    """現在還在調撥途中的數量:{商品: 數量}(派發了、對方還沒確認;跟每日庫存快照同一個算法)。"""
    from apps.transfers.models import TransferOrder, TransferOrderItem

    transit = defaultdict(int)
    for pid, n in ProductSerial.objects.filter(
        tenant=tenant, status=ProductSerial.Status.IN_TRANSIT,
    ).order_by().values("product_id").annotate(n=Count("id")).values_list("product_id", "n"):
        transit[pid] += n
    for pid, qty in TransferOrderItem.objects.filter(
        tenant=tenant, to__status=TransferOrder.Status.DISPATCHED, to__is_void=False,
        product__requires_serial=False, product__is_virtual=False,
    ).order_by().values("product_id").annotate(q=Sum("qty")).values_list("product_id", "q"):
        transit[pid] += qty
    return transit


def stock_flow(tenant, *, start, end, warehouse_id=None, category_id=None, search="", moved_only=False):
    """一段期間每個商品的 期初、進貨、銷貨、銷退、調入、調出、領用、調整、期末(只有數量)。

    期末從**現在的實際庫存**往回推(迄日之後的異動倒回去),期初 = 期末 − 期間內的增減。
    所以每一列的等式一定成立,而且查到今天的期末 = 現在帳上在門市裡的數量。
    期末含序號商品「已退」的那幾台(東西在門市裡;庫存查詢只算在庫的),每一列另外給其中已退幾台。

    warehouse_id = None 是全公司(各門市加起來)。調撥途中的不在任何一家門市的期末裡,
    所以全公司那一張另外給「在途」(迄日當時還在路上的數量),貨才不會從表上消失(動手前紅隊第 1 條)。
    預設列「期間有進出、或期初 / 期末 / 在途有數量」的商品(紅隊第 3 條:月底拿這張盤點,沒動的也要在);
    moved_only = 只列期間有進出的。
    """
    period_start, period_end = day_start(start), day_start(end + timedelta(days=1))
    moves = StockMovement.objects.filter(tenant=tenant, created_at__gte=period_start)
    if warehouse_id is not None:
        moves = moves.filter(flows.touches_q(warehouse_id))
    grouped = moves.order_by().annotate(
        pid=Coalesce("product_id", "serial__product_id"),
        later=Case(When(created_at__gte=period_end, then=Value(True)),
                   default=Value(False), output_field=BooleanField()),
        one=Case(When(serial__isnull=False, then=Value(True)),
                 default=Value(False), output_field=BooleanField()),
    ).values(
        "pid", "later", "one", "movement_type", "ref_doc_type", "from_warehouse_id", "to_warehouse_id",
    ).annotate(q=Sum("qty")).values_list(
        "pid", "later", "one", "movement_type", "ref_doc_type",
        "from_warehouse_id", "to_warehouse_id", "q",
    )

    company = warehouse_id is None
    flow = defaultdict(lambda: dict.fromkeys(flows.COLUMNS, 0))   # 期間內每一欄
    touched = set()                      # 期間內有進出的商品(賣了又作廢 = 欄上是 0,但它有進出)
    after = defaultdict(int)             # 迄日之後數量的增減(要倒回去)
    returned_after = defaultdict(int)    # 迄日之後「已退」的增減
    transit_after = defaultdict(int)     # 迄日之後「在途」的增減(只有全公司那一張用)
    for pid, later, one, kind, ref, w_from, w_to, qty in grouped:
        if pid is None:
            continue
        if later and company:
            transit_after[pid] += flows.transit_delta(kind, ref, w_from, w_to, qty)
        for wid, column, amount in flows.effects(kind, ref, w_from, w_to, qty):
            if warehouse_id is not None and wid != warehouse_id:
                continue
            if not later:
                flow[pid][column] += amount
                touched.add(pid)
                continue
            after[pid] += amount * flows.SIGN[column]
            # 序號商品被退回來 = 變成「已退」;那張銷退作廢 = 不再是「已退」。其他動作不會碰到已退的那一台
            if one and column == "sale_return":
                returned_after[pid] += amount

    stock, returned = _current_stock(tenant, warehouse_id)
    transit = _current_transit(tenant) if company else {}
    rows = {}
    for pid in set(flow) | set(stock) | set(after) | set(transit) | set(transit_after):
        cols = flow.get(pid) or dict.fromkeys(flows.COLUMNS, 0)
        closing = stock.get(pid, 0) - after.get(pid, 0)
        opening = closing - sum(cols[c] * flows.SIGN[c] for c in flows.COLUMNS)
        on_the_way = transit.get(pid, 0) - transit_after.get(pid, 0)
        moved = pid in touched
        if moved_only and not moved:
            continue
        if not moved and not opening and not closing and not on_the_way:
            continue
        rows[pid] = {
            "opening": opening, **cols, "closing": closing,
            "returned": returned.get(pid, 0) - returned_after.get(pid, 0),
            "transit": on_the_way,
        }

    products = Product.objects.filter(tenant=tenant, pk__in=list(rows))
    wanted = product_q(tenant, category_id, search)
    if wanted is not None:
        products = products.filter(wanted)
    out = []
    for pid, sku, name, category in products.order_by("sku", "id").values_list(
        "id", "sku", "name", "category__name",
    ):
        out.append({"product": pid, "sku": sku, "name": name, "category": category or "", **rows[pid]})

    keys = ("opening", *flows.COLUMNS, "closing", "returned", "transit")
    totals = {k: sum(r[k] for r in out) for k in keys}
    return {
        "from": start.isoformat(), "to": end.isoformat(), "warehouse": warehouse_id,
        "columns": [{"key": c, "label": flows.COLUMN_LABELS[c], "sign": flows.SIGN[c]} for c in flows.COLUMNS],
        "rows": out[:FLOW_MAX_ROWS], "row_count": len(out), "truncated": len(out) > FLOW_MAX_ROWS,
        "totals": totals, "with_transit": company,
    }


# ─────────────────────────────────────────────────────────
# 異動查詢
# ─────────────────────────────────────────────────────────

def serial_code_q(tenant, word, prefix=""):
    """這一段字對得到哪幾台(主碼、或登記的任何一個碼;去掉空白 / 破折號、不分大小寫、打一部分也可以)。"""
    p = f"{prefix}__" if prefix else ""
    q = Q(**{f"{p}serial_no__icontains": word})
    nv = normalize_serial(word)
    if len(nv) >= CODE_SEARCH_MIN:
        q |= Q(**{f"{p}serial_key__contains": nv})
        q |= Q(**{f"{p}pk__in": ProductSerialIdentifier.objects.filter(
            tenant=tenant, normalized_value__contains=nv).order_by().values("serial_id")})
    return q


def movements(tenant, *, start, end, warehouse_id=None, kind="", category_id=None, search="",
              product_id=None):
    """期間內的每一筆庫存異動(新的在前面)。warehouse_id = 只列動到這家門市數量的。

    product_id = 只列這一個商品的(從進銷存表點品名過來:要跟那一列是同一批異動。
    用品號去找是「包含」,`A-000001` 會連 `BA-000001` 一起列出來 —— 複審首輪抓到的)。
    """
    qs = StockMovement.objects.filter(
        tenant=tenant, created_at__gte=day_start(start),
        created_at__lt=day_start(end + timedelta(days=1)),
    )
    if warehouse_id is not None:
        qs = qs.filter(flows.touches_q(warehouse_id))
    if kind:
        if kind not in flows.KIND_LABELS:
            raise ReportError("沒有這個類別")
        qs = qs.filter(flows.kind_q(kind))
    if product_id is not None:
        qs = qs.filter(Q(product_id=product_id) | Q(serial__product_id=product_id))
    if category_id is not None:
        qs = qs.filter(Q(product__category_id=category_id) | Q(serial__product__category_id=category_id))
    for w in words(search):
        qs = qs.filter(
            Q(product__sku__icontains=w) | Q(product__name__icontains=w)
            | Q(serial__product__sku__icontains=w) | Q(serial__product__name__icontains=w)
            | serial_code_q(tenant, w, "serial")
        )
    return qs.select_related(
        "product", "serial__product", "serial__acquired_via_sales_order",
    ).order_by("-created_at", "-id")


# 異動上記的來源單據 → 那張單的資料表與畫面上的種類(畫面照種類決定點了去哪一頁)
def _doc_models():
    from apps.purchasing.models import PurchaseOrder
    from apps.repairs.models import RepairOrder
    from apps.sales.models import SalesOrder, SalesReturn
    from apps.transfers.models import TransferOrder

    return {
        "purchase_order": ("purchase", PurchaseOrder),
        "sales_order": ("sale", SalesOrder),
        "sales_return": ("sale_return", SalesReturn),
        "transfer_order": ("transfer", TransferOrder),
        "repair_order": ("repair", RepairOrder),
        "repair_order_shortage": ("repair", RepairOrder),
        "repair_order_reopen": ("repair", RepairOrder),
    }


# 這幾類的備註有別的地方看不到的內容(補差多少、為什麼跳過);其餘的備註只是把單號再講一次,
# 個人收購的備註還寫了賣家的電話姓名 —— 都不放進清單
_NOTE_KINDS = ("adjust", "usage_back", "transfer_void")


def _doc_of(tenant, moves):
    """每一筆異動是哪一張單:{異動編號: {"kind", "id", "no"}}。

    **照備註裡寫的單號找,不照異動上記的單據編號**:那一欄只是數字、不是外鍵,還原備份之後每張單的編號都換了,
    它不會跟著換(可能指到不存在的單、甚至是另一張單);單號不會變。每一種開單寫異動時備註裡都有單號
    (「銷貨單 SO-000004 第 1 行」「R-0012 維修領用」)。個人收購的備註沒有單號,用那一台設備記的收購單。
    找不到 = 不給連結(不猜)。
    """
    docs = _doc_models()
    tokens = defaultdict(set)
    for m in moves:
        if m.ref_doc_type in docs:
            tokens[docs[m.ref_doc_type][1]].update(m.note.split()[:3])
    found = {
        model: dict(model.objects.filter(tenant=tenant, no__in=[t for t in names if t]).values_list("no", "id"))
        for model, names in tokens.items()
    }
    out = {}
    for m in moves:
        if m.ref_doc_type not in docs:
            continue
        doc_kind, model = docs[m.ref_doc_type]
        no = next((t for t in m.note.split()[:3] if t in found[model]), None)
        if no is not None:
            out[m.id] = {"kind": doc_kind, "id": found[model][no], "no": no}
        elif m.movement_type == StockMovement.MovementType.TRADE_IN and m.serial_id:
            so = m.serial.acquired_via_sales_order
            if so is not None:
                out[m.id] = {"kind": "sale", "id": so.id, "no": so.no}
    return out


def movement_rows(tenant, moves, warehouse_id=None):
    """把一頁異動排成畫面要的樣子(單號一次查齊,不一筆一筆問)。"""
    moves = list(moves)
    doc_of = _doc_of(tenant, moves)
    names = dict(Warehouse.objects.filter(tenant=tenant).values_list("id", "name"))
    out = []
    for m in moves:
        product = m.product or (m.serial.product if m.serial_id else None)
        kind = flows.kind_of(m.movement_type, m.ref_doc_type)
        out.append({
            "id": m.id,
            "created_at": m.created_at,
            "kind": kind,
            "kind_label": flows.KIND_LABELS[kind],
            "product": product.id if product else None,
            "sku": product.sku if product else "",
            "name": product.name if product else "",
            "serial": m.serial_id,
            "serial_no": m.serial.serial_no if m.serial_id else "",
            "qty": m.qty,
            "effects": [
                {"warehouse": wid, "name": names.get(wid, ""), "delta": delta}
                for wid, delta in flows.deltas(m.movement_type, m.from_warehouse_id, m.to_warehouse_id, m.qty)
                if warehouse_id is None or wid == warehouse_id
            ],
            "from_name": names.get(m.from_warehouse_id, ""),
            "to_name": names.get(m.to_warehouse_id, ""),
            "doc": doc_of.get(m.id),
            "note": m.note if kind in _NOTE_KINDS else "",
        })
    return out


# ─────────────────────────────────────────────────────────
# 序號查詢
# ─────────────────────────────────────────────────────────

def _current_sale(tenant, field):
    """把這一台賣出去的那張銷貨單(沒作廢的裡面最新的一張)的某一欄。"""
    from apps.sales.models import SalesOrderItemSerial

    return Subquery(
        SalesOrderItemSerial.objects.filter(
            tenant=tenant, serial=OuterRef("pk"), item__so__is_void=False,
        ).order_by("-id").values(field)[:1]
    )


def serials(tenant, *, statuses=(), warehouse_id=None, supplier_id=None,
            received=(None, None), sold=(None, None), search=""):
    """跨商品的每一台設備(新進的在前面)。

    門市:還在店裡的看它在哪一家;已售出的看是哪一家賣的。賣出日 = 把它賣出去的那張銷貨單的日期。
    """
    S = ProductSerial.Status
    qs = ProductSerial.objects.filter(tenant=tenant).annotate(
        sale_warehouse=_current_sale(tenant, "item__so__warehouse_id"),
        sale_date=_current_sale(tenant, "item__so__doc_date"),
    )
    if statuses:
        bad = [s for s in statuses if s not in S.values]
        if bad:
            raise ReportError("沒有這個狀態")
        qs = qs.filter(status__in=statuses)
    if warehouse_id is not None:
        qs = qs.filter(Q(warehouse_id=warehouse_id) | Q(status=S.SOLD, sale_warehouse=warehouse_id))
    if supplier_id is not None:
        qs = qs.filter(purchase_order_item__po__supplier_id=supplier_id)
    if received[0]:
        qs = qs.filter(received_at__gte=day_start(received[0]))
    if received[1]:
        qs = qs.filter(received_at__lt=day_start(received[1] + timedelta(days=1)))
    if sold[0] or sold[1]:
        qs = qs.filter(status=S.SOLD)
        if sold[0]:
            qs = qs.filter(sale_date__gte=sold[0])
        if sold[1]:
            qs = qs.filter(sale_date__lte=sold[1])
    for w in words(search):
        qs = qs.filter(
            Q(product__sku__icontains=w) | Q(product__name__icontains=w) | serial_code_q(tenant, w)
        )
    return qs.order_by("-received_at", "-id")


def serial_rows(tenant, page):
    """把一頁設備排成畫面要的樣子。來源只寫「個人收購」,不帶賣家的姓名電話(要看點進履歷)。"""
    from apps.sales.models import SalesOrder

    page = list(page)
    S = ProductSerial.Status
    full = {
        s.pk: s for s in ProductSerial.objects.filter(pk__in=[s.pk for s in page]).select_related(
            "product", "warehouse", "purchase_order_item__po__supplier", "acquired_via_sales_order",
        ).prefetch_related("identifiers")
    }
    names = dict(Warehouse.objects.filter(tenant=tenant).values_list("id", "name"))
    # 把它賣出去的那張銷貨單(已售的才有)
    sales = {}
    sold_ids = [s.pk for s in page if s.status == S.SOLD]
    if sold_ids:
        from apps.sales.models import SalesOrderItemSerial

        for serial_id, so_id in SalesOrderItemSerial.objects.filter(
            tenant=tenant, serial_id__in=sold_ids, item__so__is_void=False,
        ).order_by("serial_id", "id").values_list("serial_id", "item__so_id"):
            sales[serial_id] = so_id          # 同一台最後留下的是最新的那一張
    so_info = {
        pk: (no, day, wid) for pk, no, day, wid in SalesOrder.objects.filter(
            tenant=tenant, pk__in=set(sales.values()),
        ).values_list("id", "no", "doc_date", "warehouse_id")
    }
    out = []
    for annotated in page:
        s = full[annotated.pk]
        codes = codes_of(s)
        source = None
        if s.acquired_via_sales_order_id:
            so = s.acquired_via_sales_order
            source = {"kind": "trade_in", "label": "個人收購", "doc": {"kind": "sale", "id": so.id, "no": so.no}}
        elif s.purchase_order_item_id:
            po = s.purchase_order_item.po
            source = {
                "kind": "purchase", "label": po.supplier.name if po.supplier_id else "",
                "doc": {"kind": "purchase", "id": po.id, "no": po.no},
            }
        sale = None
        store = s.warehouse.name if s.warehouse_id else ""
        if s.status == S.SOLD and s.pk in sales and sales[s.pk] in so_info:
            no, day, wid = so_info[sales[s.pk]]
            sale = {"doc": {"kind": "sale", "id": sales[s.pk], "no": no}, "date": day}
            store = names.get(wid, "")
        out.append({
            "id": s.pk,
            "serial_no": s.serial_no,
            "imei": codes["imei"],
            "sn": codes["sn"],
            "product": s.product_id,
            "sku": s.product.sku,
            "name": s.product.name,
            "status": s.status,
            "status_label": s.get_status_display(),
            "store": store,
            "source": source,
            "received_at": s.received_at,
            "cost": str(s.purchase_unit_cost),
            "sale": sale,
        })
    return out
