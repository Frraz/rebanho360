from django.urls import path

from apps.imports import views

app_name = "imports"

urlpatterns = [
    path("", views.BatchListView.as_view(), name="lista"),
    path("nova/", views.UploadView.as_view(), name="nova"),
    path("<int:pk>/", views.BatchDetailView.as_view(), name="detalhe"),
]
