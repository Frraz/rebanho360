"""Relatórios financeiros: tela, CSV, XLSX e PDF passam pelo mesmo
`montar_relatorio` — e só quem vê o financeiro os abre."""

import pytest
from django.urls import reverse

from apps.finance.tests.conftest import baixa

pytestmark = pytest.mark.django_db

SLUGS = [
    "contas-a-pagar",
    "contas-a-receber",
    "pagamentos-realizados",
    "fluxo-de-caixa",
    "mapa-financeiro",
]


@pytest.mark.parametrize("slug", SLUGS)
def test_financeiro_abre_cada_relatorio_na_tela_e_exporta(
    client, financeiro, titulo, titulo_a_receber, slug
):
    client.force_login(financeiro)
    url = reverse("reports:relatorio", args=[slug])

    assert client.get(url).status_code == 200
    csv = client.get(url, {"formato": "csv"})
    assert csv.status_code == 200 and "Filtros aplicados" in csv.content.decode(
        "utf-8-sig"
    )
    assert client.get(url, {"formato": "xlsx"}).status_code == 200


@pytest.mark.parametrize("slug", SLUGS)
def test_campo_recebe_403_nos_relatorios_financeiros(
    client, campo_baixao, titulo, slug
):
    client.force_login(campo_baixao)

    assert client.get(reverse("reports:relatorio", args=[slug])).status_code == 403


def test_indice_nao_lista_relatorio_financeiro_para_o_campo(
    client, campo_baixao, financeiro
):
    client.force_login(campo_baixao)
    assert (
        "Contas a pagar" not in client.get(reverse("reports:indice")).content.decode()
    )
    client.force_login(financeiro)
    assert (
        "Fluxo de caixa projetado"
        in client.get(reverse("reports:indice")).content.decode()
    )


def test_atalhos_do_menu_apontam_para_os_relatorios(client, financeiro):
    client.force_login(financeiro)

    assert client.get(reverse("reports:relatorio_fluxo")).status_code == 200
    assert client.get(reverse("reports:relatorio_mapa")).status_code == 200
    html = client.get(reverse("finance:contas_a_pagar")).content.decode()
    assert "Fluxo de caixa" in html and "Mapa financeiro" in html


def test_menu_financeiro_nao_aparece_para_o_campo(client, campo_baixao):
    client.force_login(campo_baixao)

    html = client.get("/").content.decode()

    assert "Contas a pagar" not in html


def test_contas_a_pagar_reproduz_os_titulos_em_aberto(titulo, financeiro):
    from apps.reports import services

    relatorio = services.montar_relatorio(
        financeiro, "contas-a-pagar", season=titulo.season, farm=None
    )

    assert relatorio.linhas[0]["titulo"] == titulo.code
    assert relatorio.totais["saldo"] == titulo.amount


def test_pagamentos_realizados_lista_a_baixa_e_ignora_a_desfeita(
    titulo_aprovado, financeiro
):
    import datetime

    from apps.finance import services as fin
    from apps.reports import services

    b1 = baixa(titulo_aprovado, financeiro, valor=100, documento="A")
    b2 = baixa(titulo_aprovado, financeiro, valor=50, documento="B")
    fin.desfazer_baixa(b2, usuario=financeiro, motivo="Erro")

    relatorio = services.montar_relatorio(
        financeiro,
        "pagamentos-realizados",
        season=titulo_aprovado.season,
        farm=None,
        extras={"start": datetime.date(2020, 1, 1), "end": datetime.date(2099, 1, 1)},
    )

    assert [lin["baixa"] for lin in relatorio.linhas] == [b1.code]


def test_pdf_do_fluxo_de_caixa_sai_para_o_financeiro_e_e_recusado_ao_campo(
    client, financeiro, campo_baixao, titulo, settings, tmp_path
):
    from apps.documents.models import DocumentStatus, GeneratedDocument

    settings.MEDIA_ROOT = tmp_path / "media"
    url = reverse("documents:gerar", args=["fluxo-de-caixa"])

    client.force_login(campo_baixao)
    assert client.post(url).status_code == 403
    assert GeneratedDocument.objects.count() == 0

    client.force_login(financeiro)
    assert client.post(url).status_code == 302
    assert GeneratedDocument.objects.get().status == DocumentStatus.PRONTO
