"""Ajustes pedidos pelo cliente (out/2026): custos por fazenda, desempenho do
lote com o peso de entrada da compra e a movimentação por fazenda."""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from apps.core import reversible
from apps.costs import services as custos
from apps.herd import services as herd
from apps.herd.models import MovementType, WeighingReason
from apps.livestock.models import Lot
from apps.purchases import services as compras
from apps.reports import services

pytestmark = pytest.mark.django_db
D = Decimal


def montar(user, slug, season, farm=None, **extras):
    return services.montar_relatorio(
        user, slug, season=season, farm=farm, extras=extras
    )


# --------------------------------------------------------------------------
# Custos por fazenda
# --------------------------------------------------------------------------


@pytest.fixture
def custos_em_duas_fazendas(
    gestor, baixao, sao_francisco, custeio, centro_funcionario, centro_maquinas
):
    def lancar(farm, dia, centro, valor, descricao):
        return custos.registrar_custo(
            date=dia,
            farm=farm,
            cost_center=centro,
            cost_class=custeio,
            amount=D(valor),
            description=descricao,
            usuario=gestor,
        )

    lancar(baixao, datetime.date(2025, 9, 5), centro_funcionario, "100", "Salário")
    lancar(baixao, datetime.date(2025, 10, 5), centro_maquinas, "40", "Diesel")
    lancar(sao_francisco, datetime.date(2025, 9, 6), centro_funcionario, "999", "Outra")


class TestCustosPorFazenda:
    def test_centro_de_custo_filtra_pela_fazenda_escolhida(
        self, gestor, baixao, season, custos_em_duas_fazendas
    ):
        todas = montar(gestor, "custos-por-centro", season)
        so_baixao = montar(gestor, "custos-por-centro", season, fazenda=baixao)

        assert todas.totais["total"] == D("1139")
        assert so_baixao.totais["total"] == D("140")
        assert "Fazenda Baixão" in so_baixao.filtros

    def test_detalhado_traz_cada_lancamento_da_fazenda_e_do_periodo(
        self, gestor, baixao, season, custos_em_duas_fazendas
    ):
        r = montar(gestor, "custos-por-fazenda-detalhado", season, fazenda=baixao)
        assert [lin["descricao"] for lin in r.linhas] == ["Salário", "Diesel"]
        assert r.linhas[0]["data"] == "05/09/2025" and r.linhas[0]["valor"] == D("100")
        assert r.totais["valor"] == D("140")

        setembro = montar(
            gestor,
            "custos-por-fazenda-detalhado",
            season,
            fazenda=baixao,
            start=datetime.date(2025, 9, 1),
            end=datetime.date(2025, 9, 30),
        )
        assert [lin["descricao"] for lin in setembro.linhas] == ["Salário"]
        assert "Período: 01/09/2025 a 30/09/2025" in setembro.filtros

    def test_detalhado_nao_traz_o_excluido_nem_a_fazenda_fora_do_escopo(
        self, gestor, campo_baixao, baixao, season, custos_em_duas_fazendas
    ):
        from apps.costs.models import CostEntry

        extra = CostEntry.objects.get(description="Diesel")
        custos.excluir_custo(extra, usuario=gestor, motivo="lançado em duplicidade")
        r = montar(gestor, "custos-por-fazenda-detalhado", season, fazenda=baixao)
        assert [lin["descricao"] for lin in r.linhas] == ["Salário"]

    def test_campo_nao_abre_o_detalhado(self, campo_baixao, season):
        with pytest.raises(PermissionDenied):
            montar(campo_baixao, "custos-por-fazenda-detalhado", season)

    def test_a_tela_oferece_o_filtro_de_fazenda_e_o_aplica(
        self, client, gestor, baixao, custos_em_duas_fazendas
    ):
        client.force_login(gestor)
        url = reverse("reports:relatorio", args=["custos-por-fazenda-detalhado"])
        html = client.get(url).content.decode()
        assert 'name="fazenda"' in html
        filtrado = client.get(url, {"fazenda": baixao.pk}).content.decode()
        assert "Salário" in filtrado and "Outra" not in filtrado

    def test_fazenda_fora_do_escopo_nao_vira_filtro(
        self, client, campo_baixao, sao_francisco, custos_em_duas_fazendas
    ):
        client.force_login(campo_baixao)
        html = client.get(
            reverse("reports:relatorio", args=["custos-por-centro"]),
            {"fazenda": sao_francisco.pk},
        ).content.decode()
        assert "Fazenda São Francisco" not in html


