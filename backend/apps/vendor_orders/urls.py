from django.urls import path

from . import views

urlpatterns = [
    path("vendor-links/", views.links),
    path("vendor-links/<int:warehouse_id>/remove-key/", views.remove_key),
    path("vendor-orders/", views.orders),
    path("vendor-orders/catalog/", views.catalog),
    path("vendor-orders/sync/", views.sync),
    path("vendor-orders/adopt/", views.adopt),
    path("vendor-orders/<int:pk>/", views.order_detail),
    path("vendor-orders/<int:pk>/resend/", views.order_resend),
    path("vendor-orders/<int:pk>/receiving/", views.receiving_plan),
    path("vendor-orders/<int:pk>/receive/", views.receive),
    path("vendor-orders/<int:pk>/issue/", views.issue),
]
