from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.tenants.urls")),
    path("api/v1/", include("apps.catalog.urls")),
    path("api/v1/", include("apps.parties.urls")),
    path("api/v1/", include("apps.inventory.urls")),
    path("api/v1/", include("apps.purchasing.urls")),
    path("api/v1/", include("apps.sales.urls")),
    path("api/v1/", include("apps.transfers.urls")),
]
