from django.urls import path
from rest_framework.routers import DefaultRouter

from .label_views import label_data
from .report_views import serial_report, stock_flow_report, stock_movement_report
from .views import (
    ProductSerialViewSet,
    StockBalanceViewSet,
    StockMovementViewSet,
    WarehouseViewSet,
    clearance_pressure,
    inventory_alerts,
    parts_usage_report,
)

router = DefaultRouter()
router.register(r"warehouses", WarehouseViewSet, basename="warehouse")
router.register(r"serials", ProductSerialViewSet, basename="serial")
router.register(r"stock-balances", StockBalanceViewSet, basename="stock-balance")
router.register(r"stock-movements", StockMovementViewSet, basename="stock-movement")

urlpatterns = router.urls + [
    path("labels/", label_data, name="labels"),
    path("inventory-alerts/", inventory_alerts, name="inventory-alerts"),
    path(
        "clearance-pressure/",
        clearance_pressure,
        name="clearance-pressure",
    ),
    path(
        "parts-usage-report/",
        parts_usage_report,
        name="parts-usage-report",
    ),
    # 庫存三張(進銷存表、異動查詢、序號查詢)
    path("stock-flow-report/", stock_flow_report, name="stock-flow-report"),
    path("stock-movement-report/", stock_movement_report, name="stock-movement-report"),
    path("serial-report/", serial_report, name="serial-report"),
]
