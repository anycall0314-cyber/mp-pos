from django.urls import path
from rest_framework.routers import DefaultRouter

from . import platform_views

from .views import (
    BrandViewSet,
    CategoryViewSet,
    ConditionViewSet,
    PartTemplateViewSet,
    PhoneSeriesViewSet,
    ProductTypeViewSet,
    ProductViewSet,
)

router = DefaultRouter()
router.register(r"brands", BrandViewSet, basename="brand")
router.register(r"product-types", ProductTypeViewSet, basename="product-type")
router.register(r"conditions", ConditionViewSet, basename="condition")
router.register(r"phone-series", PhoneSeriesViewSet, basename="phone-series")
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"products", ProductViewSet, basename="product")
router.register(r"part-templates", PartTemplateViewSet, basename="part-template")

urlpatterns = [
    path("platform/device-watch/", platform_views.watch),
    path("platform/device-candidates/<int:pk>/", platform_views.candidate),
    *router.urls,
]
