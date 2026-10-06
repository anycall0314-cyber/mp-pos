from django.urls import path
from rest_framework.routers import DefaultRouter

from .contract_views import contract_follow_up, contract_list
from .views import LegacyPurchaseViewSet, SalesOrderViewSet, SalesReturnViewSet

router = DefaultRouter()
router.register(r"sales-orders", SalesOrderViewSet, basename="sales-order")
router.register(r"sales-returns", SalesReturnViewSet, basename="sales-return")
router.register(r"legacy-purchases", LegacyPurchaseViewSet, basename="legacy-purchase")

urlpatterns = router.urls + [
    # 門號合約到期的名單與聯絡紀錄
    path("telecom-contracts/", contract_list),
    path("telecom-contracts/<int:pk>/follow-up/", contract_follow_up),
]
