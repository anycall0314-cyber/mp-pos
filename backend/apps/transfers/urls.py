from rest_framework.routers import DefaultRouter

from .views import TransferOrderViewSet

router = DefaultRouter()
router.register(r"transfer-orders", TransferOrderViewSet, basename="transfer-order")

urlpatterns = router.urls
