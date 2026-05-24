from datetime import date as date_cls

from django.db.models import Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from apps.purchasing.models import PurchaseOrder
from apps.sales.models import SalesOrder, SalesOrderPayment
from apps.tenants.models import PaymentMethod

from .models import CashAdjustment, PettyExpense
from .serializers import CashAdjustmentSerializer, PettyExpenseSerializer


class PettyExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = PettyExpenseSerializer
    search_fields = ["no", "payee", "note"]
    ordering_fields = ["doc_date", "amount", "created_at"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "warehouse": ["exact"],
        "category": ["exact"],
        "payment_method": ["exact"],
        "is_void": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return (
            PettyExpense.objects.for_tenant(self.request.tenant)
            .select_related("warehouse", "payment_method")
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        obj = self.get_object()
        if obj.is_void:
            return Response(
                {"detail": "已作廢"}, status=status.HTTP_400_BAD_REQUEST
            )
        obj.is_void = True
        obj.save(update_fields=["is_void"])
        return Response(self.get_serializer(obj).data)


class CashAdjustmentViewSet(viewsets.ModelViewSet):
    serializer_class = CashAdjustmentSerializer
    search_fields = ["no", "note"]
    ordering_fields = ["doc_date", "amount", "created_at"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "warehouse": ["exact"],
        "direction": ["exact"],
        "reason": ["exact"],
        "is_void": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return (
            CashAdjustment.objects.for_tenant(self.request.tenant)
            .select_related("warehouse")
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        obj = self.get_object()
        if obj.is_void:
            return Response(
                {"detail": "已作廢"}, status=status.HTTP_400_BAD_REQUEST
            )
        obj.is_void = True
        obj.save(update_fields=["is_void"])
        return Response(self.get_serializer(obj).data)


def _compute_cash_balance_before(tenant, warehouse_id, before_date, cash_codes):
    """算指定門市在某日「之前」的 cash 累計淨變動。
    用來當營業日報「期初現金」的值(全自動累加,使用者不可改)。
    + 銷貨 cash 收入  − 進貨 cash 付款  − 雜支 cash 支出
    + 現金存入        − 現金提取
    """
    sales_in = (
        SalesOrderPayment.objects.filter(
            so__tenant=tenant,
            so__warehouse_id=warehouse_id,
            so__doc_date__lt=before_date,
            so__is_void=False,
            method__in=cash_codes,
        ).aggregate(s=Sum("amount"))["s"]
        or 0
    )
    purchases_out = (
        PurchaseOrder.objects.for_tenant(tenant)
        .filter(
            warehouse_id=warehouse_id,
            doc_date__lt=before_date,
            is_void=False,
            payment_method__kind="cash",
        )
        .aggregate(s=Sum("total_cost"))["s"]
        or 0
    )
    expenses_out = (
        PettyExpense.objects.for_tenant(tenant)
        .filter(
            warehouse_id=warehouse_id,
            doc_date__lt=before_date,
            is_void=False,
            payment_method__kind="cash",
        )
        .aggregate(s=Sum("amount"))["s"]
        or 0
    )
    adj_in = (
        CashAdjustment.objects.for_tenant(tenant)
        .filter(
            warehouse_id=warehouse_id,
            doc_date__lt=before_date,
            is_void=False,
            direction="in",
        )
        .aggregate(s=Sum("amount"))["s"]
        or 0
    )
    adj_out = (
        CashAdjustment.objects.for_tenant(tenant)
        .filter(
            warehouse_id=warehouse_id,
            doc_date__lt=before_date,
            is_void=False,
            direction="out",
        )
        .aggregate(s=Sum("amount"))["s"]
        or 0
    )
    return int(sales_in - purchases_out - expenses_out + adj_in - adj_out)


@api_view(["GET"])
def business_daily_report(request):
    """指定門市 + 日期的現金收支日報。

    結餘 = 期初現金(由前端帶) + 銷貨 cash 收入 - 進貨 cash 付款 - 雜支 cash 支出
    本 API 只回三區明細與小計;期初現金與最終結餘由前端組裝顯示。
    """
    tenant = request.tenant
    warehouse_id = request.query_params.get("warehouse")
    date_str = request.query_params.get("date")
    if not warehouse_id or not warehouse_id.isdigit():
        return Response(
            {"detail": "warehouse 為必填"}, status=status.HTTP_400_BAD_REQUEST
        )
    if not date_str:
        return Response(
            {"detail": "date 為必填(YYYY-MM-DD)"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        target_date = date_cls.fromisoformat(date_str)
    except ValueError:
        return Response(
            {"detail": "date 格式錯誤,須 YYYY-MM-DD"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    wid = int(warehouse_id)

    # SalesOrderPayment.method 是 CharField 存 PaymentMethod.code,
    # 不是 FK,所以要先撈出該 tenant 所有 kind=cash 的 code
    cash_codes = list(
        PaymentMethod.objects.for_tenant(tenant)
        .filter(kind="cash")
        .values_list("code", flat=True)
    )

    # 期初現金 = 該倉所有 doc_date < target_date 的 cash 淨變動累計
    opening_cash = _compute_cash_balance_before(
        tenant, wid, target_date, cash_codes
    )

    # 1. 銷貨 cash 收入:當日 + 該倉 + 非作廢的銷貨單,
    #    取每筆裡 method in cash_codes 的金額加總
    sales_qs = (
        SalesOrder.objects.for_tenant(tenant)
        .filter(
            doc_date=target_date,
            warehouse_id=wid,
            is_void=False,
        )
        .select_related("customer", "sales_person")
    )
    sales_rows = []
    sales_total = 0
    for so in sales_qs:
        cash_amount = (
            SalesOrderPayment.objects.filter(
                so=so, method__in=cash_codes
            ).aggregate(s=Sum("amount"))["s"]
            or 0
        )
        if cash_amount <= 0:
            continue
        sales_rows.append(
            {
                "id": so.id,
                "no": so.no,
                "customer_name": so.customer.name if so.customer_id else "",
                "sales_person_name": (
                    so.sales_person.name if so.sales_person_id else ""
                ),
                "total": str(so.total),
                "cash_amount": str(cash_amount),
            }
        )
        sales_total += int(cash_amount)

    # 2. 進貨 cash 付款
    purchases_qs = (
        PurchaseOrder.objects.for_tenant(tenant)
        .filter(
            doc_date=target_date,
            warehouse_id=wid,
            is_void=False,
            payment_method__kind="cash",
        )
        .select_related("supplier", "payment_method")
    )
    purchases_rows = []
    purchases_total = 0
    for po in purchases_qs:
        purchases_rows.append(
            {
                "id": po.id,
                "no": po.no,
                "supplier_name": po.supplier.name if po.supplier_id else "",
                "payment_method_name": po.payment_method.name,
                "total_cost": str(po.total_cost),
            }
        )
        purchases_total += int(po.total_cost)

    # 3. 雜支 cash 支出
    expenses_qs = (
        PettyExpense.objects.for_tenant(tenant)
        .filter(
            doc_date=target_date,
            warehouse_id=wid,
            is_void=False,
            payment_method__kind="cash",
        )
        .select_related("payment_method")
    )
    expenses_rows = []
    expenses_total = 0
    for ex in expenses_qs:
        expenses_rows.append(
            {
                "id": ex.id,
                "no": ex.no,
                "category_label": ex.get_category_display(),
                "payee": ex.payee,
                "note": ex.note,
                "amount": str(ex.amount),
            }
        )
        expenses_total += int(ex.amount)

    # 4. 現金調整(老闆補錢進、領現金出去、盤點校正)
    adjustments_qs = (
        CashAdjustment.objects.for_tenant(tenant)
        .filter(
            doc_date=target_date,
            warehouse_id=wid,
            is_void=False,
        )
    )
    adj_rows = []
    adj_in_total = 0
    adj_out_total = 0
    for adj in adjustments_qs:
        amt = int(adj.amount)
        if adj.direction == "in":
            adj_in_total += amt
        else:
            adj_out_total += amt
        adj_rows.append(
            {
                "id": adj.id,
                "no": adj.no,
                "direction": adj.direction,
                "direction_label": adj.get_direction_display(),
                "reason_label": adj.get_reason_display(),
                "note": adj.note,
                "amount": str(adj.amount),
            }
        )

    net = (
        sales_total
        - purchases_total
        - expenses_total
        + adj_in_total
        - adj_out_total
    )
    return Response(
        {
            "warehouse": wid,
            "date": target_date.isoformat(),
            "opening_cash": opening_cash,
            "sales": {"rows": sales_rows, "total": sales_total},
            "purchases": {"rows": purchases_rows, "total": purchases_total},
            "expenses": {"rows": expenses_rows, "total": expenses_total},
            "adjustments": {
                "rows": adj_rows,
                "in_total": adj_in_total,
                "out_total": adj_out_total,
            },
            "net_change": net,
        }
    )
