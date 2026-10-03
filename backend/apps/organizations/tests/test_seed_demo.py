import pytest
from django.core.management import call_command

from apps.accounts.models import Role, User
from apps.costs.models import CostCenter
from apps.livestock.models import AnimalCategory
from apps.organizations.models import Season
from apps.properties.models import Farm

pytestmark = pytest.mark.django_db


class TestSeedDemo:
    def test_roda_em_banco_limpo_e_cria_os_dados_esperados(self):
        call_command("seed_demo")

        assert Farm.objects.count() == 6
        assert AnimalCategory.objects.count() == 11
        assert CostCenter.objects.count() == 12  # os 11 da planilha + FRETE
        assert Season.objects.filter(is_current=True).count() == 1
        assert User.objects.filter(role=Role.CAMPO).exists()

    def test_campo_teste_enxerga_so_uma_fazenda(self):
        call_command("seed_demo")

        campo = User.objects.get(username="campo@teste")
        assert list(campo.accessible_farms().values_list("code", flat=True)) == ["BXO"]

    def test_e_idempotente(self):
        call_command("seed_demo")
        call_command("seed_demo")

        assert Farm.objects.count() == 6
        assert User.objects.filter(username="admin@teste").count() == 1
