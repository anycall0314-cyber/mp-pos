"""每日庫存快照。

只拍「今天」:過去某一天的庫存事後倒推不準(成本會被之後的進貨改掉),
所以漏拍的那天就是空的,不補。同一天重拍會整天取代(以最後一次為準)。
"""
from collections import defaultdict
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.inventory.models import ProductSerial, StockBalance
from apps.transfers.models import TransferOrder, TransferOrderItem, TransferOrderItemSerial

from .models import StockSnapshot, StockSnapshotDay

CENTS = Decimal("0.01")
SERIAL_STATES = {
    ProductSerial.Status.IN_STOCK: StockSnapshot.State.IN_STOCK,
    ProductSerial.Status.RETURNED: StockSnapshot.State.RETURNED,
    ProductSerial.Status.RMA: StockSnapshot.State.RMA,
    ProductSerial.Status.IN_TRANSIT: StockSnapshot.State.IN_TRANSIT,
}


class CompanyBusy(Exception):
    """公司正在還原或維護,這次不拍 / 不對帳。"""


class PastBusinessDay(Exception):
    """輪到這家公司時已經過了午夜:不把午夜後的庫存記成前一天,那一天就算漏拍。"""


def business_moment(now, day):
    """輪到這家公司(拿到每日鎖)之後才看時間;指定了 day 而日期已經不是那天就停。"""
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    if day is not None and today != day:
        raise PastBusinessDay(f"已經過了午夜,{day} 沒拍到")
    return now, today


def daily_lock(tenant):
    """同一家公司的快照 / 對帳同時只有一個在做(背景程式、手動指令、兩台機器都一樣)。"""
    import hashlib

    if connection.vendor != "postgresql":
        return
    key = int.from_bytes(
        hashlib.sha256(f"mppos-ledger-daily:{tenant.pk}".encode()).digest()[:8], "big", signed=True
    )
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def hold_company(tenant):
    """在目前的交易裡:對公司那一列上共享鎖(還原取代資料時會等這裡做完),並確認沒有在維護。"""
    from apps.backup.jobs import in_maintenance

    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM tenants_tenant WHERE id = %s FOR KEY SHARE", [tenant.pk])
    if in_maintenance(tenant):
        raise CompanyBusy("這家公司正在還原或維護中")


def current_stock(tenant):
    """現在的庫存:{(門市 id 或 None, 商品 id, 狀態): [數量, 成本金額]}。"""
    rows = defaultdict(lambda: [0, Decimal("0")])

    # 調撥中的序號:記在派發中那張調撥單的目的門市
    transit_dest = dict(
        TransferOrderItemSerial.objects.filter(
            tenant=tenant, item__to__status=TransferOrder.Status.DISPATCHED,
            item__to__is_void=False,
        ).values_list("serial_id", "item__to__to_warehouse_id")
    )
    for serial_id, product_id, warehouse_id, status, cost in (
        ProductSerial.objects.filter(tenant=tenant, status__in=list(SERIAL_STATES))
        .values_list("id", "product_id", "warehouse_id", "status", "purchase_unit_cost")
        .iterator(chunk_size=5000)
    ):
        state = SERIAL_STATES[status]
        if state == StockSnapshot.State.IN_TRANSIT:
            warehouse_id = transit_dest.get(serial_id)
        row = rows[(warehouse_id, product_id, state)]
        row[0] += 1
        row[1] += cost or Decimal("0")

    # 只算配件:序號商品 / 虛擬商品不該有庫存餘額,有的話由對帳另外列出,不在這裡重複算
    for product_id, warehouse_id, qty, avg in StockBalance.objects.filter(
        tenant=tenant, qty__gt=0, product__requires_serial=False, product__is_virtual=False,
    ).values_list("product_id", "warehouse_id", "qty", "weighted_avg_cost"):
        row = rows[(warehouse_id, product_id, StockSnapshot.State.IN_STOCK)]
        row[0] += qty
        row[1] += qty * avg

    # 調撥中的配件:派發時已從來源門市扣掉、還沒加到目的門市
    for product_id, warehouse_id, qty, cost in TransferOrderItem.objects.filter(
        tenant=tenant, to__status=TransferOrder.Status.DISPATCHED, to__is_void=False,
        product__requires_serial=False, product__is_virtual=False,
    ).values_list("product_id", "to__to_warehouse_id", "qty", "unit_cost_at_dispatch"):
        row = rows[(warehouse_id, product_id, StockSnapshot.State.IN_TRANSIT)]
        row[0] += qty
        row[1] += qty * cost

    return {k: (q, v.quantize(CENTS)) for k, (q, v) in rows.items() if q > 0}


def take_snapshot(tenant, now=None, only_if_missing=False, expect_day=None):
    """拍今天的快照;回傳拍了幾列(only_if_missing 而今天已拍過時回傳 None)。
    公司正在還原時丟 CompanyBusy;指定 expect_day 而已經過了那天丟 PastBusinessDay。"""
    with transaction.atomic():
        daily_lock(tenant)
        now, day = business_moment(now, expect_day)
        if only_if_missing and StockSnapshotDay.objects.filter(
            tenant=tenant, business_date=day
        ).exists():
            return None
        hold_company(tenant)
        stock = current_stock(tenant)
        StockSnapshot.objects.filter(tenant=tenant, business_date=day).delete()
        StockSnapshot.objects.bulk_create(
            [
                StockSnapshot(
                    tenant=tenant, business_date=day, warehouse_id=w, product_id=p, state=s,
                    qty=qty, cost_value=value, taken_at=now,
                )
                for (w, p, s), (qty, value) in stock.items()
            ],
            batch_size=2000,
        )
        StockSnapshotDay.objects.update_or_create(
            tenant=tenant, business_date=day,
            defaults={"taken_at": now, "row_count": len(stock)},
        )
    return len(stock)


def snapshot_totals(tenant, day):
    return StockSnapshot.objects.filter(tenant=tenant, business_date=day).aggregate(
        qty=Sum("qty"), value=Sum("cost_value")
    )
