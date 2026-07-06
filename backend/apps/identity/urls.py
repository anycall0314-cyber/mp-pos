from rest_framework.routers import DefaultRouter

from .views import IntakeBatchViewSet, IntakeItemViewSet, ProductAliasViewSet

router = DefaultRouter()
router.register(r"identity/aliases", ProductAliasViewSet, basename="product-alias")
router.register(r"identity/intakes", IntakeBatchViewSet, basename="intake-batch")
router.register(r"identity/intake-items", IntakeItemViewSet, basename="intake-item")

urlpatterns = router.urls
