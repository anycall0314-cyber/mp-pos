from rest_framework.routers import DefaultRouter

from .views import PettyExpenseViewSet

router = DefaultRouter()
router.register(r"petty-expenses", PettyExpenseViewSet, basename="petty-expense")

urlpatterns = router.urls
