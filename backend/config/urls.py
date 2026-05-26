from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

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
    path("api/v1/", include("apps.cash.urls")),
]

# Prod 模式:非 admin / 非 api 的請求一律交給 React SPA 的 index.html
# (前端用 BrowserRouter,任何路徑都走同一份 HTML,JS 端再 route)
if not settings.DEBUG:
    urlpatterns += [
        re_path(
            r"^(?!api/|admin/|static/|assets/).*$",
            TemplateView.as_view(template_name="index.html"),
            name="spa-catch-all",
        ),
    ]
