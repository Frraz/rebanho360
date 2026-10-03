"""F1-13: tela do lote — indicador sem dado aparece como "—" com o
motivo, nunca como 0 — ver docs/fluxos/01-fluxo-fazenda-a-pasto.md e
docs/roadmap/fase-1-cadastros-e-rebanho.md#f1-13."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.herd import services
from apps.herd.models import MovementType, WeighingReason
from apps.livestock import selectors
from apps.livestock.models import AnimalCategory, Lot, Sex
from apps.organizations.models import Company, Season
from apps.properties.models import Farm

pytestmark = pytest.mark.django_db

DATA = datetime.date(2025, 9, 18)


@pytest.fixture
def company():
    return Company.objects.create(name="Fazendas Reunidas")


@pytest.fixture
def season(company):
    return Season.objects.create(
        company=company,
        name="2025/2026",
        start_date=datetime.date(2025, 7, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )


@pytest.fixture
def farm():
    return Farm.objects.create(name="São Francisco", code="SFR")


@pytest.fixture
def categoria():
    return AnimalCategory.objects.create(
        name="Machos Desm. até 12m", sex=Sex.MACHO, age_order=2
    )


@pytest.fixture
def lote(farm, season):
    return Lot.objects.create(
        code="LT-SFR-004",
        farm=farm,
        season=season,
        entry_date=datetime.date(2025, 9, 18),
    )


@pytest.fixture
def gestor():
    return User.objects.create_user(username="gestor", password="x", role=Role.GESTOR)


class TestDetalheDoLote:
    def test_financeiro_aparece_como_travessao_sem_purchase_ainda(self, lote):
        detalhe = selectors.detalhe_do_lote(lote)
        assert detalhe["financeiro"]["aquisicao"] is None
        assert detalhe["financeiro"]["custos"] is None

    def test_posicao_reflete_o_razao(self, lote, farm, categoria, gestor):
        services.registrar_movimento(
            type=MovementType.COMPRA,
            date=DATA,
            quantity=133,
            usuario=gestor,
            destination_farm=farm,
            destination_lot=lote,
            destination_category=categoria,
        )
        services.registrar_movimento(
            type=MovementType.MORTE,
            date=DATA,
            quantity=2,
            usuario=gestor,
            origin_farm=farm,
            origin_lot=lote,
            origin_category=categoria,
            reason="causa desconhecida",
        )
        detalhe = selectors.detalhe_do_lote(lote)
        assert detalhe["posicao"]["cabecas"] == 131
        assert detalhe["posicao"]["entradas"] == 133
        assert detalhe["posicao"]["mortes"] == 2

    def test_aviso_de_arroba_produzida_sempre_presente_na_fase_1(self, lote):
        detalhe = selectors.detalhe_do_lote(lote)
        assert any("carcaça" in a for a in detalhe["avisos"])

    def test_sem_pesagem_gera_aviso(self, lote):
        detalhe = selectors.detalhe_do_lote(lote)
        assert any("pesagem" in a.lower() for a in detalhe["avisos"])

    def test_gmd_aparece_quando_ha_duas_pesagens(self, lote, farm, gestor):
        services.registrar_pesagem(
            date=datetime.date(2025, 9, 1),
            farm=farm,
            lot=lote,
            reason=WeighingReason.CONFERENCIA,
            head_count=10,
            total_weight_kg=Decimal("2000"),
            usuario=gestor,
        )
        services.registrar_pesagem(
            date=datetime.date(2025, 9, 11),
            farm=farm,
            lot=lote,
            reason=WeighingReason.CONFERENCIA,
            head_count=10,
            total_weight_kg=Decimal("2074"),
            usuario=gestor,
        )
        detalhe = selectors.detalhe_do_lote(lote)
        assert detalhe["desempenho"]["gmd"] == Decimal("0.74")
        assert detalhe["desempenho"]["peso_medio"] == Decimal("207.4")


class TestTelaDoLote:
    def test_tela_mostra_travessao_para_financeiro_indisponivel(
        self, client, lote, gestor
    ):
        client.force_login(gestor)
        response = client.get(reverse("livestock:lote_detalhe", args=[lote.pk]))
        assert response.status_code == 200
        conteudo = response.content.decode("utf-8")
        assert "—" in conteudo
        assert "Aquisição" in conteudo
