from django.urls import path

from . import views

urlpatterns = [
    path("photo-drafts/", views.drafts),
    path("photo-drafts/<str:uid>/", views.draft_detail),
    path("photo-drafts/<str:uid>/uploads/", views.draft_upload),
    path("photo-drafts/<str:uid>/<slug:action>/", views.draft_action),
    path("product-photos/", views.product_photos),
    path("photo-file/<str:token>/", views.photo_file),
    path("photo-pair/<slug:action>/", views.phone),
]
