"""門號佣金明細(員工帳號權限第三批,owner 2026-10-10):一筆門號一列。

GET /telecom-commissions/?from=&to=(必填)&warehouse=(沒鎖門市的才有用)

列的東西跟報表引擎的「門號業務員佣金(扣銷退)」是同一批、同一種算法,所以這一頁的合計 = 業績彙總同一段期間的「門號佣金」:
- 期間內開的單上每一行門號(有方案的那一行;作廢的單不算)→ 一列,佣金是成交當下記在單上的數字。
- 期間內的銷退,退掉的那一行是門號 → 另外一列負的(列在**退的那一天**,不回頭把原本那一列拿掉)。

公司佣金只有管理員的回應裡有。門市範圍跟其他報表一樣(`report_warehouse_id`):銷貨看開單的門市、銷退看退貨單的門市。
"""
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.warehouse_scoping import report_warehouse_id
from apps.tenants import abilities
from apps.tenants.permissions import is_tenant_admin

from .models import SalesOrderItem, SalesReturnItem

MAX_ROWS = 2000
MAX_DAYS = 366
ZERO = Decimal("0")
CENT = Decimal("0.01")


def _day(raw, what):
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        raise ValueError(f"{what}的格式要是 YYYY-MM-DD")


def _money(value, sign=1):
    """跟報表引擎同一種寫法(兩位小數的字串);沒有記的(方案當時沒設定公司佣金)是空的,不是 0。"""
    return None if value is None else str((Decimal(value) * sign).quantize(CENT))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def commission_lines(request):
    abilities.require(request.user, abilities.REPORT_COMMISSION)
    params = request.query_params
    try:
        start, end = _day(params.get("from"), "開始日期"), _day(params.get("to"), "結束日期")
        if end < start:
            raise ValueError("結束日期不能早於開始日期")
        if (end - start).days >= MAX_DAYS:
            raise ValueError("「佣金明細」一次最多看一年")
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    tenant = request.tenant
    wid = report_warehouse_id(request)
    manager = is_tenant_admin(request.user)

    sold = SalesOrderItem.objects.filter(
        tenant=tenant, so__is_void=False, telecom_plan__isnull=False,
        so__doc_date__gte=start, so__doc_date__lte=end)
    back = SalesReturnItem.objects.filter(
        tenant=tenant, sr__is_void=False, original_item__telecom_plan__isnull=False,
        sr__doc_date__gte=start, sr__doc_date__lte=end)
    if wid is not None:
        sold = sold.filter(so__warehouse_id=wid)
        back = back.filter(sr__warehouse_id=wid)

    def line(kind, doc, item, person, sign):
        plan = item.telecom_plan
        row = {
            "kind": kind,                   # sale | return
            "date": doc.doc_date.isoformat(),
            "doc_id": doc.id,
            "doc_no": doc.no,
            "warehouse": doc.warehouse.name if doc.warehouse_id else "",
            "msisdn": item.msisdn,
            "carrier": plan.carrier.name if plan.carrier_id else "",
            "plan": plan.name,
            "sales_person": person.name if person else "",
            "commission": _money(item.commission, sign),
        }
        if manager:
            row["company_commission"] = _money(item.company_commission, sign)
        return row

    rows = [
        line("sale", it.so, it, it.so.sales_person, 1)
        for it in sold.select_related(
            "so", "so__warehouse", "so__sales_person", "telecom_plan", "telecom_plan__carrier",
        ).order_by("so__doc_date", "so__no", "line_no", "pk")[: MAX_ROWS + 1]
    ] + [
        line("return", it.sr, it.original_item, it.sr.original_so.sales_person, -1)
        for it in back.select_related(
            "sr", "sr__warehouse", "sr__original_so__sales_person",
            "original_item__telecom_plan", "original_item__telecom_plan__carrier",
        ).order_by("sr__doc_date", "sr__no", "line_no", "pk")[: MAX_ROWS + 1]
    ]
    rows.sort(key=lambda r: (r["date"], r["kind"] == "return", r["doc_no"]))

    def total(field):
        plus = sold.aggregate(v=Sum(field))["v"] or ZERO
        minus = back.aggregate(v=Sum(f"original_item__{field}"))["v"] or ZERO
        return _money(plus - minus)

    totals = {"commission": total("commission")}
    if manager:
        totals["company_commission"] = total("company_commission")
    return Response({
        "rows": rows[:MAX_ROWS],
        "row_count": len(rows),
        "truncated": len(rows) > MAX_ROWS,
        "totals": totals,
        "manager": manager,
        "applied": {"from": start.isoformat(), "to": end.isoformat(), "warehouse": wid},
    })
