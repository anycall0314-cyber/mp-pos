from django.urls import path

from . import views

urlpatterns = [
    # 會員頁:舊 POS 紀錄
    path("legacy/history/", views.history),
    path("legacy/history/<int:pk>/", views.history_document),
    # 管理員:舊會員對照
    path("legacy/members/", views.legacy_members),
    path("legacy/members/<int:pk>/", views.legacy_member_detail),
    path("legacy/members/<int:pk>/evidence/", views.legacy_member_evidence),
    path("legacy/members/<int:pk>/link/", views.legacy_member_link),
    path("legacy/members/<int:pk>/unlink/", views.legacy_member_unlink),
    path("legacy/members/<int:pk>/create-member/", views.legacy_member_create_member),
    path("legacy/candidates/", views.candidates_for_member),
    # 管理員:待核、店別 / 品號 / 業務員對照、匯入紀錄
    path("legacy/exceptions/", views.exceptions),
    path("legacy/exceptions/<int:pk>/resolve/", views.exception_resolve),
    path("legacy/maps/<str:kind>/", views.maps),
    path("legacy/maps/<str:kind>/<int:pk>/candidates/", views.map_candidates),
    path("legacy/maps/<str:kind>/<int:pk>/confirm/", views.map_confirm),
    path("legacy/maps/<str:kind>/<int:pk>/revoke/", views.map_revoke),
    path("legacy/batches/", views.batches),
]
