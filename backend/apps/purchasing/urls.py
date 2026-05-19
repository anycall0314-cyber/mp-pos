from rest_framework.routers import DefaultRouter

from .views import PurchaseOrderCategoryViewSet, PurchaseOrderViewSet

router = DefaultRouter()
router.register(r"purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register(
    r"purchase-order-categories",
    PurchaseOrderCategoryViewSet,
    basename="purchase-order-category",
)

urlpatterns = router.urls
