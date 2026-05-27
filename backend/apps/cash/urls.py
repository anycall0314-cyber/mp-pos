from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CashAdjustmentViewSet,
    PettyExpenseViewSet,
    PhoneBillCollectionViewSet,
    business_daily_report,
    home_summary,
)

router = DefaultRouter()
router.register(r"petty-expenses", PettyExpenseViewSet, basename="petty-expense")
router.register(
    r"cash-adjustments", CashAdjustmentViewSet, basename="cash-adjustment"
)
router.register(r"phone-bills", PhoneBillCollectionViewSet, basename="phone-bill")

urlpatterns = router.urls + [
    path(
        "reports/business-daily/",
        business_daily_report,
        name="business-daily-report",
    ),
    path(
        "home-summary/",
        home_summary,
        name="home-summary",
    ),
]
