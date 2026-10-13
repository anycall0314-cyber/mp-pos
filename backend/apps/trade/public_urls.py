from django.urls import path, re_path

from . import public_views

# 對外(金鑰):/api/trade/v2/capabilities、/products、/orders、/orders/{單號}、/orders/{單號}/cancel、/orders/{單號}/received、/statements
urlpatterns = [
    path("", public_views.entry),
    re_path(r"^(?P<rest>[A-Za-z0-9_/-]{1,120})$", public_views.entry),
]
