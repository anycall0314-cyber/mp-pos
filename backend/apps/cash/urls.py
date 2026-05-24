from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CashAdjustmentViewSet,
    PettyExpenseViewSet,
    business_daily_report,
)

router = DefaultRouter()
router.register(r"petty-expenses", PettyExpenseViewSet, basename="petty-expense")
router.register(
    r"cash-adjustments", CashAdjustmentViewSet, basename="cash-adjustment"
)

urlpatterns = router.urls + [
    path(
        "reports/business-daily/",
        business_daily_report,
        name="business-daily-report",
    ),
]
