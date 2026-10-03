import datetime

import pytest

from apps.costs.models import CostCenter, CostClass
from apps.costs.seed import garantir_classes_e_centros
from apps.herd.tests.conftest import *  # noqa: F401,F403
from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice


@pytest.fixture(autouse=True)
def seed_custos(db):
    """Os centros e classes vêm da migração `costs.0004`, mas um teste
    transacional (`transaction=True`) esvazia as tabelas ao terminar —
    então cada teste garante o que precisa em vez de assumir a migração."""
    garantir_classes_e_centros()


@pytest.fixture(autouse=True)
def safra_padrao(season):
    """Todo lançamento precisa de safra que cubra a data."""
    return season


@pytest.fixture
def custeio():
    return CostClass.objects.get(name="CUSTEIO")


@pytest.fixture
def investimento():
    return CostClass.objects.get(name="INVESTIMENTO")


@pytest.fixture
def centro_funcionario():
    return CostCenter.objects.get(name="FUNCIONARIO")


@pytest.fixture
def centro_maquinas():
    return CostCenter.objects.get(name="PARQUE DE MÁQUINAS")


@pytest.fixture
def vendedor():
    parceiro = Partner.objects.create(name="Fazenda Boa Vista")
    PartnerRole.objects.create(partner=parceiro, role=PartnerRoleChoice.FORNECEDOR)
    return parceiro


@pytest.fixture
def hoje_na_safra(season):
    """Uma data de custo dentro da safra e no passado."""
    return datetime.date(2025, 9, 18)
