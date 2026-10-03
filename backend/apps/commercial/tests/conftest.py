import datetime
from decimal import Decimal

import pytest

from apps.commercial.models import CommissionRule
from apps.commercial.seed import garantir_cadastros_comerciais
from apps.costs.tests.conftest import *  # noqa: F401,F403
from apps.partners.models import Partner, PartnerRole, PartnerRoleChoice


@pytest.fixture(autouse=True)
def seed_comercial(db):
    """As classes e os tipos vêm da migração `commercial.0002`, mas um teste
    transacional esvazia as tabelas ao terminar: cada teste garante o seu."""
    garantir_cadastros_comerciais()


@pytest.fixture
def comissionado():
    parceiro = Partner.objects.create(name="Cláudia Ferreira")
    PartnerRole.objects.create(partner=parceiro, role=PartnerRoleChoice.COMISSIONADO)
    return parceiro


@pytest.fixture
def outro_comissionado():
    parceiro = Partner.objects.create(name="Romero Ferreira")
    PartnerRole.objects.create(partner=parceiro, role=PartnerRoleChoice.COMISSIONADO)
    return parceiro


@pytest.fixture
def regra_padrao(db):
    """Para qualquer comprador e categoria: 1% sobre o bruto, desde jan/2025."""
    return CommissionRule.objects.create(
        type="PERCENTUAL",
        base="BRUTO",
        value=Decimal("1"),
        valid_from=datetime.date(2025, 1, 1),
    )
