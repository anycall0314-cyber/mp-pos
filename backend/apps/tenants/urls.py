from rest_framework.routers import DefaultRouter

from .views import (
    InvoiceTrackViewSet,
    InvoiceTypeViewSet,
    PaymentMethodViewSet,
)

router = DefaultRouter()
router.register(r"invoice-types", InvoiceTypeViewSet, basename="invoice-type")
router.register(r"invoice-tracks", InvoiceTrackViewSet, basename="invoice-track")
router.register(r"payment-methods", PaymentMethodViewSet, basename="payment-method")

urlpatterns = router.urls
