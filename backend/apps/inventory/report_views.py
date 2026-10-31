"""庫存三張的端點:進銷存表、異動查詢、序號查詢。全部只讀;怎麼算在 `reports.py` 與 `flows.py`。

誰看得到:查庫存本來就不另外擋(沒有權限的勾)。鎖在門市的帳號 —— 進銷存表與異動查詢只算自己門市
(跟報表一樣,由伺服器決定,網址帶別家的編號沒有用);序號查詢跟庫存查詢一樣各門市都看得到。
"""
from django.db.models import Sum
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.core.warehouse_scoping import report_warehouse_id

from . import flows, reports
from .models import ProductSerial


class Paging(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500


def _bad(exc):
    return Response({"detail": str(exc)}, status=400)


def _flag(params, key) -> bool:
    return params.get(key, "").strip().lower() in ("1", "true", "yes")


def listing(request, queryset, to_rows, extra):
    """一頁一頁給;?export=1 = 照同樣的條件一次給全部(匯出用,有上限)。"""
    if _flag(request.query_params, "export"):
        rows = list(queryset[: reports.EXPORT_MAX + 1])
        return Response({
            "count": min(len(rows), reports.EXPORT_MAX),
            "truncated": len(rows) > reports.EXPORT_MAX,
            "results": to_rows(rows[: reports.EXPORT_MAX]),
            **extra,
        })
    paginator = Paging()
    page = paginator.paginate_queryset(queryset, request)
    response = paginator.get_paginated_response(to_rows(page))
    response.data.update(extra)
    return response


@api_view(["GET"])
def stock_flow_report(request):
    """進銷存表。?from= &to= &warehouse= &category= &search= &moved=1(只列期間有進出的)"""
    p = request.query_params
    try:
        start, end = reports.parse_range(p)
        category_id = reports.parse_id(p.get("category"))
    except reports.ReportError as exc:
        return _bad(exc)
    warehouse_id = report_warehouse_id(request)
    with reports.one_moment():       # 異動與現在的庫存要是同一刻的
        return Response(reports.stock_flow(
            request.tenant, start=start, end=end, warehouse_id=warehouse_id,
            category_id=category_id, search=p.get("search", ""), moved_only=_flag(p, "moved"),
        ))


@api_view(["GET"])
def stock_movement_report(request):
    """異動查詢。?from= &to= &warehouse= &kind= &category= &search= &product=(就是這一個商品)&page= &export=1"""
    p = request.query_params
    tenant = request.tenant
    try:
        start, end = reports.parse_range(p)
        warehouse_id = report_warehouse_id(request)
        queryset = reports.movements(
            tenant, start=start, end=end, warehouse_id=warehouse_id,
            kind=p.get("kind", "").strip(), category_id=reports.parse_id(p.get("category")),
            search=p.get("search", ""), product_id=reports.parse_id(p.get("product")),
        )
    except reports.ReportError as exc:
        return _bad(exc)
    return listing(
        request, queryset, lambda rows: reports.movement_rows(tenant, rows, warehouse_id),
        {
            "from": start.isoformat(), "to": end.isoformat(), "warehouse": warehouse_id,
            "kinds": [{"key": k, "label": v} for k, v in flows.KIND_LABELS.items()],
        },
    )


@api_view(["GET"])
def serial_report(request):
    """序號查詢。?status=in_stock,returned &warehouse= &supplier= &received_from= &received_to=
    &sold_from= &sold_to= &search= &page= &export=1"""
    p = request.query_params
    tenant = request.tenant
    try:
        queryset = reports.serials(
            tenant,
            statuses=[s for s in p.get("status", "").split(",") if s.strip()],
            warehouse_id=reports.parse_id(p.get("warehouse")),
            supplier_id=reports.parse_id(p.get("supplier")),
            received=reports.optional_range(p, "received_from", "received_to"),
            sold=reports.optional_range(p, "sold_from", "sold_to"),
            search=p.get("search", ""),
        )
    except reports.ReportError as exc:
        return _bad(exc)
    return listing(
        request, queryset, lambda rows: reports.serial_rows(tenant, rows),
        {
            # 照同樣的條件全部加起來(不是只有這一頁)
            "cost_total": str(queryset.aggregate(s=Sum("unit_cost"))["s"] or 0),
            "statuses": [{"key": k, "label": v} for k, v in ProductSerial.Status.choices],
        },
    )
