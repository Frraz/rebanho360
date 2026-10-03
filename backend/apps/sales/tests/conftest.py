import datetime
from decimal import Decimal

import pytest

from apps.costs.services import registrar_custo
from apps.costs.tests.conftest import *  # noqa: F401,F403
from apps.herd import services as herd
from apps.herd.models import MovementType
from apps.livestock.models import AnimalCategory, Lot, Sex
from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice
from apps.purchases import services as compras
from apps.sales import services

D = Decimal
DATA_ENTRADA = datetime.date(2025, 7, 10)
DATA_COMPRA = datetime.date(2025, 7, 10)
DATA_VENDA = datetime.date(2025, 8, 3)


@pytest.fixture
def categoria_25_36():
    return AnimalCategory.objects.create(
        name="Machos 25 a 36 meses", sex=Sex.MACHO, age_order=4, display_order=9
    )


@pytest.fixture
def frigorifico():
    parceiro = Partner.objects.create(name="COPERFRIGU")
    PartnerRole.objects.create(partner=parceiro, role=PartnerRoleChoice.FRIGORIFICO)
    return parceiro


@pytest.fixture
def lote_gordo(sao_francisco, season, categoria_25_36, escritorio):
    """Um lote de São Francisco com 100 cabeças de Machos 25 a 36 meses."""
    lote = Lot.objects.create(
        code="LT-SFR-010",
        farm=sao_francisco,
        season=season,
        entry_date=DATA_ENTRADA,
    )
    herd.registrar_movimento(
        type=MovementType.COMPRA,
        date=DATA_ENTRADA,
        quantity=100,
        usuario=escritorio,
        destination_farm=sao_francisco,
        destination_lot=lote,
        destination_category=categoria_25_36,
    )
    return lote


@pytest.fixture
def dados_abate(sao_francisco, lote_gordo, categoria_25_36, frigorifico):
    """O abate de agosto/2025 da planilha, que trava o `CarcassService`:
    84 cabeças, 43.540 kg vivo, 22.350,40 kg de carcaça, R$ 401.502,68."""
    return {
        "date": DATA_VENDA,
        "type": "ABATE",
        "buyer": frigorifico,
        "farm": sao_francisco,
        "lot": lote_gordo,
        "category": categoria_25_36,
        "head_count": 84,
        "total_weight_kg": D("43540"),
        "carcass_weight_kg": D("22350.40"),
        "total_value": D("401502.68"),
    }


@pytest.fixture
def criar(escritorio):
    def _criar(**dados):
        return services.criar_venda(usuario=escritorio, **dados)

    return _criar


@pytest.fixture
def confirmar(escritorio):
    def _confirmar(venda):
        return services.confirmar_venda(venda, usuario=escritorio)

    return _confirmar


@pytest.fixture
def lote_de_compra(
    escritorio, sao_francisco, categoria_25_36, vendedor, custeio, centro_funcionario
):
    compra = compras.criar_compra(
        usuario=escritorio,
        date=DATA_COMPRA,
        destination_farm=sao_francisco,
        category=categoria_25_36,
        seller=vendedor,
        head_count=100,
        animal_value=D("250000"),
        freight_value=D("5000"),
    )
    compra = compras.confirmar_compra(compra, usuario=escritorio)
    lote = compra.lot
    registrar_custo(
        date=datetime.date(2025, 7, 15),
        farm=sao_francisco,
        cost_center=centro_funcionario,
        cost_class=custeio,
        amount=D("3000"),
        description="Vacina",
        usuario=escritorio,
        lot=lote,
    )
    registrar_custo(
        date=datetime.date(2025, 7, 20),
        farm=sao_francisco,
        cost_center=centro_funcionario,
        cost_class=custeio,
        amount=D("12000"),
        description="Salário",
        usuario=escritorio,
    )
    return lote


def vender(escritorio, lote, frigorifico, categoria, **extra):
    dados = {
        "date": DATA_VENDA,
        "type": "ABATE",
        "buyer": frigorifico,
        "farm": lote.farm,
        "lot": lote,
        "category": categoria,
        "head_count": 100,
        "total_weight_kg": D("48000"),
        "carcass_weight_kg": D("24000"),
        "total_value": D("480000"),
        **extra,
    }
    venda = services.criar_venda(usuario=escritorio, **dados)
    return services.confirmar_venda(venda, usuario=escritorio)
