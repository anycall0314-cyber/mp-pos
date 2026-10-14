from django.urls import path

from . import views

urlpatterns = [
    path("trade/settings/", views.settings_view),
    path("trade/summary/", views.summary),
    path("trade/partners/", views.partner_list),
    path("trade/partners/external/", views.external_create),
    path("trade/partners/<int:pk>/", views.partner_change),
    path("trade/partners/<int:pk>/key/", views.partner_key),
    path("trade/partners/<int:pk>/ledger/", views.partner_ledger),
    path("trade/invites/", views.invite_create),
    path("trade/units/", views.unit_list),
    path("trade/units/models/", views.unit_models),
    path("trade/units/changes/", views.unit_changes),
    path("trade/units/rules/", views.unit_rules),
    path("trade/units/rules/<int:pk>/drop/", views.unit_rule_drop),
    path("trade/units/list/", views.unit_put_on),
    path("trade/units/unlist/", views.unit_take_off),
    path("trade/products/", views.product_list),
    path("trade/orders/", views.order_list),
    path("trade/orders/<int:pk>/", views.order_detail),
    path("trade/orders/<int:pk>/accept/", views.order_accept),
    path("trade/orders/<int:pk>/reject/", views.order_reject),
    path("trade/orders/<int:pk>/drop/", views.order_drop),
    path("trade/orders/<int:pk>/ship/", views.order_ship),
    path("trade/shipments/<int:pk>/void/", views.shipment_void),
    path("trade/scan/", views.scan),
    path("trade/payments/", views.payment_create),
    path("trade/payments/<int:pk>/void/", views.payment_void),
]