# --------------------------------------------------------------------------
# Desempenho do lote: o peso de entrada é o da compra
# --------------------------------------------------------------------------


@pytest.fixture
def lote_comprado_com_peso(escritorio, sao_francisco, categoria_25_36, vendedor):
    compra = compras.criar_compra(
        usuario=escritorio,
        date=datetime.date(2025, 9, 1),
        destination_farm=sao_francisco,
        category=categoria_25_36,
        seller=vendedor,
        head_count=100,
        total_weight_kg=D("48000"),
        animal_value=D("250000"),
    )
    return compras.confirmar_compra(compra, usuario=escritorio).lot


class TestDesempenhoDoLote:
    def _linha(self, gestor, season, **extras):
        rel = services.desempenho_dos_lotes(gestor, season=season, farm=None, **extras)
        return rel.linhas

    def test_peso_inicial_vem_da_compra_mesmo_sem_gmd(
        self, gestor, season, lote_comprado_com_peso
    ):
        (linha,) = self._linha(gestor, season)
        assert linha["peso_inicial"] == D("480")  # 48.000 kg ÷ 100 cabeças
        assert linha["gmd"] is None and linha["observacao"]  # e diz por quê

    def test_pesagem_no_mesmo_dia_da_compra_nao_apaga_o_peso_inicial(
        self, gestor, escritorio, season, lote_comprado_com_peso, sao_francisco
    ):
        herd.registrar_pesagem(
            date=datetime.date(2025, 9, 1),
            farm=sao_francisco,
            lot=lote_comprado_com_peso,
            reason=WeighingReason.CONFERENCIA,
            head_count=100,
            total_weight_kg=D("49000"),
            usuario=escritorio,
        )
        (linha,) = self._linha(gestor, season)
        assert linha["peso_inicial"] == D("480")
        assert linha["gmd"] is None  # mesmo dia: sem GMD, sem inventar

    def test_com_outra_data_o_gmd_parte_do_peso_da_compra(
        self, gestor, escritorio, season, lote_comprado_com_peso, sao_francisco
    ):
        herd.registrar_pesagem(
            date=datetime.date(2025, 9, 21),
            farm=sao_francisco,
            lot=lote_comprado_com_peso,
            reason=WeighingReason.CONFERENCIA,
            head_count=100,
            total_weight_kg=D("49000"),
            usuario=escritorio,
        )
        (linha,) = self._linha(gestor, season)
        assert linha["gmd"] == D("0.5")  # (490 − 480) kg ÷ 20 dias
        assert linha["desde_entrada"] == "Sim"
        assert linha["peso_inicial"] == D("480") and linha["peso_final"] == D("490")

    def test_compra_sem_peso_continua_sem_peso_inicial_e_diz_por_que(
        self, gestor, season, lote_de_compra
    ):
        (linha,) = self._linha(gestor, season)
        assert linha["peso_inicial"] is None
        assert "nem todas as compras" in linha["observacao"]

    def test_filtro_de_situacao_do_lote(
        self, gestor, season, lote_comprado_com_peso, lote_gordo
    ):
        Lot.objects.filter(pk=lote_gordo.pk).update(status="ENCERRADO")
        todos = {lin["lote"] for lin in self._linha(gestor, season)}
        abertos = self._linha(gestor, season, situacao="ABERTO")
        encerrados = self._linha(gestor, season, situacao="ENCERRADO")

        assert todos == {lote_comprado_com_peso.code, lote_gordo.code}
        assert [lin["lote"] for lin in abertos] == [lote_comprado_com_peso.code]
        assert [lin["lote"] for lin in encerrados] == [lote_gordo.code]

    def test_o_filtro_de_situacao_vale_na_tela_e_aparece_nos_filtros(
        self, client, gestor, season, lote_comprado_com_peso, lote_gordo
    ):
        Lot.objects.filter(pk=lote_gordo.pk).update(status="ENCERRADO")
        client.force_login(gestor)
        url = reverse("reports:relatorio", args=["desempenho-do-lote"])
        html = client.get(url, {"situacao": "ENCERRADO"}).content.decode()
        assert "Situação do lote: encerrados" in html
        assert lote_gordo.code in html and lote_comprado_com_peso.code not in html


