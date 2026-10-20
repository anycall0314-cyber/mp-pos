from django.urls import path
from rest_framework.routers import DefaultRouter

from .commission_views import commission_lines
from .contract_views import contract_follow_up, contract_list
from .daily_report import sales_daily_report
from .invoice_printer import invoice_printer_test
from .invoice_report import sales_invoice_report, sales_invoice_summary
from .views import LegacyPurchaseViewSet, SalesOrderViewSet, SalesReturnViewSet

router = DefaultRouter()
router.register(r"sales-orders", SalesOrderViewSet, basename="sales-order")
router.register(r"sales-returns", SalesReturnViewSet, basename="sales-return")
router.register(r"legacy-purchases", LegacyPurchaseViewSet, basename="legacy-purchase")

urlpatterns = router.urls + [
    # 門號合約到期的名單與聯絡紀錄
    path("telecom-contracts/", contract_list),
    path("telecom-contracts/<int:pk>/follow-up/", contract_follow_up),
    # 門號佣金明細(一筆門號一列;員工帳號的權限「佣金明細」)
    path("telecom-commissions/", commission_lines),
    # 銷貨日報的資料(期間內全部的銷貨單與銷退;員工帳號的權限「銷貨日報」)
    path("sales-daily-report/", sales_daily_report),
    # 發票明細(有發票號碼的銷貨單一張一列;員工帳號的權限「發票明細」)
    path("sales-invoice-report/", sales_invoice_report),
    # 開立發票彙總表(給會計師;照舊系統的格式;權限跟發票明細同一項)
    path("sales-invoice-summary/", sales_invoice_summary),
    # 發票機(WP-103)測試頁:行號測試與樣張的位元組(畫面直接送進 COM 埠)
    path("invoice-printer/test/", invoice_printer_test),
]
