"""Indicadores do consultor (cliente, 2026-10-03, pendência #39): mortalidade por
causa, curva ABC, inventário valorizado, TIR e confinamento."""

import datetime
from decimal import Decimal

import pytest

from apps.accounts.models import Role, User
from apps.herd import services as herd
from apps.herd.models import DeathCause, MovementType, WeighingReason
from apps.livestock.models import LotRegime
from apps.reports import services as relatorios
from apps.reports.tests.test_reports import DASH_FINANCEIRO, popular
from apps.sales.tests.conftest import *  # noqa: F401,F403
from apps.sales.tests.conftest import vender

pytestmark = pytest.mark.django_db
D = Decimal


def montar(user, slug, season, **extras):
    return relatorios.montar_relatorio(
        user, slug, season=season, farm=None, extras=extras
    )


class TestCurvaAbc:
    def test_perfil_a_b_c_pelo_acumulado(self, gestor, baixao, custeio, season):
        popular(gestor, baixao, custeio)
        r = montar(gestor, "curva-abc-de-custos", season)

        total = sum(DASH_FINANCEIRO.values())
        assert r.totais["valor"] == total == D("1046907.76")
        # do maior para o menor
        valores = [lin["valor"] for lin in r.linhas]
        assert valores == sorted(valores, reverse=True)
        # OUTROS (R$ 416 mil, 39,8%) e FUNCIONARIO (16,5%) abrem a curva: A
        assert [lin["perfil"] for lin in r.linhas[:2]] == ["A", "A"]
        # o último centro (R$ 639) está depois dos 95%: C
        assert r.linhas[-1]["perfil"] == "C"
        assert r.linhas[-1]["acumulado"].quantize(D("0.01")) == D("100.00")
        assert {lin["perfil"] for lin in r.linhas} == {"A", "B", "C"}

    def test_maior_centro_e_sempre_a_mesmo_passando_de_80(
        self, gestor, baixao, custeio, season
    ):
        from apps.costs import services as custos
        from apps.costs.models import CostCenter

        custos.registrar_custo(
            date=datetime.date(2025, 9, 1),
            farm=baixao,
            cost_center=CostCenter.objects.get(name="FUNCIONARIO"),
            cost_class=custeio,
            amount=D("900"),
            description="x",
            usuario=gestor,
        )
        custos.registrar_custo(
            date=datetime.date(2025, 9, 1),
            farm=baixao,
            cost_center=CostCenter.objects.get(name="OUTROS"),
            cost_class=custeio,
            amount=D("100"),
            description="y",
            usuario=gestor,
        )
        r = montar(gestor, "curva-abc-de-custos", season)
        assert r.linhas[0]["perfil"] == "A" and r.linhas[0]["participacao"] == D("90")

    def test_sem_custo_nao_quebra(self, gestor, season):
        assert montar(gestor, "curva-abc-de-custos", season).linhas == []

    def test_campo_nao_ve_dinheiro(self, campo_baixao, season):
        from django.core.exceptions import PermissionDenied

        for slug in ("curva-abc-de-custos", "inventario-valorizado", "tir-da-safra"):
            with pytest.raises(PermissionDenied):
                montar(campo_baixao, slug, season)
        assert "curva-abc-de-custos" not in {
            i[0] for i in relatorios.catalogo_para(campo_baixao)
        }


class TestMortalidadePorCausa:
    def _morte(self, escritorio, lote, categoria, quantidade, causa):
        return herd.registrar_movimento(
            type=MovementType.MORTE,
            date=datetime.date(2025, 7, 25),
            quantity=quantidade,
            usuario=escritorio,
            origin_farm=lote.farm,
            origin_lot=lote,
            origin_category=categoria,
            reason="Encontrado morto",
            death_cause=causa,
        )

    def test_agrupa_por_causa_e_diz_nao_informada(
        self, escritorio, gestor, season, lote_gordo, categoria_25_36
    ):
        self._morte(
            escritorio, lote_gordo, categoria_25_36, 3, DeathCause.PICADA_DE_COBRA
        )
        self._morte(escritorio, lote_gordo, categoria_25_36, 1, DeathCause.ONCA)
        self._morte(escritorio, lote_gordo, categoria_25_36, 1, "")

        r = montar(gestor, "mortalidade-por-causa", season)

        por_causa = {lin["causa"]: lin["mortes"] for lin in r.linhas}
        assert por_causa == {
            "Picada de cobra": 3,
            "Ataque de onça / predador": 1,
            "Não informada": 1,
        }
        assert r.totais["mortes"] == 5
        assert r.linhas[0]["participacao"] == D("60")
        # a taxa por fazenda vem do serviço de sempre, sem juízo de "acima do normal"
        assert r.secoes[0].linhas[0]["mortes"] == 5
        assert any(
            "não define o que é mortalidade acima do normal" in n for n in r.notas
        )

    def test_causa_so_vale_em_morte(
        self, escritorio, lote_gordo, categoria_25_36, sao_francisco
    ):
        from apps.core.exceptions import BusinessError

        with pytest.raises(
            BusinessError, match="só se informa em movimentação de morte"
        ):
            herd.registrar_movimento(
                type=MovementType.CONSUMO_DOACAO,
                date=datetime.date(2025, 7, 25),
                quantity=1,
                usuario=escritorio,
                origin_farm=sao_francisco,
                origin_lot=lote_gordo,
                origin_category=categoria_25_36,
                reason="Consumo",
                death_cause=DeathCause.ONCA,
            )


