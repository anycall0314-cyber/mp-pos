from datetime import date as date_cls

from django.db.models import Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from apps.core.warehouse_scoping import WarehouseScopedMixin
from apps.purchasing.models import PurchaseOrder
from apps.sales.models import SalesOrder, SalesOrderPayment
from apps.tenants.models import PaymentMethod

from .models import CashAdjustment, PettyExpense, PhoneBillCollection
from .serializers import (
    CashAdjustmentSerializer,
    PettyExpenseSerializer,
    PhoneBillCollectionSerializer,
)


class PettyExpenseViewSet(WarehouseScopedMixin, viewsets.ModelViewSet):
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


class PhoneBillCollectionViewSet(WarehouseScopedMixin, viewsets.ModelViewSet):
    serializer_class = PhoneBillCollectionSerializer
    search_fields = ["no", "phone_no", "id_no"]
    ordering_fields = ["doc_date", "amount", "created_at"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "warehouse": ["exact"],
        "carrier": ["exact"],
        "member": ["exact"],
        "is_void": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return (
            PhoneBillCollection.objects.for_tenant(self.request.tenant)
            .select_related("warehouse", "carrier", "handled_by", "member")
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


class CashAdjustmentViewSet(WarehouseScopedMixin, viewsets.ModelViewSet):
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
    """算指定門市在某日「之前」的現金累計淨變動。
    用來當營業日報「期初現金」的值(全自動累加,使用者不可改)。
    + 銷貨現金收入   + 代收話費    − 進貨現金付款  − 雜支現金支出  − 銷退現金支出
    + 現金存入       − 現金提取
    """
    from apps.sales.models import SalesReturn

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
    sales_return_out = (
        SalesReturn.objects.for_tenant(tenant)
        .filter(
            warehouse_id=warehouse_id,
            doc_date__lt=before_date,
            is_void=False,
            payment_method__in=cash_codes,
        )
        .aggregate(s=Sum("total"))["s"]
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
    phone_bills_in = (
        PhoneBillCollection.objects.for_tenant(tenant)
        .filter(
            warehouse_id=warehouse_id,
            doc_date__lt=before_date,
            is_void=False,
        )
        .aggregate(s=Sum("amount"))["s"]
        or 0
    )
    return int(
        sales_in
        + phone_bills_in
        - sales_return_out
        - purchases_out
        - expenses_out
        + adj_in
        - adj_out
    )


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
    # 鎖倉帳號:只允許看自己門市的日報
    profile = getattr(request.user, "profile", None)
    if profile and profile.is_warehouse_locked:
        if profile.default_warehouse_id != int(warehouse_id):
            return Response(
                {"detail": "不可查看非自己門市的營業日報"},
                status=status.HTTP_403_FORBIDDEN,
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
    # 非現金 = transfer + non_cash;另外取出 code → name 對照供前端顯示用
    non_cash_methods = list(
        PaymentMethod.objects.for_tenant(tenant)
        .filter(kind__in=["transfer", "non_cash"])
        .values("code", "name", "kind")
    )
    non_cash_codes = [m["code"] for m in non_cash_methods]
    non_cash_name_map = {m["code"]: m["name"] for m in non_cash_methods}

    # 期初現金 = 該倉所有 doc_date < target_date 的 cash 淨變動累計
    opening_cash = _compute_cash_balance_before(
        tenant, wid, target_date, cash_codes
    )

    # 1. 銷貨收入:當日 + 該倉 + 非作廢的銷貨單,
    #    分別計算 cash / non_cash 的金額,組成兩個明細區
    sales_qs = (
        SalesOrder.objects.for_tenant(tenant)
        .filter(
            doc_date=target_date,
            warehouse_id=wid,
            is_void=False,
        )
        .select_related("customer", "sales_person")
        .prefetch_related("payments")
    )
    sales_rows = []
    sales_total = 0
    non_cash_sales_rows = []
    non_cash_sales_total = 0
    for so in sales_qs:
        cash_amount = 0
        non_cash_amount = 0
        non_cash_breakdown = {}
        for p in so.payments.all():
            if p.method in cash_codes:
                cash_amount += int(p.amount)
            elif p.method in non_cash_codes:
                amt = int(p.amount)
                non_cash_amount += amt
                non_cash_breakdown[p.method] = (
                    non_cash_breakdown.get(p.method, 0) + amt
                )

        if cash_amount > 0:
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
            sales_total += cash_amount

        if non_cash_amount > 0:
            non_cash_sales_rows.append(
                {
                    "id": so.id,
                    "no": so.no,
                    "customer_name": so.customer.name if so.customer_id else "",
                    "sales_person_name": (
                        so.sales_person.name if so.sales_person_id else ""
                    ),
                    "total": str(so.total),
                    "non_cash_amount": str(non_cash_amount),
                    "method_breakdown": [
                        {
                            "code": code,
                            "name": non_cash_name_map.get(code, code),
                            "amount": str(amt),
                        }
                        for code, amt in non_cash_breakdown.items()
                    ],
                }
            )
            non_cash_sales_total += non_cash_amount

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

    # 3b. 銷退現金支出:當日 + 該倉 + 非作廢 + 退款方式=現金的銷退單
    from apps.sales.models import SalesReturn

    sales_returns_qs = (
        SalesReturn.objects.for_tenant(tenant)
        .filter(
            doc_date=target_date,
            warehouse_id=wid,
            is_void=False,
            payment_method__in=cash_codes,
        )
        .select_related("original_so", "customer")
    )
    sales_returns_rows = []
    sales_returns_total = 0
    cash_methods_map = {
        m.code: m.name
        for m in PaymentMethod.objects.for_tenant(tenant).filter(kind="cash")
    }
    for sr in sales_returns_qs:
        sales_returns_rows.append(
            {
                "id": sr.id,
                "no": sr.no,
                "original_so_no": sr.original_so.no,
                "customer_name": sr.customer.name if sr.customer_id else "",
                "payment_method_name": cash_methods_map.get(
                    sr.payment_method, sr.payment_method
                ),
                "total": str(sr.total),
            }
        )
        sales_returns_total += int(sr.total)

    # 3c. 代收話費(店家代收電信費,純現金收入)
    phone_bills_qs = (
        PhoneBillCollection.objects.for_tenant(tenant)
        .filter(
            doc_date=target_date,
            warehouse_id=wid,
            is_void=False,
        )
        .select_related("carrier", "handled_by", "member")
    )
    phone_bills_rows = []
    phone_bills_total = 0
    for pb in phone_bills_qs:
        phone_bills_rows.append(
            {
                "id": pb.id,
                "no": pb.no,
                "carrier_name": pb.carrier.name,
                "phone_no": pb.phone_no,
                "handled_by_name": (
                    pb.handled_by.name if pb.handled_by_id else ""
                ),
                "member_name": pb.member.name if pb.member_id else "",
                "amount": str(pb.amount),
            }
        )
        phone_bills_total += int(pb.amount)

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
        + phone_bills_total
        - purchases_total
        - expenses_total
        - sales_returns_total
        + adj_in_total
        - adj_out_total
    )
    return Response(
        {
            "warehouse": wid,
            "date": target_date.isoformat(),
            "opening_cash": opening_cash,
            "sales": {"rows": sales_rows, "total": sales_total},
            "non_cash_sales": {
                "rows": non_cash_sales_rows,
                "total": non_cash_sales_total,
            },
            "sales_returns": {
                "rows": sales_returns_rows,
                "total": sales_returns_total,
            },
            "purchases": {"rows": purchases_rows, "total": purchases_total},
            "expenses": {"rows": expenses_rows, "total": expenses_total},
            "phone_bills": {
                "rows": phone_bills_rows,
                "total": phone_bills_total,
            },
            "adjustments": {
                "rows": adj_rows,
                "in_total": adj_in_total,
                "out_total": adj_out_total,
            },
            "net_change": net,
        }
    )
