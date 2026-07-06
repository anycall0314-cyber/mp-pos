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
    path("api/v1/", include("apps.repairs.urls")),
    path("api/v1/", include("apps.assistant.urls")),
    path("api/v1/", include("apps.signals.urls")),
    path("api/v1/", include("apps.identity.urls")),
]

# dev 模式:由 Django 直接 serve 上傳的原圖(進貨單照片);prod 由前面的靜態服務代理
if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

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
