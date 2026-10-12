"""進貨明細:進貨單的每一行一列。只讀。

owner 2026-10-12(取舊歐睿報表的優點,第 2 批;舊 FI010 進退貨商品查詢表):以前只有進貨單清單(一張單一列),
要找「某個商品什麼時候跟誰進的、進價多少」得一張一張點開。

- 不列作廢的進貨單(作廢 = 當作沒進過;跟自訂分析的「進貨金額」同一批明細)。
- 成本 = 記進庫存的未稅成本(單位成本 × 數量,含分攤的運費;贈品會把單位成本拉低)。**合計的成本 = 自訂分析同一段期間的「進貨金額(未稅)」**。
- 單價、金額是單上打的(含稅還是未稅看那張單的課稅別)。
- 看進貨單本來就不另外擋,所以這一張也沒有權限的勾;鎖在門市的帳號只看自己門市(跟進貨單清單一樣)。
"""
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.core.warehouse_scoping import report_warehouse_id
from apps.inventory import reports as stock_reports
from apps.inventory.report_views import listing

from .models import PurchaseOrderItem

LINE_COST = ExpressionWrapper(
    F("unit_landed_cost") * F("qty"), output_field=DecimalField(max_digits=18, decimal_places=2))


def lines(tenant, *, start, end, warehouse_id=None, supplier_id=None, category_id=None, search=""):
    """期間內(看單據日期)沒作廢的進貨單的每一行,新的在前面。"""
    qs = PurchaseOrderItem.objects.filter(
        tenant=tenant, po__is_void=False, po__doc_date__gte=start, po__doc_date__lte=end)
    if warehouse_id is not None:
        qs = qs.filter(po__warehouse_id=warehouse_id)
    if supplier_id is not None:
        qs = qs.filter(po__supplier_id=supplier_id)
    wanted = stock_reports.product_q(tenant, category_id, search, "product")
    if wanted is not None:
        qs = qs.filter(wanted)
    return qs.annotate(line_cost=LINE_COST).select_related(
        "po__supplier", "po__warehouse", "product",
    ).order_by("-po__doc_date", "-po_id", "line_no", "id")


def totals(queryset):
    """照同樣的條件全部加起來(不是只有這一頁)。"""
    got = queryset.order_by().aggregate(qty=Sum("qty"), amount=Sum("amount"), cost=Sum("line_cost"))
    return {"qty": got["qty"] or 0, "amount": str(got["amount"] or 0), "cost": str(got["cost"] or 0)}


def rows(page):
    out = []
    for it in page:
        po = it.po
        out.append({
            "id": it.id,
            "date": po.doc_date,
            "doc": {"kind": "purchase", "id": po.id, "no": po.no},
            "store": po.warehouse.name if po.warehouse_id else "",
            "supplier": po.supplier.name if po.supplier_id else "",
            "product": it.product_id,
            "sku": it.product.sku,
            "name": it.product.name,
            "qty": it.qty,
            # 計價數量比進貨數量少 = 有贈品(沒填 = 全部計價)
            "free_qty": it.qty - it.billed_qty if it.billed_qty is not None else 0,
            "unit_price": str(it.unit_price),
            "amount": str(it.amount),
            "cost": str(it.line_cost),
            "note": po.note,
        })
    return out


@api_view(["GET"])
def purchase_line_report(request):
    """進貨明細。?from= &to= &warehouse= &supplier= &category= &search= &page= &export=1"""
    p = request.query_params
    try:
        start, end = stock_reports.parse_range(p)
        queryset = lines(
            request.tenant, start=start, end=end, warehouse_id=report_warehouse_id(request),
            supplier_id=stock_reports.parse_id(p.get("supplier")),
            category_id=stock_reports.parse_id(p.get("category")), search=p.get("search", ""),
        )
    except stock_reports.ReportError as exc:
        return Response({"detail": str(exc)}, status=400)
    return listing(request, queryset, rows, {
        "from": start.isoformat(), "to": end.isoformat(), "totals": totals(queryset),
    })