# --------------------------------------------------------------------------
# Movimentação por fazenda
# --------------------------------------------------------------------------

PERIODO = {"start": datetime.date(2025, 8, 1), "end": datetime.date(2025, 8, 31)}


@pytest.fixture
def movimentos(
    escritorio,
    gestor,
    sao_francisco,
    baixao,
    lote_gordo,
    lote_baixao,
    categoria_25_36,
):
    """São Francisco: 100 de saldo (julho), e em agosto 3 mortes, 10 abatidas e
    20 transferidas para o Baixão."""

    def lancar(tipo, dia, quantidade, **extra):
        return herd.registrar_movimento(
            type=tipo,
            date=datetime.date(2025, 8, dia),
            quantity=quantidade,
            usuario=gestor,
            **extra,
        )

    origem = dict(
        origin_farm=sao_francisco,
        origin_lot=lote_gordo,
        origin_category=categoria_25_36,
    )
    return {
        "morte": lancar(MovementType.MORTE, 5, 3, reason="Picada", **origem),
        "abate": lancar(MovementType.ABATE, 10, 10, **origem),
        "transf": lancar(
            MovementType.TRANSFERENCIA,
            15,
            20,
            destination_farm=baixao,
            destination_lot=lote_baixao,
            destination_category=categoria_25_36,
            **origem,
        ),
    }


def _linha(relatorio, categoria):
    return next(lin for lin in relatorio.linhas if lin["categoria"] == categoria.name)


