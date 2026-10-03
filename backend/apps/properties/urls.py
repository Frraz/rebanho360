from django.urls import path

from apps.properties import views

app_name = "properties"

urlpatterns = [
    path("fazendas/", views.FarmListView.as_view(), name="fazenda_lista"),
    path("fazendas/nova/", views.FarmCreateView.as_view(), name="fazenda_nova"),
    path(
        "fazendas/<int:pk>/editar/",
        views.FarmUpdateView.as_view(),
        name="fazenda_editar",
    ),
    path("pastos/", views.PaddockListView.as_view(), name="pasto_lista"),
    path("pastos/novo/", views.PaddockCreateView.as_view(), name="pasto_novo"),
    path(
        "pastos/<int:pk>/editar/",
        views.PaddockUpdateView.as_view(),
        name="pasto_editar",
    ),
    path(
        "contexto/trocar-fazenda/",
        views.TrocarFazendaView.as_view(),
        name="trocar_fazenda",
    ),
]
