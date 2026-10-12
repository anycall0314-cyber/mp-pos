from django.urls import path
from rest_framework.routers import DefaultRouter

from .report import repair_monthly_report
from .views import RepairItemViewSet, RepairOrderViewSet

router = DefaultRouter()
router.register(r"repair-items", RepairItemViewSet, basename="repair-item")
router.register(r"repair-orders", RepairOrderViewSet, basename="repair-order")

urlpatterns = [
    path("repair-monthly-report/", repair_monthly_report),
    *router.urls,
]
