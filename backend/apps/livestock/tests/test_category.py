"""F1-04: as 11 categorias na ordem da planilha, e a sugestão de evolução
por idade — ver docs/roadmap/fase-1-cadastros-e-rebanho.md#f1-04."""

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.livestock.models import AnimalCategory, Sex
from apps.livestock.selectors import listar_categorias, sugerir_proxima_categoria

pytestmark = pytest.mark.django_db


@pytest.fixture
def gestor():
    return User.objects.create_user(username="gestor", password="x", role=Role.GESTOR)


class TestOrdemDasCategorias:
    def test_as_11_aparecem_na_ordem_da_planilha(self):
        call_command("seed_demo")

        nomes = list(listar_categorias().values_list("name", flat=True))

        assert len(nomes) == 11
        assert nomes[0] == "Bezerros Mamando"
        assert nomes[-1] == "Tropa"


class TestSugestaoDeEvolucao:
    def test_machos_desmamados_evolui_para_machos_13_a_24(self):
        call_command("seed_demo")

        origem = AnimalCategory.objects.get(name="Machos Desm. até 12m")
        sugerida = sugerir_proxima_categoria(origem)

        assert sugerida.name == "Machos 13 a 24 meses"

    def test_categoria_sem_ordem_etaria_nao_tem_sugestao(self):
        call_command("seed_demo")

        tropa = AnimalCategory.objects.get(name="Tropa")
        assert sugerir_proxima_categoria(tropa) is None

    def test_categoria_de_topo_nao_tem_sugestao(self):
        call_command("seed_demo")

        touros = AnimalCategory.objects.get(name="Touros")
        assert sugerir_proxima_categoria(touros) is None

    def test_sugestao_nunca_atravessa_sexo(self):
        """Macho nunca sugere evoluir para categoria de fêmea."""
        call_command("seed_demo")

        machos_13_24 = AnimalCategory.objects.get(name="Machos 13 a 24 meses")
        sugerida = sugerir_proxima_categoria(machos_13_24)

        assert sugerida.sex == Sex.MACHO

    def test_endpoint_devolve_sugestao_sem_aplicar_nada(self, client, gestor):
        call_command("seed_demo")
        origem = AnimalCategory.objects.get(name="Machos Desm. até 12m")

        client.force_login(gestor)
        response = client.get(
            reverse("livestock:categoria_sugestao_evolucao", args=[origem.pk])
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Machos 13 a 24 meses"


class TestTelasDeCadastro:
    def test_lista_de_categorias_exige_permissao(self, client):
        consulta = User.objects.create_user(
            username="consulta", password="x", role=Role.CONSULTA
        )
        client.force_login(consulta)
        response = client.get(reverse("livestock:categoria_lista"))
        assert response.status_code == 403

    def test_gestor_cadastra_raca_pela_tela(self, client, gestor):
        client.force_login(gestor)
        response = client.post(
            reverse("livestock:raca_nova"), {"name": "Angus", "is_active": "on"}
        )
        assert response.status_code == 302
        from apps.livestock.models import Breed

        assert Breed.objects.filter(name="Angus").exists()
