"""F2-13 — relatórios de custo e compra. O de centro reproduz a tabela do
`DASH FINANCEIRO` (docs/regras-negocio/05#custo-por-centro-de-custo)."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.costs import services as custos
from apps.costs.models import CostCenter
from apps.purchases import services as compras
from apps.reports import services

pytestmark = pytest.mark.django_db
D = Decimal

# Tabela do DASH FINANCEIRO, já com os R$ 411.132,64 sem centro classificados
# (aqui, todos em OUTROS): o total fecha em R$ 1.046.907,76.
DASH_FINANCEIRO = {
    "FUNCIONARIO": D("172593.34"),
    "PASTAGEM": D("142323.00"),
    "NUTRIÇÃO": D("136099.99"),
    "PARQUE DE MÁQUINAS": D("109794.93"),
    "INFRAESTRUTURA": D("27740.19"),
    "DESPESA GADO": D("20776.50"),
    "SANIDADE": D("11348.90"),
    "IMPOSTO E TAXAS": D("6330.77"),
    "OUTROS": D("5262.00") + D("411132.64"),
    "COMISSÃO": D("2866.50"),
    "FERPAM": D("639.00"),
}


def popular(gestor, baixao, custeio):
    for nome, valor in DASH_FINANCEIRO.items():
        custos.registrar_custo(
            date=datetime.date(2025, 9, 18),
            farm=baixao,
            cost_center=CostCenter.objects.get(name=nome),
            cost_class=custeio,
            amount=valor,
            description=nome,
            usuario=gestor,
        )


class TestCustosPorCentro:
    def test_reproduz_o_dash_financeiro_e_o_total_de_1_046_907_76(
        self, gestor, baixao, custeio, season
    ):
        popular(gestor, baixao, custeio)

        relatorio = services.custos_por_centro(gestor, season=season, farm=None)

        por_nome = {lin["nome"]: lin["total"] for lin in relatorio.linhas}
        assert por_nome == DASH_FINANCEIRO
        assert relatorio.totais["total"] == D("1046907.76")
        assert len(relatorio.linhas) == 11

    def test_ordenado_do_maior_para_o_menor_e_com_participacao(
        self, gestor, baixao, custeio, season
    ):
        popular(gestor, baixao, custeio)

        relatorio = services.custos_por_centro(gestor, season=season, farm=None)

        assert relatorio.linhas[0]["nome"] == "OUTROS"
        totais = [lin["total"] for lin in relatorio.linhas]
        assert totais == sorted(totais, reverse=True)
        assert relatorio.linhas[0]["participacao"].quantize(D("0.01")) == D(
            "39.77"
        )  # (5.262+411.132,64) ÷ total

    def test_sem_lancamentos_nao_divide_por_zero(self, gestor, season):
        relatorio = services.custos_por_centro(gestor, season=season, farm=None)

        assert relatorio.linhas == []
        assert relatorio.totais["participacao"] is None  # "—", não 0 nem erro

    def test_so_conta_o_confirmado_e_respeita_o_escopo(
        self,
        gestor,
        escritorio,
        campo_baixao,
        baixao,
        sao_francisco,
        custeio,
        season,
        centro_funcionario,
    ):
        custos.registrar_custo(
            date=datetime.date(2025, 9, 18),
            farm=baixao,
            cost_center=centro_funcionario,
            cost_class=custeio,
            amount=D("100"),
            description="a",
            usuario=gestor,
        )
        excluido = custos.registrar_custo(
            date=datetime.date(2025, 9, 18),
            farm=baixao,
            cost_center=centro_funcionario,
            cost_class=custeio,
            amount=D("50"),
            description="b",
            usuario=gestor,
        )
        custos.excluir_custo(excluido, usuario=gestor, motivo="erro")
        custos.registrar_custo(
            date=datetime.date(2025, 9, 18),
            farm=sao_francisco,
            cost_center=centro_funcionario,
            cost_class=custeio,
            amount=D("999"),
            description="c",
            usuario=gestor,
        )

        do_campo = services.custos_por_centro(campo_baixao, season=season, farm=None)

        assert do_campo.totais["total"] == D(
            "100"
        )  # sem o excluído, sem a outra fazenda


class TestOutrosRelatorios:
    def test_por_fazenda_e_custeio_x_investimento(
        self,
        gestor,
        baixao,
        sao_francisco,
        custeio,
        investimento,
        centro_funcionario,
        season,
    ):
        for farm, classe, valor in (
            (baixao, custeio, "100"),
            (sao_francisco, investimento, "300"),
        ):
            custos.registrar_custo(
                date=datetime.date(2025, 9, 18),
                farm=farm,
                cost_center=centro_funcionario,
                cost_class=classe,
                amount=D(valor),
                description="x",
                usuario=gestor,
            )

        por_fazenda = services.custos_por_fazenda(gestor, season=season)
        por_classe = services.custeio_x_investimento(gestor, season=season, farm=None)

        assert {lin["nome"]: lin["total"] for lin in por_fazenda.linhas} == {
            "Baixão": D("100"),
            "São Francisco": D("300"),
        }
        assert {lin["nome"]: lin["total"] for lin in por_classe.linhas} == {
            "CUSTEIO": D("100"),
            "INVESTIMENTO": D("300"),
        }

    def test_compras_do_periodo_e_custo_por_arroba_so_com_peso(
        self, escritorio, gestor, season, dados_compra_rel
    ):
        compras.confirmar_compra(
            compras.criar_compra(usuario=escritorio, **dados_compra_rel),
            usuario=escritorio,
        )

        relatorio = services.compras_do_periodo(gestor, season=season, farm=None)

        linha = relatorio.linhas[0]
        assert linha["cabecas"] == 105
        assert linha["media_cabeca"].quantize(D("0.01")) == D("2477.83")
        assert linha["custo_arroba"] is None
        assert services.formatar(linha["custo_arroba"], services.DINHEIRO) == "—"
        assert relatorio.secoes[0].linhas[0]["cabecas"] == 105  # por mês

    def test_aquisicao_por_lote(self, escritorio, gestor, season, dados_compra_rel):
        compras.confirmar_compra(
            compras.criar_compra(usuario=escritorio, **dados_compra_rel),
            usuario=escritorio,
        )

        relatorio = services.aquisicao_por_lote(gestor, season=season, farm=None)

        assert relatorio.linhas[0]["lote"].startswith("LT-")
        assert relatorio.linhas[0]["custo_aquisicao"] == D("260172.15")


@pytest.fixture
def dados_compra_rel(baixao, categoria_desmamados):
    return {
        "date": datetime.date(2025, 12, 29),
        "destination_farm": baixao,
        "category": categoria_desmamados,
        "head_count": 105,
        "animal_value": D("260172.15"),
    }


class TestTelaECsv:
    def test_tela_mostra_valores_em_formato_brasileiro(
        self, client, gestor, baixao, custeio, season
    ):
        popular(gestor, baixao, custeio)
        client.force_login(gestor)

        html = client.get(
            reverse("reports:relatorio", args=["custos-por-centro"])
        ).content.decode()

        assert "R$ 1.046.907,76" in html
        assert "R$ 172.593,34" in html

    def test_csv_exporta_com_ponto_e_virgula_e_virgula_decimal_e_audita(
        self, client, gestor, baixao, custeio, season
    ):
        popular(gestor, baixao, custeio)
        client.force_login(gestor)

        resposta = client.get(
            reverse("reports:relatorio", args=["custos-por-centro"]) + "?formato=csv"
        )

        corpo = resposta.content.decode("utf-8")
        assert resposta["Content-Type"].startswith("text/csv")
        assert corpo.startswith("﻿")
        assert "FUNCIONARIO;" in corpo and "R$ 172.593,34" in corpo
        assert AuditEvent.objects.filter(
            action="EXPORT", entity_id="custos-por-centro"
        ).exists()

    def test_relatorio_inexistente_da_404(self, client, gestor):
        client.force_login(gestor)

        assert (
            client.get(reverse("reports:relatorio", args=["nao-existe"])).status_code
            == 404
        )

    def test_anonimo_nao_ve(self, client, db):
        assert client.get(reverse("reports:indice")).status_code == 302

    def test_indice_lista_os_5_relatorios(self, client, gestor):
        client.force_login(gestor)

        html = client.get(reverse("reports:indice")).content.decode()

        for titulo in (
            "Custos por centro de custo",
            "Custos por fazenda",
            "Custeio × investimento",
            "Compras do período",
            "Custo de aquisição por lote",
        ):
            assert titulo in html
