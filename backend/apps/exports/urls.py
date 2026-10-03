from django.urls import path

from apps.exports import views

app_name = "exports"

urlpatterns = [
    path("", views.ListaView.as_view(), name="lista"),
    path("nova/", views.NovaView.as_view(), name="nova"),
    path("<uuid:job_id>/", views.DetalheView.as_view(), name="detalhe"),
    path("<uuid:job_id>/baixar/", views.BaixarView.as_view(), name="baixar"),
    path("<uuid:job_id>/cancelar/", views.CancelarView.as_view(), name="cancelar"),
    path("<uuid:job_id>/repetir/", views.RepetirView.as_view(), name="repetir"),
    path("<uuid:job_id>/apagar/", views.ApagarView.as_view(), name="apagar"),
]
