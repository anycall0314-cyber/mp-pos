from rest_framework.routers import DefaultRouter

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

urlpatterns = router.urls
