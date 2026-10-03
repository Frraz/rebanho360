from django.urls import path

from apps.finance import views

app_name = "finance"

urlpatterns = [
    path("", views.ContasView.as_view(), name="contas_a_pagar"),
    path("a-receber/", views.ContasAReceberView.as_view(), name="contas_a_receber"),
    path("titulos/novo/", views.TituloCreateView.as_view(), name="titulo_novo"),
    path("titulos/<int:pk>/", views.TituloDetailView.as_view(), name="titulo_detalhe"),
    path(
        "titulos/<int:pk>/editar/",
        views.TituloUpdateView.as_view(),
        name="titulo_editar",
    ),
    path(
        "titulos/<int:pk>/cancelar/",
        views.TituloDeleteView.as_view(),
        name="titulo_excluir",
    ),
    path(
        "titulos/<int:pk>/restaurar/",
        views.TituloRestoreView.as_view(),
        name="titulo_restaurar",
    ),
    path(
        "titulos/<int:pk>/programar/",
        views.TituloProgramarView.as_view(),
        name="titulo_programar",
    ),
    path(
        "titulos/<int:pk>/aprovar/",
        views.TituloAprovarView.as_view(),
        name="titulo_aprovar",
    ),
    path(
        "titulos/<int:pk>/devolver/",
        views.TituloDevolverView.as_view(),
        name="titulo_devolver",
    ),
    path(
        "titulos/<int:pk>/baixar/",
        views.TituloBaixarView.as_view(),
        name="titulo_baixar",
    ),
    path("pagamentos/", views.PagamentoListView.as_view(), name="pagamento_lista"),
    path(
        "pagamentos/<int:pk>/",
        views.PagamentoDetailView.as_view(),
        name="pagamento_detalhe",
    ),
    path(
        "pagamentos/<int:pk>/desfazer/",
        views.PagamentoDesfazerView.as_view(),
        name="pagamento_desfazer",
    ),
    path(
        "pagamentos/<int:pk>/restaurar/",
        views.PagamentoRestoreView.as_view(),
        name="pagamento_restaurar",
    ),
    path("sem-titulo/", views.SemTituloView.as_view(), name="sem_titulo"),
    path(
        "contas-do-favorecido/",
        views.ContasDoFavorecidoView.as_view(),
        name="contas_do_favorecido",
    ),
]
