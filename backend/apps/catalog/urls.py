from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, PartTemplateViewSet, ProductViewSet

router = DefaultRouter()
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"products", ProductViewSet, basename="product")
router.register(r"part-templates", PartTemplateViewSet, basename="part-template")

urlpatterns = router.urls
