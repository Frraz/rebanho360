from django.urls import path

from apps.herd import views

app_name = "herd"

urlpatterns = [
    path("posicao/", views.PositionView.as_view(), name="posicao"),
    path("lancar/", views.MovementCreateView.as_view(), name="lancar_movimento"),
    path("lotes-da-fazenda/", views.lotes_da_fazenda, name="lotes_da_fazenda"),
    path("", views.MovementListView.as_view(), name="movimento_lista"),
    path("<int:pk>/", views.MovementDetailView.as_view(), name="movimento_detalhe"),
    path(
        "<int:pk>/editar/", views.MovementUpdateView.as_view(), name="movimento_editar"
    ),
    path(
        "<int:pk>/excluir/",
        views.MovementDeleteView.as_view(),
        name="movimento_excluir",
    ),
    path(
        "<int:pk>/restaurar/",
        views.MovementRestoreView.as_view(),
        name="movimento_restaurar",
    ),
    path("pesagens/", views.WeighingListView.as_view(), name="pesagem_lista"),
    path("pesagens/nova/", views.WeighingCreateView.as_view(), name="pesagem_nova"),
    path(
        "conciliacao/",
        views.ReconciliationView.as_view(),
        name="conciliacao_transferencias",
    ),
]
