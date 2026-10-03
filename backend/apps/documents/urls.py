from django.urls import path

from apps.documents import views

app_name = "documents"

urlpatterns = [
    path("", views.DocumentListView.as_view(), name="lista"),
    path("gerar/<slug:slug>/", views.GerarView.as_view(), name="gerar"),
    path("<uuid:document_id>/", views.DocumentDetailView.as_view(), name="detalhe"),
    path("<uuid:document_id>/baixar/", views.DownloadView.as_view(), name="baixar"),
]
