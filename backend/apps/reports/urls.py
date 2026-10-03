from django.urls import path

from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.IndiceView.as_view(), name="indice"),
    # Atalhos do menu Financeiro: o mesmo relatório, com nome próprio para o
    # menu poder apontar para ele e acender o item certo.
    path(
        "fluxo-de-caixa/",
        views.RelatorioView.as_view(),
        {"slug": "fluxo-de-caixa"},
        name="relatorio_fluxo",
    ),
    path(
        "mapa-financeiro/",
        views.RelatorioView.as_view(),
        {"slug": "mapa-financeiro"},
        name="relatorio_mapa",
    ),
    path("<slug:slug>/", views.RelatorioView.as_view(), name="relatorio"),
]
