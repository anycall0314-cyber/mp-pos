from rest_framework.routers import DefaultRouter

from .views import LegacyPurchaseViewSet, SalesOrderViewSet, SalesReturnViewSet

router = DefaultRouter()
router.register(r"sales-orders", SalesOrderViewSet, basename="sales-order")
router.register(r"sales-returns", SalesReturnViewSet, basename="sales-return")
router.register(r"legacy-purchases", LegacyPurchaseViewSet, basename="legacy-purchase")

urlpatterns = router.urls
