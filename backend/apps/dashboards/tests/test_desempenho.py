"""Desempenho que não pode voltar atrás: **o número de consultas não cresce com
a quantidade de lotes**.

O sistema ficou lento com o seed grande porque cada lote disparava dezenas de
consultas (e o rateio relia o razão da fazenda inteira por lote). Estes testes
medem a consulta, não o relógio — relógio varia de máquina para máquina, a
contagem não. Um N+1 novo (um laço com consulta dentro) faz o segundo cenário,
com mais lotes, executar mais consultas que o primeiro, e o teste quebra.
"""

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.herd.weight_gain import desempenho_dos_lotes
from apps.livestock.models import Lot
from apps.livestock.selectors import (
    cabecas_que_entraram_por_lote,
    financeiro_dos_lotes,
)
from apps.purchases import services as compras
from apps.sales.result import resultados_dos_lotes
from apps.sales.tests.conftest import DATA_COMPRA, vender

pytestmark = pytest.mark.django_db

D = Decimal


def mais_lotes(n, *, escritorio, sao_francisco, categoria_25_36, vendedor, frigorifico):
    """`n` lotes novos na mesma fazenda, cada um com compra e uma venda parcial."""
    for i in range(n):
        compra = compras.confirmar_compra(
            compras.criar_compra(
                usuario=escritorio,
                date=DATA_COMPRA + datetime.timedelta(days=i % 5),
                destination_farm=sao_francisco,
                category=categoria_25_36,
                seller=vendedor,
                head_count=100,
                animal_value=D("250000"),
                freight_value=D("5000"),
            ),
            usuario=escritorio,
        )
        vender(
            escritorio,
            compra.lot,
            frigorifico,
            categoria_25_36,
            head_count=40,
            total_weight_kg=D("19200"),
            carcass_weight_kg=D("9600"),
            total_value=D("192000"),
        )


def consultas(funcao) -> int:
    with CaptureQueriesContext(connection) as capturadas:
        funcao()
    return len(capturadas)


@pytest.fixture
def cenario(escritorio, sao_francisco, categoria_25_36, vendedor, frigorifico):
    return {
        "escritorio": escritorio,
        "sao_francisco": sao_francisco,
        "categoria_25_36": categoria_25_36,
        "vendedor": vendedor,
        "frigorifico": frigorifico,
    }


def lotes_ativos():
    return list(
        Lot.objects.exclude(status="EXCLUIDO").select_related("farm").order_by("pk")
    )


class TestServicosEmLote:
    def test_consultas_dos_servicos_nao_dependem_do_numero_de_lotes(
        self, cenario, lote_de_compra
    ):
        def tudo(lotes):
            entradas = cabecas_que_entraram_por_lote(lotes)
            desempenho_dos_lotes(lotes)
            financeiro_dos_lotes(lotes, entradas=entradas)
            resultados_dos_lotes(lotes)

        mais_lotes(2, **cenario)
        poucos = lotes_ativos()
        com_poucos = consultas(lambda: tudo(poucos))

        mais_lotes(8, **cenario)
        muitos = lotes_ativos()
        assert len(muitos) > len(poucos) * 3
        com_muitos = consultas(lambda: tudo(muitos))

        assert com_muitos == com_poucos, (
            f"{com_poucos} consultas com {len(poucos)} lotes, "
            f"{com_muitos} com {len(muitos)}: há consulta dentro de laço"
        )


class TestTelasNaoCrescemComOsLotes:
    @pytest.mark.parametrize("aba", ["visao-geral", "lotes", "vendas", "custos"])
    def test_aba_do_dashboard(
        self, client, gestor, season, cenario, lote_de_compra, aba
    ):
        client.force_login(gestor)
        url = reverse("dashboards:dashboard_aba", args=[aba])

        def abrir():
            resposta = client.get(url, HTTP_HX_REQUEST="true")
            assert resposta.status_code == 200

        mais_lotes(2, **cenario)
        abrir()  # aquece o que não é por lote (sessão, tipos de conteúdo)
        com_poucos = consultas(abrir)

        mais_lotes(8, **cenario)
        com_muitos = consultas(abrir)

        assert com_muitos == com_poucos, (
            f"aba {aba}: {com_poucos} consultas com poucos lotes, "
            f"{com_muitos} com mais — há consulta por lote"
        )

    def test_inicio(self, client, gestor, season, cenario, lote_de_compra):
        client.force_login(gestor)

        def abrir():
            assert client.get(reverse("dashboards:inicio")).status_code == 200

        mais_lotes(2, **cenario)
        abrir()
        com_poucos = consultas(abrir)
        mais_lotes(8, **cenario)
        assert consultas(abrir) == com_poucos


class TestNumerosIguaisEmLoteEIndividual:
    """A versão de um lote é um caso da versão em lote: tela do lote e
    dashboard mostram o mesmo número por construção — e aqui se confere."""

    def test_financeiro_e_resultado(self, cenario, lote_de_compra):
        mais_lotes(3, **cenario)
        lotes = lotes_ativos()
        entradas = cabecas_que_entraram_por_lote(lotes)
        em_lote = financeiro_dos_lotes(lotes, entradas=entradas)
        resultados = resultados_dos_lotes(lotes)

        from apps.livestock.selectors import financeiro_do_lote
        from apps.sales.result import resultado_do_lote

        for lote in lotes:
            sozinho = financeiro_do_lote(lote, cabecas_que_entraram=entradas[lote.pk])
            assert em_lote[lote.pk] == sozinho
            assert resultados[lote.pk] == resultado_do_lote(lote)

    def test_desempenho(self, cenario, lote_de_compra):
        mais_lotes(3, **cenario)
        lotes = lotes_ativos()
        em_lote = desempenho_dos_lotes(lotes)

        from apps.herd.weight_gain import desempenho_do_lote

        for lote in lotes:
            assert em_lote[lote.pk] == desempenho_do_lote(lote)
