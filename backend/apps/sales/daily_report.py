"""銷貨日報的資料:期間內的銷貨單(每一行)與銷退(每一行,數字是負的)。只讀。

owner 2026-10-12(取舊歐睿報表的優點,第 2 批;舊 SA102 銷退貨明細表):銷貨日報要看得到銷退、可以用品名與會員找。
以前那一頁拿銷貨單清單 `/sales-orders/?page_size=500` 自己加總 —— 伺服器的分頁不認 `page_size`(一頁固定 50 張),
期間內超過 50 張單時只列前 50 張、合計也只算那 50 張,畫面沒有提示。這一支一次給齊,超過上限會明講。

畫面的版面與合計的算法沒有動(`frontend/src/lib/salesDaily.ts`):這裡給的每一張單、每一行的欄位名稱跟銷貨單清單一樣,
銷退的每一行把數量、金額、未稅、成本、業務員成本都給成負的,畫面用同一套算法就得到負的毛利。
"""
from collections import defaultdict

from django.db.models import Q
from django.db.models.functions import Coalesce
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.core import cost_access
from apps.core.warehouse_scoping import report_warehouse_id
from apps.inventory import reports as stock_reports
from apps.tenants import abilities

from .models import (
    SalesOrder,
    SalesOrderItem,
    SalesOrderItemSerial,
    SalesReturn,
    SalesReturnItem,
    SalesReturnItemSerial,
)

MAX_DOCS = 2000     # 一次最多給幾張銷貨單(銷退另外算,同一個上限)


def _line_q(tenant, search, serial_links):
    """商品那一格打的字:同一行的品號 / 品名 / 那一行的任何一台的碼,每一段都要對得上。沒有打字 → None。"""
    q = None
    for w in stock_reports.words(search):
        hit = (
            Q(product__sku__icontains=w) | Q(product__name__icontains=w)
            | Q(pk__in=serial_links.objects.filter(tenant=tenant).filter(
                stock_reports.serial_code_q(tenant, w, "serial")).order_by().values("item_id"))
        )
        q = hit if q is None else q & hit
    return q


def _serials(link_model, tenant, item_ids):
    out = defaultdict(list)
    for item_id, serial_no in link_model.objects.filter(
        tenant=tenant, item_id__in=item_ids,
    ).order_by("id").values_list("item_id", "serial__serial_no"):
        out[item_id].append({"serial_no": serial_no})
    return out


def _item(row, serials, matched, sign=1):
    """一行。sign = -1 是銷退:數量與每一個金額都是負的(單價不變)。"""
    return {
        "id": row["id"],
        "line_no": row["line_no"],
        "product": row["product_id"],
        "product_sku": row["product__sku"],
        "product_name": row["product__name"],
        "product_counts_margin": row["product__counts_margin"],
        # 客人要不要付(手機回補不用付:不算金額,只算毛利)
        "counts_cash": row["counts_cash"],
        "product_warehouse_type": row["product__warehouse_type"],
        "serials": serials.get(row["id"], []),
        "qty": row["qty"] * sign,
        "unit_price": str(row["unit_price"]),
        "amount": str(row["amount"] * sign),
        "untaxed_amount": str(row["untaxed_amount"] * sign),
        "cost_at_post": str(row["cost_at_post"] * sign),
        "staff_cost": str(row["line_staff_cost"] * sign),
        # 打了商品的字時,這一行對不對得上(沒打字 = 都算)
        "matched": matched is None or row["id"] in matched,
    }


_ITEM_FIELDS = (
    "id", "line_no", "product_id", "product__sku", "product__name", "product__counts_margin",
    "product__warehouse_type", "qty", "unit_price", "amount", "untaxed_amount", "cost_at_post",
    "line_staff_cost", "counts_cash",
)


def _sales(tenant, *, start, end, warehouse_id, sales_person_id, customer_id, member_id, search):
    orders = SalesOrder.objects.filter(tenant=tenant, doc_date__gte=start, doc_date__lte=end)
    if warehouse_id is not None:
        orders = orders.filter(warehouse_id=warehouse_id)
    if sales_person_id is not None:
        orders = orders.filter(sales_person_id=sales_person_id)
    if customer_id is not None:
        orders = orders.filter(customer_id=customer_id)
    if member_id is not None:
        orders = orders.filter(member_id=member_id)
    matched = None
    wanted = _line_q(tenant, search, SalesOrderItemSerial)
    if wanted is not None:
        hits = SalesOrderItem.objects.filter(tenant=tenant, so__in=orders.order_by()).filter(wanted)
        matched = set(hits.order_by().values_list("id", flat=True))
        orders = orders.filter(pk__in=hits.order_by().values("so_id"))
    heads = list(orders.order_by("doc_date", "no", "id").values(
        "id", "no", "doc_date", "is_void", "warehouse__code", "warehouse__name",
        "sales_person__name", "source_name", "customer__name", "member__name",
    )[: MAX_DOCS + 1])
    truncated = len(heads) > MAX_DOCS
    heads = heads[:MAX_DOCS]
    ids = [h["id"] for h in heads]
    lines = defaultdict(list)
    rows = list(SalesOrderItem.objects.filter(tenant=tenant, so_id__in=ids).annotate(
        line_staff_cost=Coalesce("staff_cost", "cost_at_post"),
    ).order_by("so_id", "line_no", "id").values("so_id", *_ITEM_FIELDS))
    serials = _serials(SalesOrderItemSerial, tenant, [r["id"] for r in rows])
    for r in rows:
        lines[r["so_id"]].append(_item(r, serials, matched))
    return [{
        "id": h["id"], "no": h["no"], "doc_date": h["doc_date"], "is_void": h["is_void"],
        "warehouse_code": h["warehouse__code"], "warehouse_name": h["warehouse__name"],
        "sales_person_name": h["sales_person__name"],
        # 跟銷貨單清單同一個規則:這張單記的來源名稱,舊單沒有就是客戶
        "customer_name": h["source_name"] or h["customer__name"],
        "member_name": h["member__name"],
        "items": lines[h["id"]],
    } for h in heads], truncated


