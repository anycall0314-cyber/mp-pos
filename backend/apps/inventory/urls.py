from django.urls import path
from rest_framework.routers import DefaultRouter

from .label_views import label_data
from .report_views import serial_report, stock_flow_report, stock_movement_report
from .stockcount_views import (
    count_phone,
    stock_count,
    stock_count_action,
    stock_count_found,
    stock_count_phone,
    stock_count_phones,
    stock_count_unknown,
    stock_count_line,
    stock_count_lines,
    stock_count_old_units,
    stock_count_scan,
    stock_count_scans,
    stock_counts,
)
from .vendor_exchange_views import (
    vendor_exchange_cancel,
    vendor_exchange_done,
    vendor_exchange_done_serial,
    vendor_exchanges,
)
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
    # 廠商換貨(規則在 vendor_exchange.py)
    path("vendor-exchanges/", vendor_exchanges),
    path("vendor-exchanges/done-serial/", vendor_exchange_done_serial),
    path("vendor-exchanges/<int:pk>/done/", vendor_exchange_done),
    path("vendor-exchanges/<int:pk>/cancel/", vendor_exchange_cancel),
    # 盤點(規則在 stockcount.py)
    path("stock-counts/", stock_counts),
    path("stock-counts/old-units/", stock_count_old_units),
    path("stock-counts/<int:pk>/", stock_count),
    path("stock-counts/<int:pk>/lines/", stock_count_lines),
    path("stock-counts/<int:pk>/lines/<int:line_id>/", stock_count_line),
    path("stock-counts/<int:pk>/scans/", stock_count_scans),
    path("stock-counts/<int:pk>/scans/<int:scan_id>/", stock_count_scan),
    path("stock-counts/<int:pk>/missing/<int:missing_id>/found/", stock_count_found),
    path("stock-counts/<int:pk>/phones/", stock_count_phones),
    path("stock-counts/<int:pk>/phones/<int:phone_id>/", stock_count_phone),
    path("stock-counts/<int:pk>/unknowns/<int:unknown_id>/", stock_count_unknown),
    path("count-phone/<str:action>/", count_phone),
    path("stock-counts/<int:pk>/<str:action>/", stock_count_action),
]
