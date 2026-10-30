"""今日總覽的「到貨」(owner 2026-10-30:「看到今天入庫的新品,讓進貨資訊與門市人員沒有時差」
「新品是一個,還有原本零庫存進貨的也要」)。

今天進貨單進來的商品(作廢的進貨單不算;零件倉的零件、虛擬商品不列),只列兩種:
- 新品:以前從來沒有進出過的商品(今天以前沒有任何一筆庫存異動)。
- 缺貨補進:今天某一張進貨單進來的那一刻,這個範圍裡原本一個都沒有。一般補貨(原本就有)不列。

範圍跟首頁其他區一樣:一家門市 = 那一家的數量;全公司 = 各門市加起來(調撥途中的不在任何一家)。
「原本有幾個」跟進銷存表同一套(`reports.stock_flow`):從現在在門市裡的數量(`reports.IN_STORE`,含已退、
換貨中、整理中)把那張進貨單之後的異動倒回去,方向照 `flows.deltas`。
"""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Exists, Max, Min, OuterRef, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.catalog.models import Product
from apps.purchasing.models import PurchaseOrder

from . import flows
from .models import ProductSerial, StockBalance, StockMovement, Warehouse
from .reports import IN_STORE, day_start, one_moment

LIMIT = 50      # 一組最多列幾個(數字照實際的)


def _in_store_now(tenant, warehouse_id, pids):
    """現在在門市裡的數量:{商品: 數量}(warehouse_id = None 是各門市加起來)。"""
    serials = ProductSerial.objects.filter(tenant=tenant, product_id__in=pids, status__in=IN_STORE,
                                           warehouse__isnull=False)
    balances = StockBalance.objects.filter(tenant=tenant, product_id__in=pids, product__requires_serial=False)
    if warehouse_id is not None:
        serials = serials.filter(warehouse_id=warehouse_id)
        balances = balances.filter(warehouse_id=warehouse_id)
    stock = defaultdict(int)
    for pid, n in serials.order_by().values("product_id").annotate(n=Count("id")).values_list("product_id", "n"):
        stock[pid] += n
    for pid, q in balances.order_by().values("product_id").annotate(q=Sum("qty")).values_list("product_id", "q"):
        stock[pid] += q or 0
    return stock


def today_arrivals(tenant, warehouse_id=None, day=None):
    """{"new": {"count", "items"}, "restock": {"count", "items"}};items 最近進來的在前。"""
    day = day or timezone.localdate()
    start, end = day_start(day), day_start(day + timedelta(days=1))
    with one_moment():
        bought = StockMovement.objects.filter(
            tenant=tenant, movement_type=StockMovement.MovementType.PURCHASE_IN,
            created_at__gte=start, created_at__lt=end, ref_doc_type="purchase_order",
            ref_doc_id__in=PurchaseOrder.objects.filter(tenant=tenant, is_void=False).values("id"),
        )
        if warehouse_id is not None:
            bought = bought.filter(to_warehouse_id=warehouse_id)
        batches = list(
            bought.annotate(pid=Coalesce("product_id", "serial__product_id")).order_by()
            .values("pid", "ref_doc_id", "to_warehouse_id")
            .annotate(first=Min("id"), last_at=Max("created_at"), q=Sum("qty"))
            .values_list("pid", "first", "to_warehouse_id", "last_at", "q")
        )
        products = {
            p.id: p for p in Product.objects.filter(tenant=tenant, pk__in={b[0] for b in batches}, is_virtual=False)
            .exclude(warehouse_type=Product.WarehouseType.PARTS)
        }
        batches = [b for b in batches if b[0] in products]
        if not batches:
            return {"new": {"count": 0, "items": []}, "restock": {"count": 0, "items": []}}
        pids = list(products)

        # 新品:這個商品今天以前沒有任何異動(配件記在商品上、手機記在每一台上;找到一筆就停,首頁每 30 秒抓一次)
        before = StockMovement.objects.filter(tenant=tenant, created_at__lt=start)
        fresh = set(pids) - set(
            Product.objects.filter(pk__in=pids).filter(
                Exists(before.filter(product_id=OuterRef("pk"))) | Exists(before.filter(serial__product_id=OuterRef("pk")))
            ).values_list("id", flat=True)
        )

        # 缺貨補進:每張進貨單進來之前,這個範圍裡有幾個 = 現在的 − 那一刻(含)之後的增減
        since = min(b[1] for b in batches)
        later = defaultdict(list)       # 商品 → [(異動編號, 這個範圍的增減)]
        for pid, mid, kind, w_from, w_to, qty in (
            StockMovement.objects.filter(tenant=tenant, id__gte=since)
            .annotate(pid=Coalesce("product_id", "serial__product_id")).filter(pid__in=pids)
            .values_list("pid", "id", "movement_type", "from_warehouse_id", "to_warehouse_id", "qty")
        ):
            change = sum(d for wid, d in flows.deltas(kind, w_from, w_to, qty)
                         if warehouse_id is None or wid == warehouse_id)
            if change:
                later[pid].append((mid, change))
        now = _in_store_now(tenant, warehouse_id, pids)
        empty_before = {
            pid for pid, first, *_ in batches
            if now.get(pid, 0) - sum(c for mid, c in later[pid] if mid >= first) <= 0
        }

        rows = {}
        for pid, _first, wid, last_at, qty in batches:
            row = rows.setdefault(pid, {"qty": 0, "at": last_at, "warehouses": set()})
            row["qty"] += qty
            row["at"] = max(row["at"], last_at)
            row["warehouses"].add(wid)
        names = dict(Warehouse.objects.filter(tenant=tenant, pk__in={w for r in rows.values() for w in r["warehouses"]})
                     .values_list("id", "name"))

    def item(pid):
        p, r = products[pid], rows[pid]
        return {
            "id": pid, "sku": p.sku, "name": p.name, "qty": r["qty"],
            "at": timezone.localtime(r["at"]).isoformat(),
            "warehouses": sorted(names.get(w, "") for w in r["warehouses"]),
        }

    def group(ids):
        ids = sorted(ids, key=lambda pid: (rows[pid]["at"], pid), reverse=True)
        return {"count": len(ids), "items": [item(pid) for pid in ids[:LIMIT]]}

    return {"new": group(fresh), "restock": group(empty_before - fresh)}
