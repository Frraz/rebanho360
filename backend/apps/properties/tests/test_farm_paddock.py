"""F1-02: CRUD de Fazenda e Pasto, e o `ScopedManager` filtrando contra o
modelo real (não mais o `ScopeTestModel` sintético da F0-06) — ver
docs/roadmap/fase-1-cadastros-e-rebanho.md#f1-02."""

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User, UserFarmAccess
from apps.audit.models import AuditEvent
from apps.properties.models import Farm, Paddock, PaddockType

pytestmark = pytest.mark.django_db


@pytest.fixture
def farms():
    return (
        Farm.objects.create(name="Baixão", code="BXO"),
        Farm.objects.create(name="Goiano", code="GOI"),
    )


@pytest.fixture
def campo_baixao(farms):
    baixao, _goiano = farms
    user = User.objects.create_user(username="campo", password="x", role=Role.CAMPO)
    UserFarmAccess.objects.create(user=user, farm=baixao)
    return user


@pytest.fixture
def gestor():
    return User.objects.create_user(username="gestor", password="x", role=Role.GESTOR)


class TestScopedManagerContraFarmReal:
    def test_paddock_scoped_manager_filtra_fazenda_de_verdade(
        self, farms, campo_baixao
    ):
        baixao, goiano = farms
        Paddock.objects.create(farm=baixao, name="Pasto 1", type=PaddockType.PASTAGEM)
        Paddock.objects.create(farm=goiano, name="Pasto 2", type=PaddockType.PASTAGEM)

        visiveis = Paddock.objects.for_user(campo_baixao)

        assert list(visiveis.values_list("name", flat=True)) == ["Pasto 1"]

    def test_gestor_ve_pastos_de_todas_as_fazendas(self, farms, gestor):
        baixao, goiano = farms
        Paddock.objects.create(farm=baixao, name="Pasto 1", type=PaddockType.PASTAGEM)
        Paddock.objects.create(farm=goiano, name="Pasto 2", type=PaddockType.PASTAGEM)

        assert Paddock.objects.for_user(gestor).count() == 2


class TestTelasDeCadastro:
    def test_lista_de_fazendas_exige_permissao(self, client, farms):
        consulta = User.objects.create_user(
            username="consulta", password="x", role=Role.CONSULTA
        )
        client.force_login(consulta)
        response = client.get(reverse("properties:fazenda_lista"))
        assert response.status_code == 403

    def test_gestor_cadastra_fazenda_pela_tela(self, client, gestor):
        client.force_login(gestor)
        response = client.post(
            reverse("properties:fazenda_nova"),
            {"name": "Morada do Boi", "code": "MDB", "is_active": "on"},
        )
        assert response.status_code == 302
        assert Farm.objects.filter(code="MDB").exists()
        assert AuditEvent.objects.filter(entity_type="Farm", action="CREATE").exists()

    def test_gestor_cadastra_pasto_pela_tela(self, client, gestor, farms):
        baixao, _goiano = farms
        client.force_login(gestor)
        response = client.post(
            reverse("properties:pasto_novo"),
            {
                "farm": baixao.pk,
                "name": "Pasto do curral",
                "type": PaddockType.PASTAGEM,
                "is_active": "on",
            },
        )
        assert response.status_code == 302
        assert Paddock.objects.filter(name="Pasto do curral", farm=baixao).exists()

    def test_lista_de_pastos_e_escopada_por_usuario(self, client, farms, campo_baixao):
        baixao, goiano = farms
        Paddock.objects.create(
            farm=baixao, name="Pasto do Baixão", type=PaddockType.PASTAGEM
        )
        Paddock.objects.create(
            farm=goiano, name="Pasto do Goiano", type=PaddockType.PASTAGEM
        )

        client.force_login(campo_baixao)
        response = client.get(reverse("properties:pasto_lista"))
        conteudo = response.content.decode("utf-8")

        assert "Pasto do Baixão" in conteudo
        assert "Pasto do Goiano" not in conteudo


class TestContextoDeFazenda:
    def test_trocar_fazenda_persiste_na_sessao(self, client, farms, campo_baixao):
        baixao, _goiano = farms
        client.force_login(campo_baixao)

        client.post(
            reverse("properties:trocar_fazenda"), {"farm_id": baixao.pk, "next": "/"}
        )

        assert client.session["ctx_farm_id"] == baixao.pk

    def test_nao_e_possivel_selecionar_fazenda_fora_do_escopo_via_contexto(
        self, client, farms, campo_baixao
    ):
        _baixao, goiano = farms
        client.force_login(campo_baixao)

        client.post(
            reverse("properties:trocar_fazenda"), {"farm_id": goiano.pk, "next": "/"}
        )

        assert client.session.get("ctx_farm_id") is None
