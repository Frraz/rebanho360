from django.urls import path

from apps.reproduction import views

app_name = "reproduction"

urlpatterns = [
    path("", views.CicloListView.as_view(), name="lista"),
    path("novo/", views.CicloNovoView.as_view(), name="novo"),
    path("<int:pk>/", views.CicloDetalheView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.CicloEditarView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.CicloExcluirView.as_view(), name="excluir"),
    path("<int:pk>/restaurar/", views.CicloRestaurarView.as_view(), name="restaurar"),
]
