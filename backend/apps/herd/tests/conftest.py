import datetime

import pytest

from apps.accounts.models import Role, User, UserFarmAccess
from apps.livestock.models import AnimalCategory, Lot, Sex
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
def baixao():
    return Farm.objects.create(name="Baixão", code="BXO")


@pytest.fixture
def sao_francisco():
    return Farm.objects.create(name="São Francisco", code="SFR")


@pytest.fixture
def categoria_desmamados():
    return AnimalCategory.objects.create(
        name="Machos Desm. até 12m", sex=Sex.MACHO, age_order=2, display_order=7
    )


@pytest.fixture
def categoria_13_24(categoria_desmamados):
    return AnimalCategory.objects.create(
        name="Machos 13 a 24 meses", sex=Sex.MACHO, age_order=3, display_order=8
    )


@pytest.fixture
def lote_baixao(baixao, season):
    return Lot.objects.create(
        code="LT-BXO-001",
        farm=baixao,
        season=season,
        entry_date=datetime.date(2025, 9, 1),
    )


@pytest.fixture
def lote_sao_francisco(sao_francisco, season):
    return Lot.objects.create(
        code="LT-SFR-001",
        farm=sao_francisco,
        season=season,
        entry_date=datetime.date(2025, 9, 1),
    )


@pytest.fixture
def gestor():
    return User.objects.create_user(username="gestor", password="x", role=Role.GESTOR)


@pytest.fixture
def escritorio(baixao, sao_francisco):
    user = User.objects.create_user(
        username="escritorio", password="x", role=Role.ESCRITORIO
    )
    UserFarmAccess.objects.create(user=user, farm=baixao, can_write=True)
    UserFarmAccess.objects.create(user=user, farm=sao_francisco, can_write=True)
    return user


@pytest.fixture
def admin():
    return User.objects.create_user(username="admin", password="x", role=Role.ADMIN)


@pytest.fixture
def campo_baixao(baixao):
    user = User.objects.create_user(username="campo", password="x", role=Role.CAMPO)
    UserFarmAccess.objects.create(user=user, farm=baixao, can_write=True)
    return user
