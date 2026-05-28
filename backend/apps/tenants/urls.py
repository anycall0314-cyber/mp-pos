from django.urls import path
from rest_framework.routers import DefaultRouter

from .auth_views import login, logout, me
from .platform_views import (
    PlatformTenantViewSet,
    PlatformUserViewSet,
    PlatformWarehouseViewSet,
)
from .views import (
    InvoiceTrackViewSet,
    InvoiceTypeViewSet,
    PaymentMethodViewSet,
    tenant_settings,
)

router = DefaultRouter()
router.register(r"invoice-types", InvoiceTypeViewSet, basename="invoice-type")
router.register(r"invoice-tracks", InvoiceTrackViewSet, basename="invoice-track")
router.register(r"payment-methods", PaymentMethodViewSet, basename="payment-method")
router.register(
    r"platform/tenants", PlatformTenantViewSet, basename="platform-tenant"
)
router.register(
    r"platform/users", PlatformUserViewSet, basename="platform-user"
)
router.register(
    r"platform/warehouses",
    PlatformWarehouseViewSet,
    basename="platform-warehouse",
)

urlpatterns = router.urls + [
    path("auth/login/", login, name="auth-login"),
    path("auth/me/", me, name="auth-me"),
    path("auth/logout/", logout, name="auth-logout"),
    path("tenant-settings/", tenant_settings, name="tenant-settings"),
]
