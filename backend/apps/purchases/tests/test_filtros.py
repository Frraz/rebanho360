"""Filtros da listagem de compras: nº de registro, vendedor, destino e datas."""

import datetime

import pytest
from django.urls import reverse

from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice
from apps.purchases import selectors

pytestmark = pytest.mark.django_db


@pytest.fixture
def compras(criar, dados_compra, baixao):
    outro = Partner.objects.create(name="Agro Cerrado do Norte")
    PartnerRole.objects.create(partner=outro, role=PartnerRoleChoice.FORNECEDOR)
    a = criar(**dados_compra)  # São Francisco, 18/09/2025, Fazenda Boa Vista
    b = criar(
        **{
            **dados_compra,
            "seller": outro,
            "destination_farm": baixao,
            "date": datetime.date(2025, 10, 20),
        }
    )
    return a, b


def _codigos(resposta):
    return {c.code for c in resposta.context["compras"]}


def test_filtra_por_pedaco_do_numero_de_registro(client, escritorio, compras):
    a, b = compras
    client.force_login(escritorio)
    url = reverse("purchases:lista")
    assert _codigos(client.get(url, {"registro": a.code[-4:]})) == {a.code}
    assert _codigos(client.get(url, {"registro": "CP-"})) == {a.code, b.code}
    assert _codigos(client.get(url, {"registro": "nada"})) == set()


def test_filtra_por_vendedor(client, escritorio, compras):
    a, b = compras
    client.force_login(escritorio)
    resposta = client.get(reverse("purchases:lista"), {"vendedor": b.seller_id})
    assert _codigos(resposta) == {b.code}


def test_filtra_por_destino_mesmo_com_a_fazenda_do_topo_em_todas(
    client, escritorio, compras, baixao
):
    _, b = compras
    client.force_login(escritorio)
    resposta = client.get(reverse("purchases:lista"), {"destino": baixao.pk})
    assert _codigos(resposta) == {b.code}


def test_filtra_por_periodo_inclusive_nas_pontas(client, escritorio, compras):
    a, b = compras
    client.force_login(escritorio)
    url = reverse("purchases:lista")
    assert _codigos(client.get(url, {"data_de": "2025-10-01"})) == {b.code}
    assert _codigos(client.get(url, {"data_ate": "2025-09-18"})) == {a.code}
    assert _codigos(
        client.get(url, {"data_de": "2025-09-18", "data_ate": "2025-10-20"})
    ) == {a.code, b.code}


def test_periodo_invertido_mostra_o_erro_e_nao_filtra(client, escritorio, compras):
    client.force_login(escritorio)
    resposta = client.get(
        reverse("purchases:lista"), {"data_de": "2025-10-01", "data_ate": "2025-09-01"}
    )
    assert "A data final é anterior à inicial." in resposta.content.decode()


def test_filtros_se_combinam_e_o_escopo_continua(client, campo_baixao, compras):
    """Quem só enxerga o Baixão não vê a compra de São Francisco nem filtrando
    pelo número dela."""
    a, b = compras
    client.force_login(campo_baixao)
    url = reverse("purchases:lista")
    assert _codigos(client.get(url, {"registro": a.code})) == set()


def test_selector_sem_filtros_extras_se_comporta_como_antes(escritorio, compras):
    assert selectors.listar_compras_para(escritorio).count() == 2
