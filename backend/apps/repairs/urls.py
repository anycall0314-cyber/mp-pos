from rest_framework.routers import DefaultRouter

from .views import RepairItemViewSet, RepairOrderViewSet

router = DefaultRouter()
router.register(r"repair-items", RepairItemViewSet, basename="repair-item")
router.register(r"repair-orders", RepairOrderViewSet, basename="repair-order")

urlpatterns = router.urls
