from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ProductSerialViewSet,
    StockBalanceViewSet,
    StockMovementViewSet,
    WarehouseViewSet,
    inventory_alerts,
)

router = DefaultRouter()
router.register(r"warehouses", WarehouseViewSet, basename="warehouse")
router.register(r"serials", ProductSerialViewSet, basename="serial")
router.register(r"stock-balances", StockBalanceViewSet, basename="stock-balance")
router.register(r"stock-movements", StockMovementViewSet, basename="stock-movement")

urlpatterns = router.urls + [
    path("inventory-alerts/", inventory_alerts, name="inventory-alerts"),
]
