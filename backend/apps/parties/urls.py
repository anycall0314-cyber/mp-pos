from rest_framework.routers import DefaultRouter

from .views import (
    CarrierViewSet,
    CustomerViewSet,
    SalesPersonViewSet,
    SimCardViewSet,
    SupplierViewSet,
    TelecomPlanViewSet,
)

router = DefaultRouter()
router.register(r"suppliers", SupplierViewSet, basename="supplier")
router.register(r"customers", CustomerViewSet, basename="customer")
router.register(r"sales-persons", SalesPersonViewSet, basename="sales-person")
router.register(r"carriers", CarrierViewSet, basename="carrier")
router.register(r"telecom-plans", TelecomPlanViewSet, basename="telecom-plan")
router.register(r"sim-cards", SimCardViewSet, basename="sim-card")

urlpatterns = router.urls