def _returns(tenant, *, start, end, warehouse_id, sales_person_id, customer_id, member_id, search):
    """期間內(看退的那一天)沒作廢的銷退。門市看退回的門市(一律跟原單同一家),業務員看原銷貨單的。"""
    returns = SalesReturn.objects.filter(
        tenant=tenant, is_void=False, doc_date__gte=start, doc_date__lte=end)
    if warehouse_id is not None:
        returns = returns.filter(warehouse_id=warehouse_id)
    if sales_person_id is not None:
        returns = returns.filter(original_so__sales_person_id=sales_person_id)
    if customer_id is not None:
        returns = returns.filter(customer_id=customer_id)
    if member_id is not None:
        returns = returns.filter(member_id=member_id)
    matched = None
    wanted = _line_q(tenant, search, SalesReturnItemSerial)
    if wanted is not None:
        hits = SalesReturnItem.objects.filter(tenant=tenant, sr__in=returns.order_by()).filter(wanted)
        matched = set(hits.order_by().values_list("id", flat=True))
        returns = returns.filter(pk__in=hits.order_by().values("sr_id"))
    heads = list(returns.order_by("doc_date", "no", "id").values(
        "id", "no", "doc_date", "original_so_id", "original_so__no", "warehouse__code", "warehouse__name",
        "original_so__sales_person__name", "original_so__source_name", "original_so__customer__name",
        "member__name",
    )[: MAX_DOCS + 1])
    truncated = len(heads) > MAX_DOCS
    heads = heads[:MAX_DOCS]
    ids = [h["id"] for h in heads]
    lines = defaultdict(list)
    rows = list(SalesReturnItem.objects.filter(tenant=tenant, sr_id__in=ids).annotate(
        line_staff_cost=Coalesce("staff_cost", "cost_at_post"),
    ).order_by("sr_id", "line_no", "id").values("sr_id", *_ITEM_FIELDS))
    serials = _serials(SalesReturnItemSerial, tenant, [r["id"] for r in rows])
    for r in rows:
        lines[r["sr_id"]].append(_item(r, serials, matched, sign=-1))
    return [{
        "id": h["id"], "no": h["no"], "doc_date": h["doc_date"], "is_void": False,
        "original_so": h["original_so_id"], "original_so_no": h["original_so__no"],
        "warehouse_code": h["warehouse__code"], "warehouse_name": h["warehouse__name"],
        "sales_person_name": h["original_so__sales_person__name"],
        # 跟銷退單清單同一個規則:看原銷貨單記的來源名稱,舊單沒有就是原單的客戶
        "customer_name": h["original_so__source_name"] or h["original_so__customer__name"],
        "member_name": h["member__name"],
        "items": lines[h["id"]],
    } for h in heads], truncated


def daily(tenant, **conditions):
    orders, more_orders = _sales(tenant, **conditions)
    returns, more_returns = _returns(tenant, **conditions)
    return {
        "from": conditions["start"].isoformat(), "to": conditions["end"].isoformat(),
        "warehouse": conditions["warehouse_id"],
        "orders": orders, "returns": returns,
        "searching": bool(stock_reports.words(conditions["search"])),
        "truncated": more_orders or more_returns, "limit": MAX_DOCS,
    }


@api_view(["GET"])
def sales_daily_report(request):
    """銷貨日報。?from= &to= &warehouse= &sales_person= &customer= &member= &search=(品號 / 品名 / 序號)

    要有「銷貨日報」那一項;鎖在門市的帳號只算自己門市(網址帶別家的編號沒有用)。
    """
    abilities.require(request.user, abilities.REPORT_SALES_DAILY)
    p = request.query_params
    try:
        start, end = stock_reports.parse_range(p)
        conditions = {
            "sales_person_id": stock_reports.parse_id(p.get("sales_person")),
            "customer_id": stock_reports.parse_id(p.get("customer")),
            "member_id": stock_reports.parse_id(p.get("member")),
        }
    except stock_reports.ReportError as exc:
        return Response({"detail": str(exc)}, status=400)
    with stock_reports.one_moment():       # 銷貨與銷退要是同一刻的(中間有人開單不會只算到一半)
        data = daily(
            request.tenant, start=start, end=end, warehouse_id=report_warehouse_id(request),
            search=p.get("search", ""), **conditions,
        )
    if not cost_access.sees_actual_cost(request.user):
        # 實際成本只給管理員,其他人看業務員成本與業務員毛利(owner 2026-10-28;規則在 core/cost_access.py)
        for doc in (*data["orders"], *data["returns"]):
            for item in doc["items"]:
                item.pop("cost_at_post", None)
    return Response(data)
