from rest_framework.routers import DefaultRouter

from .views import SalesOrderViewSet

router = DefaultRouter()
router.register(r"sales-orders", SalesOrderViewSet, basename="sales-order")

urlpatterns = router.urls
