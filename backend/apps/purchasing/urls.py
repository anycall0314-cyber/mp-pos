from django.urls import path
from rest_framework.routers import DefaultRouter

from .line_report import purchase_line_report
from .sheet_views import secondhand_purchase_sheet
from .views import PurchaseOrderCategoryViewSet, PurchaseOrderViewSet

router = DefaultRouter()
router.register(r"purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register(
    r"purchase-order-categories",
    PurchaseOrderCategoryViewSet,
    basename="purchase-order-category",
)

urlpatterns = router.urls + [
    # 進貨明細(進貨單的每一行一列)
    path("purchase-line-report/", purchase_line_report),
    # 中古機大量進貨的 Excel(範本、讀檔)
    path("secondhand-purchase-sheet/", secondhand_purchase_sheet),
]