class TestInventarioValorizado:
    def test_sem_peso_nao_inventa_valor_de_mercado(self, gestor, season, lote_gordo):
        r = montar(gestor, "inventario-valorizado", season, preco_arroba=D("300"))
        (linha,) = r.linhas
        assert linha["cabecas"] == 100
        assert linha["peso_medio"] is None and linha["mercado"] is None
        assert any("Sem peso" in n for n in r.notas)

    def test_com_pesagem_e_preco_a_arroba_viva_de_30_kg(
        self, gestor, escritorio, season, lote_gordo, sao_francisco
    ):
        herd.registrar_pesagem(
            date=datetime.date(2025, 7, 20),
            farm=sao_francisco,
            lot=lote_gordo,
            reason=WeighingReason.CONFERENCIA,
            head_count=100,
            total_weight_kg=D("45000"),  # 450 kg por cabeça = 15 @ vivas
            usuario=escritorio,
        )
        r = montar(gestor, "inventario-valorizado", season, preco_arroba=D("300"))
        (linha,) = r.linhas
        assert linha["peso_medio"] == D("450")
        assert linha["arrobas"] == D("1500")  # 100 × 450 ÷ 30
        assert linha["mercado"] == D("450000")  # 1.500 @ × R$ 300
        assert r.totais["mercado"] == D("450000")

    def test_sem_preco_pede_o_preco_e_nao_escolhe_um(self, gestor, season, lote_gordo):
        r = montar(gestor, "inventario-valorizado", season)
        assert r.linhas[0]["mercado"] is None
        assert any("Informe o preço da @" in n for n in r.notas)


class TestTir:
    def test_sem_venda_e_sem_preco_nao_ha_tir(self, gestor, baixao, custeio, season):
        popular(gestor, baixao, custeio)
        r = montar(gestor, "tir-da-safra", season)
        tir_mes, tir_ano = r.secoes[0].linhas
        assert tir_mes["valor"] is None and tir_ano["valor"] is None
        assert any("não troca de sinal" in n for n in r.notas)

    def test_fluxo_mensal_e_tir_com_venda(
        self, gestor, escritorio, season, lote_de_compra, frigorifico, categoria_25_36
    ):
        # compra (R$ 255 mil) em jul/2025 e abate de R$ 480 mil em ago/2025
        vender(escritorio, lote_de_compra, frigorifico, categoria_25_36)
        r = montar(gestor, "tir-da-safra", season)

        assert r.linhas[0]["mes"] == "07/2025"
        assert r.totais["entradas"] == D("480000")
        assert r.totais["saidas"] > 0
        tir_mes = r.secoes[0].linhas[0]["valor"]
        assert tir_mes is not None and tir_mes > 0  # vendeu por mais do que gastou


class TestConfinamento:
    def test_so_lista_lote_marcado_como_confinamento(self, gestor, season, lote_gordo):
        assert montar(gestor, "confinamento", season).linhas == []
        lote_gordo.regime = LotRegime.CONFINAMENTO
        lote_gordo.save()
        r = montar(gestor, "confinamento", season)
        (linha,) = r.linhas
        assert linha["lote"] == lote_gordo.code and linha["cabecas"] == 100
        # sem pesagem não há GMD: "—", nunca zero
        assert linha["gmd"] is None and linha["arrobas"] is None


def test_escopo_de_fazenda_vale_nos_relatorios_novos(season, baixao, lote_gordo):
    from apps.accounts.models import UserFarmAccess

    so_baixao = User.objects.create_user(
        username="sb", password="x", role=Role.ESCRITORIO
    )
    UserFarmAccess.objects.create(user=so_baixao, farm=baixao, can_write=True)
    assert montar(so_baixao, "inventario-valorizado", season).linhas == []
    assert montar(so_baixao, "mortalidade-por-causa", season).linhas == []
