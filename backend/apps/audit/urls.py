from django.urls import path

from apps.audit import views

app_name = "audit"

urlpatterns = [
    path("", views.ConsoleView.as_view(), name="console"),
    path("exportar.csv", views.ExportCsvView.as_view(), name="export_csv"),
    path("<int:pk>/restaurar/", views.RestoreView.as_view(), name="restore"),
    path(
        "linha-do-tempo/<str:entity_type>/<str:entity_id>/",
        views.TimelineView.as_view(),
        name="timeline",
    ),
]