class TestMovimentacaoPorFazenda:
    def test_quadro_da_fazenda_fecha_com_o_saldo_do_razao(
        self, gestor, season, sao_francisco, categoria_25_36, movimentos
    ):
        r = montar(gestor, "movimentacao-por-fazenda", season, sao_francisco, **PERIODO)
        linha = _linha(r, categoria_25_36)

        assert linha["saldo_anterior"] == 100
        assert linha["morte"] == 3 and linha["abate"] == 10
        assert linha["transf_s"] == 20 and linha["transf_e"] == 0
        assert linha["total_s"] == 33 and linha["total_e"] == 0
        assert linha["posicao"] == 67
        # a posição final é o saldo do razão na data final
        assert (
            linha["posicao"]
            == herd.saldo(
                farm=sao_francisco, category=categoria_25_36, until=PERIODO["end"]
            )["head_count"]
        )
        assert r.totais["posicao"] == 67 and r.totais["categoria"] == "Total"

    def test_a_outra_ponta_da_transferencia_e_entrada(
        self, gestor, season, baixao, categoria_25_36, movimentos
    ):
        r = montar(gestor, "movimentacao-por-fazenda", season, baixao, **PERIODO)
        linha = _linha(r, categoria_25_36)
        assert linha["transf_e"] == 20 and linha["transf_s"] == 0
        assert linha["posicao"] == 20

    def test_transferencia_soma_zero_no_consolidado(
        self, gestor, season, categoria_25_36, movimentos
    ):
        r = montar(gestor, "movimentacao-por-fazenda", season, None, **PERIODO)
        linha = _linha(r, categoria_25_36)
        assert linha["transf_e"] == linha["transf_s"] == 20
        assert linha["posicao"] == 100 - 3 - 10  # a transferência não muda o total

    def test_desfazer_um_movimento_corrige_o_quadro_para_tras(
        self, gestor, season, sao_francisco, categoria_25_36, movimentos
    ):
        reversible.excluir(movimentos["morte"], usuario=gestor, motivo="Lançada errada")
        r = montar(gestor, "movimentacao-por-fazenda", season, sao_francisco, **PERIODO)
        linha = _linha(r, categoria_25_36)
        assert linha["morte"] == 0
        assert linha["posicao"] == 70

    def test_entre_lotes_da_mesma_fazenda_nao_e_entrada_nem_saida_da_fazenda(
        self, gestor, season, sao_francisco, lote_gordo, categoria_25_36, escritorio
    ):
        outro = Lot.objects.create(
            code="LT-SFR-011",
            farm=sao_francisco,
            season=season,
            entry_date=datetime.date(2025, 7, 10),
        )
        herd.registrar_movimento(
            type=MovementType.TRANSFERENCIA,
            date=datetime.date(2025, 8, 12),
            quantity=15,
            usuario=gestor,
            origin_farm=sao_francisco,
            origin_lot=lote_gordo,
            origin_category=categoria_25_36,
            destination_farm=sao_francisco,
            destination_lot=outro,
            destination_category=categoria_25_36,
        )
        r = montar(gestor, "movimentacao-por-fazenda", season, sao_francisco, **PERIODO)
        linha = _linha(r, categoria_25_36)
        assert linha["transf_e"] == 0 and linha["transf_s"] == 0
        assert linha["posicao"] == 100  # nada saiu da fazenda
        # na mesma categoria o líquido é zero: nenhuma coluna "outras" aparece
        assert not {"outras_e", "outras_s"} & {c.chave for c in r.colunas}

    def test_lista_de_movimentacoes_com_destino_e_peso_medio(
        self, gestor, season, sao_francisco, movimentos
    ):
        r = montar(gestor, "movimentacao-por-fazenda", season, sao_francisco, **PERIODO)
        (lista,) = r.secoes
        por_tipo = {lin["tipo"]: lin for lin in lista.linhas}
        assert [lin["tipo"] for lin in lista.linhas] == [
            "Morte",
            "Abate",
            "Transferência",
        ]
        assert por_tipo["Transferência"]["com_quem"] == "para Baixão"
        assert por_tipo["Morte"]["mes"] == "ago"
        assert por_tipo["Morte"]["peso_medio"] is None  # sem peso: "—", nunca 0

    def test_sem_datas_o_periodo_e_a_safra_e_o_escopo_vale(
        self, gestor, campo_baixao, season, sao_francisco, categoria_25_36, movimentos
    ):
        r = montar(gestor, "movimentacao-por-fazenda", season, sao_francisco)
        assert any(f.startswith("Período: 01/07/2025") for f in r.filtros)
        # quem só enxerga o Baixão não vê a fazenda São Francisco
        do_campo = montar(
            campo_baixao, "movimentacao-por-fazenda", season, None, **PERIODO
        )
        assert all(lin["saldo_anterior"] == 0 for lin in do_campo.linhas)
        assert [x for x in do_campo.secoes[0].linhas if x["tipo"] == "Morte"] == []

    def test_vem_no_catalogo_e_a_tela_abre(self, client, gestor, season, movimentos):
        client.force_login(gestor)
        assert (
            "Movimentação por fazenda"
            in client.get(reverse("reports:indice")).content.decode()
        )
        resposta = client.get(
            reverse("reports:relatorio", args=["movimentacao-por-fazenda"]),
            {"de": "2025-08-01", "ate": "2025-08-31"},
        )
        assert resposta.status_code == 200
        assert "Posição final" in resposta.content.decode()
