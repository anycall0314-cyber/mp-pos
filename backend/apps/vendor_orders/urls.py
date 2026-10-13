from django.urls import path

from . import handoff_views, platform_views, views

urlpatterns = [
    # 平台管理員:叫貨類別與廠商名單
    path("platform/vendor-categories/", platform_views.categories),
    path("platform/vendor-categories/<int:pk>/", platform_views.category),
    path("platform/vendors/", platform_views.vendor_list),
    path("platform/vendors/<int:pk>/", platform_views.vendor),
    path("platform/vendors/<int:pk>/items/", platform_views.vendor_items),
    path("platform/vendors/<int:pk>/items/import/", platform_views.vendor_items_import),
    path("platform/vendor-items/<int:pk>/", platform_views.vendor_item),
    path("vendor-links/", views.links),
    path("vendor-links/<int:warehouse_id>/remove-key/", views.remove_key),
    path("vendor-orders/", views.orders),
    path("vendor-orders/catalog/", views.catalog),
    path("vendor-orders/sync/", views.sync),
    path("vendor-orders/adopt/", views.adopt),
    path("vendor-orders/mappings/", views.mappings),
    path("vendor-orders/<int:pk>/", views.order_detail),
    path("vendor-orders/<int:pk>/resend/", views.order_resend),
    path("vendor-orders/<int:pk>/receiving/", views.receiving_plan),
    path("vendor-orders/<int:pk>/receive/", views.receive),
    path("vendor-orders/<int:pk>/issue/", views.issue),
    path("vendor-orders/<int:pk>/sent/", views.order_sent),
    path("vendor-orders/<int:pk>/progress/", views.order_progress),
    path("vendor-orders/<int:pk>/cancel/", views.order_cancel),
    # 送進廠商的下單網站:POS 這一側(要登入)
    path("vendor-orders/<int:pk>/handoff/", views.order_handoff),
    path("vendor-orders/<int:pk>/handoff/resolve/", views.order_handoff_resolve),
    # 小幫手那一側(不用登入、認一次性的代碼;只對廠商網站的來源開跨來源)
    path("site-handoff/<str:code>/", handoff_views.site_handoff),
    path("site-handoff/<str:code>/<str:step>/", handoff_views.site_handoff_step),
]
