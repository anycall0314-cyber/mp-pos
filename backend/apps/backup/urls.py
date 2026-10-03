from django.urls import path

from . import views

urlpatterns = [
    path("backup/overview/", views.overview),
    path("backup/key/", views.key_create),
    path("backup/key/reveal/", views.key_reveal),
    path("backup/key/acknowledge/", views.key_acknowledge),
    path("backup/key/register/", views.key_register),
    path("backup/jobs/", views.backup_jobs),
    path("backup/jobs/<int:pk>/", views.backup_job_detail),
    path("backup/jobs/<int:pk>/download-ticket/", views.download_ticket),
    path("backup/jobs/<int:pk>/verify-local/", views.verify_local),
    path("backup/download/", views.download),
    path("backup/restores/", views.restores),
    path("backup/restores/<int:pk>/", views.restore_detail),
    path("backup/restores/<int:pk>/confirm/", views.restore_confirm),
    path("backup/restores/<int:pk>/cancel/", views.restore_cancel),
    path("backup/maintenance/release/", views.maintenance_release),
    path("backup/audit/", views.audit_log),
]
