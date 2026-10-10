from django.urls import path

from . import views

urlpatterns = [
    path("analytics/catalog/", views.catalog),
    path("analytics/options/", views.options),
    path("analytics/query/", views.query),
    path("analytics/reports/", views.reports),
    path("analytics/reports/<int:pk>/", views.report_detail),
    path("analytics/presets/<slug:key>/", views.preset),
]
