"""每日自動對帳:帳本自己前後一致嗎。

每一項檢查回傳同一種格式:
    {"key", "label", "level": "error" | "info", "ok", "count", "detail", "samples"}
error = 帳本不一致(要有人看);info = 提醒(例如還有多少舊代號沒對照),不算不一致。
samples 只放單號 / 品號這類代號,不放客人姓名電話。
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.identity.normalize import normalize_serial
from apps.inventory.models import (
    ProductSerial,
    ProductSerialIdentifier,
    StockBalance,
    StockMovement,
)
from apps.sales.models import (
    SalesOrder,
    SalesOrderItem,
    SalesOrderItemSerial,
    SalesOrderPayment,
    SalesReturn,
    SalesReturnItem,
    SalesReturnItemSerial,
)
from apps.sales.services import _calc_tax

from .models import LedgerCheckRun, StockSnapshot, StockSnapshotDay
from .snapshot import current_stock, daily_lock, hold_company

SAMPLES = 10
ZERO = Decimal("0")


def _result(key, label, bad, detail="", level="error", count=None):
    bad = list(bad)
    return {
        "key": key, "label": label, "level": level,
        "ok": not bad if level == "error" else True,
        "count": len(bad) if count is None else count,
        "detail": detail, "samples": [str(b) for b in bad[:SAMPLES]],
    }


def _serial_tail(serial_no):
    """序號 / IMEI 只留末 6 碼(跟畫面「顯示末 N 碼」的慣例一致,對帳紀錄也不存完整值)。"""
    return serial_no if len(serial_no) <= 6 else "…" + serial_no[-6:]


def _line_sums(model, fk, **filters):
    """每張單的明細加總(金額、未稅、稅額),由資料庫依單分組算好。"""
    return {
        hid: (a or ZERO, u or ZERO, t or ZERO)
        for hid, a, u, t in model.objects.filter(**filters).values(fk).annotate(
            a=Sum("amount"), u=Sum("untaxed_amount"), t=Sum("tax_amount")
        ).values_list(fk, "a", "u", "t").iterator(chunk_size=5000)
    }


def check_sales_orders(tenant):
    orders = SalesOrder.objects.filter(tenant=tenant, is_void=False).values_list(
        "id", "no", "tax_method", "subtotal", "tax_amount", "total"
    ).iterator(chunk_size=5000)
    sums = _line_sums(SalesOrderItem, "so_id", so__tenant=tenant, so__is_void=False)
    paid = dict(
        SalesOrderPayment.objects.filter(so__tenant=tenant, so__is_void=False)
        .values_list("so_id").annotate(s=Sum("amount")).values_list("so_id", "s")
    )
    header, lines, payments = [], [], []
    for pk, no, method, subtotal, tax, total in orders:
        amount, untaxed, line_tax = sums.get(pk, (ZERO, ZERO, ZERO))
        if _calc_tax(amount, method) != (subtotal, tax, total):
            header.append(no)
        if (untaxed, line_tax) != (subtotal, tax):
            lines.append(no)
        if (paid.get(pk) or ZERO) != total:
            payments.append(no)
    return [
        _result("sales_header", "銷貨單:明細金額加總 = 單頭", header),
        _result("sales_line_tax", "銷貨單:每行未稅 / 稅額加總 = 單頭", lines),
        _result("sales_payment", "銷貨單:付款加總 = 含稅總額", payments),
    ]


def check_sales_returns(tenant):
    rows = SalesReturn.objects.filter(tenant=tenant, is_void=False).values_list(
        "id", "no", "original_so__tax_method", "subtotal", "tax_amount", "total"
    ).iterator(chunk_size=5000)
    sums = _line_sums(SalesReturnItem, "sr_id", sr__tenant=tenant, sr__is_void=False)
    header, lines = [], []
    for pk, no, method, subtotal, tax, total in rows:
        amount, untaxed, line_tax = sums.get(pk, (ZERO, ZERO, ZERO))
        if _calc_tax(amount, method) != (subtotal, tax, total):
            header.append(no)
        if (untaxed, line_tax) != (subtotal, tax):
            lines.append(no)
    # 同一行分幾次退:退的數量與沖回成本都不能超過原行
    over = []
    for oi_no, line_no, oi_qty, oi_cost, qty, cost in (
        SalesReturnItem.objects.filter(tenant=tenant, sr__is_void=False)
        .values("original_item_id")
        .annotate(qty=Sum("qty"), cost=Sum("cost_at_post"))
        .values_list(
            "original_item__so__no", "original_item__line_no", "original_item__qty",
            "original_item__cost_at_post", "qty", "cost",
        )
    ):
        if qty > oi_qty or abs(cost) > abs(oi_cost):
            over.append(f"{oi_no} 第 {line_no} 行")
    return [
        _result("return_header", "銷退單:明細金額加總 = 單頭", header),
        _result("return_line_tax", "銷退單:每行未稅 / 稅額加總 = 單頭", lines),
        _result("return_over", "銷退:退的數量與沖回成本不超過原銷貨行", over),
    ]


def check_stock_balance(tenant):
    """配件(不逐支記的商品):每個門市的庫存數量 = 異動進出加總。"""
    T = StockMovement.MovementType
    moved = defaultdict(int)
    for product_id, w_in, w_out, qty, kind in StockMovement.objects.filter(
        tenant=tenant, serial__isnull=True, product__isnull=False
    ).values_list("product_id", "to_warehouse_id", "from_warehouse_id", "qty", "movement_type"):
        # 調撥的兩筆都寫了來源與目的(當路線說明):派發只扣來源,確認才加到目的
        if kind == T.TRANSFER_OUT:
            w_in = None
        elif kind == T.TRANSFER_IN:
            w_out = None
        if w_in:
            moved[(product_id, w_in)] += qty
        if w_out:
            moved[(product_id, w_out)] -= qty
    balances = {
        (p, w): (q, sku, wname)
        for p, w, q, sku, wname in StockBalance.objects.filter(
            tenant=tenant, product__requires_serial=False, product__is_virtual=False
        ).values_list("product_id", "warehouse_id", "qty", "product__sku", "warehouse__name")
    }
    bad = []
    for key in set(balances) | set(moved):
        qty, sku, wname = balances.get(key, (0, None, None))
        if qty != moved.get(key, 0):
            bad.append((sku or f"商品#{key[0]}", wname or f"門市#{key[1]}", qty, moved.get(key, 0)))
    bad.sort()
    wrong_kind = sorted(
        f"{sku} @ {w}:{q}"
        for sku, w, q in StockBalance.objects.filter(tenant=tenant, qty__gt=0).filter(
            Q(product__requires_serial=True) | Q(product__is_virtual=True)
        ).values_list("product__sku", "warehouse__name", "qty")
    )
    return [
        _result(
            "stock_balance", "配件庫存:各門市數量 = 進出異動加總",
            [f"{sku} @ {w}:庫存 {q},異動合計 {m}" for sku, w, q, m in bad],
        ),
        _result("stock_balance_kind", "序號 / 虛擬商品沒有配件庫存", wrong_kind),
    ]


def check_serials(tenant):
    """序號:狀態、所在門市、銷貨 / 銷退紀錄彼此一致。"""
    sold = defaultdict(int)       # 有效銷貨次數 − 有效銷退次數
    returned = defaultdict(int)   # 有效銷退次數
    for sid in SalesOrderItemSerial.objects.filter(
        tenant=tenant, item__so__is_void=False
    ).values_list("serial_id", flat=True):
        sold[sid] += 1
    for sid in SalesReturnItemSerial.objects.filter(
        tenant=tenant, item__sr__is_void=False
    ).values_list("serial_id", flat=True):
        sold[sid] -= 1
        returned[sid] += 1
    # 每一台的主碼都要登記在識別碼表:「一個碼只屬於一台」靠那張表把關,沒登記的那一台,
    # 別台就可以再用同一個碼
    registered = set(
        ProductSerialIdentifier.objects.filter(tenant=tenant)
        .values_list("serial_id", "normalized_value").iterator(chunk_size=5000))
    taken_codes = {nv for _, nv in registered}
    place, record, codes = [], [], []
    S = ProductSerial.Status
    for sid, raw_no, sku, status, warehouse_id in ProductSerial.objects.filter(
        tenant=tenant
    ).values_list(
        "id", "serial_no", "product__sku", "status", "warehouse_id"
    ).iterator(chunk_size=5000):
        serial_no = f"{sku} {_serial_tail(raw_no)}"
        key = normalize_serial(raw_no)
        if (sid, key) not in registered:
            # 沒登記多半是因為去掉空白 / 破折號後跟另一台相同:刷這個碼會對到兩台,銷貨會擋下來不讓賣
            codes.append(
                f"{serial_no}:主序號沒有登記"
                + ("(跟另一台設備的碼相同,刷這個碼會對到兩台)" if key in taken_codes else ""))
        if status in (S.IN_STOCK, S.RETURNED) and warehouse_id is None:
            place.append(f"{serial_no}:{S(status).label}卻沒有門市")
        if status in (S.SOLD, S.IN_TRANSIT) and warehouse_id is not None:
            place.append(f"{serial_no}:{S(status).label}卻還掛在門市")
        net = sold.get(sid, 0)
        if net < 0:
            record.append(f"{serial_no}:銷退比銷貨多")
        elif status == S.SOLD and net == 0:
            record.append(f"{serial_no}:已售,但沒有有效的銷貨")
        elif status == S.SOLD and net > 1:
            record.append(f"{serial_no}:同時掛在 {net} 張有效的銷貨")
        elif status in (S.IN_STOCK, S.IN_TRANSIT, S.RETURNED, S.VOID) and net > 0:
            record.append(f"{serial_no}:{S(status).label},但有銷貨沒退")
        elif status == S.RETURNED and not returned.get(sid):
            record.append(f"{serial_no}:已退,但沒有有效的銷退")
    return [
        _result("serial_place", "序號:狀態與所在門市一致", place),
        _result("serial_record", "序號:狀態與銷貨 / 銷退紀錄一致", record),
        _result("serial_codes", "序號:每一台的碼都有登記", codes),
    ]


def check_snapshot_gaps(tenant, now, days=7):
    """最近幾天有沒有漏拍(從第一次拍開始算)。漏拍的那天事後補不回來,只能提醒。"""
    from datetime import timedelta

    today = timezone.localtime(now).date()
    marks = StockSnapshotDay.objects.filter(tenant=tenant)
    taken = set(
        marks.filter(business_date__gte=today - timedelta(days=days))
        .values_list("business_date", flat=True)
    )
    first = marks.order_by("business_date").values_list("business_date", flat=True).first()
    missing = [
        d for d in (today - timedelta(days=i) for i in range(days, 0, -1))
        if first is not None and d >= first and d not in taken
    ]
    return [_result(
        "snapshot_gap", f"最近 {days} 天的庫存快照", [], level="info", count=len(missing),
        detail=("漏拍:" + "、".join(d.isoformat() for d in missing)) if missing else "沒有漏拍",
    )]


def check_snapshot(tenant, now):
    """今天的庫存快照:有沒有拍到;拍完之後沒有異動的話,要跟現在的庫存一模一樣。"""
    day = timezone.localtime(now).date()
    snap = StockSnapshot.objects.filter(tenant=tenant, business_date=day)
    first = StockSnapshotDay.objects.filter(tenant=tenant, business_date=day).values_list(
        "taken_at", flat=True
    ).first()
    if first is None:
        # 每天收店後先拍再對帳;白天手動對帳時還沒拍是正常的,只提醒
        return [_result(
            "snapshot", "今天的庫存快照", [], level="info",
            detail="今天還沒拍" if current_stock(tenant) else "目前沒有庫存",
        )]
    if StockMovement.objects.filter(tenant=tenant, created_at__gt=first).exists():
        return [_result(
            "snapshot", "今天的庫存快照", [], level="info",
            detail="拍完後有異動,未比對",
        )]
    taken = {
        (w, p, s): (q, v)
        for w, p, s, q, v in snap.values_list("warehouse_id", "product_id", "state", "qty", "cost_value")
    }
    now_stock = current_stock(tenant)
    bad = sorted(str(k) for k in set(taken) | set(now_stock) if taken.get(k) != now_stock.get(k))
    return [_result("snapshot", "今天的庫存快照 = 現在的庫存", bad)]


def check_legacy(tenant):
    from apps.legacy.models import (
        LegacyDocument,
        LegacyItem,
        LegacyProductMap,
        LegacySalespersonMap,
        LegacySourceException,
        LegacyStoreMap,
        MapStatus,
    )

    docs = LegacyDocument.objects.filter(tenant=tenant)
    if not docs.exists() and not LegacySourceException.objects.filter(tenant=tenant).exists():
        return []
    bad = []
    for no, kind, report, net, count, s_raw, s_net, n in docs.annotate(
        s_raw=Sum("items__amount_minor"),
        s_net=Sum(F("items__amount_minor") * F("items__net_sign")),
        n=Count("items"),
    ).values_list(
        "document_number_raw", "document_type_raw", "report_amount_minor", "net_amount_minor",
        "item_count", "s_raw", "s_net", "n",
    ).iterator(chunk_size=5000):
        if (report, net, count) != (s_raw or 0, s_net or 0, n):
            bad.append(f"{kind} {no}")
    open_exc = LegacySourceException.objects.filter(
        tenant=tenant, status=LegacySourceException.Status.OPEN
    ).count()

    def unmapped(model):
        return model.objects.filter(tenant=tenant).filter(~Q(status=MapStatus.CONFIRMED)).count()

    items = LegacyItem.objects.filter(tenant=tenant)
    # 匯入時每個品號都會建一列對照(先是「未對照」),所以只要看狀態
    unmapped_net = items.exclude(product_map__status=MapStatus.CONFIRMED).aggregate(
        v=Sum(F("amount_minor") * F("net_sign"))
    )["v"] or 0
    return [
        _result("legacy_docs", "舊 POS:每張單的合計 = 明細加總", bad),
        _result(
            "legacy_open", "舊 POS:待核的來源差異", [], level="info", count=open_exc,
            detail=f"{open_exc:,} 筆待核" if open_exc else "沒有待核",
        ),
        _result(
            "legacy_unmapped", "舊 POS:還沒對照的舊代號", [], level="info",
            count=unmapped(LegacyStoreMap) + unmapped(LegacyProductMap) + unmapped(LegacySalespersonMap),
            detail=(
                f"店別 {unmapped(LegacyStoreMap):,}、品號 {unmapped(LegacyProductMap):,}、"
                f"業務 {unmapped(LegacySalespersonMap):,} 個;未對照品號淨額 "
                f"{round(unmapped_net / 100):,}"
            ),
        ),
    ]


CHECKS = [
    check_sales_orders, check_sales_returns, check_stock_balance, check_serials, check_legacy,
]


def last_restore_at(tenant):
    """這家公司最近一次還原完成的時間(沒有還原過就是 None)。"""
    from django.db.models import Max

    from apps.backup.models import RestoreJob

    return RestoreJob.objects.filter(
        tenant=tenant, status=RestoreJob.Status.DONE
    ).aggregate(m=Max("finished_at"))["m"]


def up_to_date_run(tenant, day):
    """今天那一筆對帳,而且是在最近一次還原之後做的;沒有就是 None(要重做)。"""
    run = LedgerCheckRun.objects.filter(tenant=tenant, business_date=day).order_by("-id").first()
    restored = last_restore_at(tenant)
    if run is None or (restored is not None and run.started_at < restored):
        return None
    return run


def run_checks(tenant, now=None, only_if_needed=False, expect_day=None):
    """跑一次全部檢查並存起來;only_if_needed 而今天已有最新的一筆時回傳 None。
    公司正在還原時丟 CompanyBusy(不留紀錄);指定 expect_day 而已過了那天丟 PastBusinessDay。"""
    from django.db import transaction

    from .snapshot import business_moment

    with transaction.atomic():
        daily_lock(tenant)
        now, day = business_moment(now, expect_day)
        if only_if_needed and up_to_date_run(tenant, day):
            return None
        hold_company(tenant)
        results = []
        for check in CHECKS:
            results.extend(check(tenant))
        results.extend(check_snapshot(tenant, now))
        results.extend(check_snapshot_gaps(tenant, now))
        problems = sum(1 for r in results if not r["ok"])
        return LedgerCheckRun.objects.create(
            tenant=tenant, business_date=timezone.localtime(now).date(), started_at=now,
            finished_at=timezone.now(), ok=problems == 0, problem_count=problems,
            results=results,
        )
