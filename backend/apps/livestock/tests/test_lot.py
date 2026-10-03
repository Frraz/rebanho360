"""F1-05: `Lot` sem quantidade/peso/categoria como campo — saem do razão
(ADR 0002) — ver docs/roadmap/fase-1-cadastros-e-rebanho.md#f1-05."""

import datetime

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User, UserFarmAccess
from apps.livestock import services
from apps.livestock.models import Lot
from apps.organizations.models import Company, Season
from apps.properties.models import Farm

pytestmark = pytest.mark.django_db


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
def escritorio():
    return User.objects.create_user(
        username="escritorio", password="x", role=Role.ESCRITORIO
    )


class TestLoteNaoTemQuantidadeOuPeso:
    def test_modelo_nao_tem_campo_de_quantidade_peso_ou_categoria(self):
        nomes_dos_campos = {f.name for f in Lot._meta.get_fields()}
        for proibido in ("head_count", "quantity", "weight", "category"):
            assert proibido not in nomes_dos_campos


class TestGeracaoDeCodigo:
    def test_codigo_segue_o_padrao_lt_fazenda_sequencial(
        self, farm, season, escritorio
    ):
        lote = Lot(farm=farm, season=season, entry_date=datetime.date(2025, 9, 18))
        services.criar_lote(lote, usuario=escritorio)

        assert lote.code == "LT-SFR-001"

    def test_segundo_lote_da_mesma_fazenda_incrementa(self, farm, season, escritorio):
        services.criar_lote(
            Lot(farm=farm, season=season, entry_date=datetime.date(2025, 9, 18)),
            usuario=escritorio,
        )
        segundo = Lot(farm=farm, season=season, entry_date=datetime.date(2025, 10, 1))
        services.criar_lote(segundo, usuario=escritorio)

        assert segundo.code == "LT-SFR-002"

    def test_sequencia_e_por_fazenda_nao_global(self, farm, season, escritorio):
        goiano = Farm.objects.create(name="Goiano", code="GOI")
        services.criar_lote(
            Lot(farm=farm, season=season, entry_date=datetime.date(2025, 9, 18)),
            usuario=escritorio,
        )
        do_goiano = Lot(
            farm=goiano, season=season, entry_date=datetime.date(2025, 9, 18)
        )
        services.criar_lote(do_goiano, usuario=escritorio)

        assert do_goiano.code == "LT-GOI-001"


class TestTelasDeCadastro:
    def test_criar_lote_pela_tela_gera_codigo(self, client, farm, season, escritorio):
        client.force_login(escritorio)
        response = client.post(
            reverse("livestock:lote_novo"),
            {
                "farm": farm.pk,
                "season": season.pk,
                "entry_date": "2025-09-18",
            },
        )
        assert response.status_code == 302
        assert Lot.objects.filter(farm=farm, code="LT-SFR-001").exists()

    def test_lista_de_lotes_e_escopada(self, client, farm, season):
        goiano = Farm.objects.create(name="Goiano", code="GOI")
        campo = User.objects.create_user(
            username="campo", password="x", role=Role.CAMPO
        )
        UserFarmAccess.objects.create(user=campo, farm=farm)

        services.criar_lote(
            Lot(farm=farm, season=season, entry_date=datetime.date(2025, 9, 18)),
            usuario=campo,
        )
        services.criar_lote(
            Lot(farm=goiano, season=season, entry_date=datetime.date(2025, 9, 18)),
            usuario=campo,
        )

        client.force_login(campo)
        response = client.get(reverse("livestock:lote_lista"))
        conteudo = response.content.decode("utf-8")

        assert "LT-SFR-001" in conteudo
        assert "LT-GOI-001" not in conteudo
