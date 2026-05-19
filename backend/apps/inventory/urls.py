from rest_framework.routers import DefaultRouter

from .views import ProductSerialViewSet, StockMovementViewSet, WarehouseViewSet

router = DefaultRouter()
router.register(r"warehouses", WarehouseViewSet, basename="warehouse")
router.register(r"serials", ProductSerialViewSet, basename="serial")
router.register(r"stock-movements", StockMovementViewSet, basename="stock-movement")

urlpatterns = router.urls
