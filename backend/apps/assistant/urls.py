from rest_framework.routers import DefaultRouter

from .views import CommandViewSet

router = DefaultRouter()
router.register(r"assistant/commands", CommandViewSet, basename="assistant-command")

urlpatterns = router.urls
