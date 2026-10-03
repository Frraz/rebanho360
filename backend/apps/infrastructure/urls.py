from django.urls import path

from apps.infrastructure import views

app_name = "infrastructure"

urlpatterns = [
    path("", views.EstruturaListView.as_view(), name="estrutura_lista"),
    path("nova/", views.EstruturaNovaView.as_view(), name="estrutura_nova"),
    path(
        "<int:pk>/editar/", views.EstruturaEditarView.as_view(), name="estrutura_editar"
    ),
    path("maquinas/", views.MaquinaListView.as_view(), name="maquina_lista"),
    path("maquinas/nova/", views.MaquinaNovaView.as_view(), name="maquina_nova"),
    path(
        "maquinas/<int:pk>/", views.MaquinaDetalheView.as_view(), name="maquina_detalhe"
    ),
    path(
        "maquinas/<int:pk>/editar/",
        views.MaquinaEditarView.as_view(),
        name="maquina_editar",
    ),
    path("maquinas/<int:pk>/uso/novo/", views.UsoNovoView.as_view(), name="uso_novo"),
    path("usos/<int:pk>/editar/", views.UsoEditarView.as_view(), name="uso_editar"),
    path("usos/<int:pk>/excluir/", views.UsoExcluirView.as_view(), name="uso_excluir"),
    path(
        "usos/<int:pk>/restaurar/",
        views.UsoRestaurarView.as_view(),
        name="uso_restaurar",
    ),
]
