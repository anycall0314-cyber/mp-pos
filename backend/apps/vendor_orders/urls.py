from django.urls import path

from . import platform_views, views

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
]
