from rest_framework.routers import DefaultRouter

from .views import DemandAlertViewSet

router = DefaultRouter()
router.register(r"signals/demand-alerts", DemandAlertViewSet, basename="demand-alert")

urlpatterns = router.urls
