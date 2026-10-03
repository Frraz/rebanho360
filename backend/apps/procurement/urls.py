from django.urls import path

from apps.procurement import views

app_name = "procurement"

urlpatterns = [
    # Compromisso
    path("", views.CompromissoListView.as_view(), name="compromisso_lista"),
    path("novo/", views.CompromissoNovoView.as_view(), name="compromisso_novo"),
    path(
        "<int:pk>/", views.CompromissoDetalheView.as_view(), name="compromisso_detalhe"
    ),
    path(
        "<int:pk>/editar/",
        views.CompromissoEditarView.as_view(),
        name="compromisso_editar",
    ),
    path(
        "<int:pk>/aprovar/",
        views.CompromissoAprovarView.as_view(),
        name="compromisso_aprovar",
    ),
    path(
        "<int:pk>/excluir/",
        views.CompromissoExcluirView.as_view(),
        name="compromisso_excluir",
    ),
    path(
        "<int:pk>/restaurar/",
        views.CompromissoRestaurarView.as_view(),
        name="compromisso_restaurar",
    ),
    path(
        "<int:pk>/contrato/", views.ContratoGerarView.as_view(), name="contrato_gerar"
    ),
    path(
        "<int:pk>/comissao/",
        views.ComissaoDefinirView.as_view(),
        name="comissao_definir",
    ),
    path("<int:pk>/viagens/nova/", views.ViagemNovaView.as_view(), name="viagem_nova"),
    path("<int:pk>/acerto/novo/", views.AcertoNovoView.as_view(), name="acerto_novo"),
    # Item e romaneio
    path("itens/<int:pk>/romaneio/", views.RomaneioView.as_view(), name="romaneio"),
    # Viagem
    path("viagens/<int:pk>/", views.ViagemDetalheView.as_view(), name="viagem_detalhe"),
    path(
        "viagens/<int:pk>/editar/",
        views.ViagemEditarView.as_view(),
        name="viagem_editar",
    ),
    path(
        "viagens/<int:pk>/excluir/",
        views.ViagemExcluirView.as_view(),
        name="viagem_excluir",
    ),
    path(
        "viagens/<int:pk>/restaurar/",
        views.ViagemRestaurarView.as_view(),
        name="viagem_restaurar",
    ),
    path(
        "viagens/<int:pk>/recebimento/novo/",
        views.RecebimentoNovoView.as_view(),
        name="recebimento_novo",
    ),
    # Recebimento
    path(
        "recebimentos/<int:pk>/",
        views.RecebimentoDetalheView.as_view(),
        name="recebimento_detalhe",
    ),
    path(
        "recebimentos/<int:pk>/editar/",
        views.RecebimentoEditarView.as_view(),
        name="recebimento_editar",
    ),
    path(
        "recebimentos/<int:pk>/excluir/",
        views.RecebimentoExcluirView.as_view(),
        name="recebimento_excluir",
    ),
    path(
        "recebimentos/<int:pk>/restaurar/",
        views.RecebimentoRestaurarView.as_view(),
        name="recebimento_restaurar",
    ),
    # Acerto
    path("acertos/", views.AcertoListView.as_view(), name="acerto_lista"),
    path("acertos/<int:pk>/", views.AcertoDetalheView.as_view(), name="acerto_detalhe"),
    path(
        "acertos/<int:pk>/linhas/",
        views.AcertoLinhasView.as_view(),
        name="acerto_linhas",
    ),
    path(
        "acertos/<int:pk>/notas/", views.AcertoNotasView.as_view(), name="acerto_notas"
    ),
    path(
        "acertos/<int:pk>/aprovar/",
        views.AcertoAprovarView.as_view(),
        name="acerto_aprovar",
    ),
    path(
        "acertos/<int:pk>/reabrir/",
        views.AcertoReabrirView.as_view(),
        name="acerto_reabrir",
    ),
    path(
        "acertos/<int:pk>/excluir/",
        views.AcertoExcluirView.as_view(),
        name="acerto_excluir",
    ),
    path(
        "acertos/<int:pk>/restaurar/",
        views.AcertoRestaurarView.as_view(),
        name="acerto_restaurar",
    ),
]
