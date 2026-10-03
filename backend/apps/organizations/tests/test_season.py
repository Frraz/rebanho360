"""F1-01: CRUD de Empresa/Unidade/Safra, com constraint de não-sobreposição
de safra garantida pelo banco, não só pelo formulário — ver
docs/roadmap/fase-1-cadastros-e-rebanho.md#f1-01."""

import datetime

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.audit.models import AuditEvent
from apps.organizations import services
from apps.organizations.forms import SeasonForm
from apps.organizations.models import Company, Season, SeasonStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def company():
    return Company.objects.create(name="Fazendas Reunidas")


@pytest.fixture
def season_atual(company):
    return Season.objects.create(
        company=company,
        name="2025/2026",
        start_date=datetime.date(2025, 7, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )


@pytest.fixture
def gestor(db):
    return User.objects.create_user(username="gestor", password="x", role=Role.GESTOR)


@pytest.fixture
def admin(db):
    return User.objects.create_user(username="admin", password="x", role=Role.ADMIN)


class TestSafraNaoSobrepoe:
    def test_formulario_recusa_sobreposicao(self, company, season_atual):
        form = SeasonForm(
            data={
                "company": company.pk,
                "name": "2026/2027",
                "start_date": "2026-01-01",
                "end_date": "2027-06-30",
            }
        )
        assert not form.is_valid()
        assert "sobreposto" in str(form.errors).lower()

    def test_banco_recusa_sobreposicao_mesmo_passando_pelo_formulario(
        self, company, season_atual
    ):
        """O DoD exige que o banco recuse, não só o formulário — aqui a
        sobreposição é inserida contornando o form/serviço, direto no ORM.

        O trigger levanta uma excepção plpgsql genérica (SQLSTATE P0001),
        que o psycopg mapeia para `ProgrammingError` — não para
        `IntegrityError` como uma constraint declarativa faria. O que
        importa para o DoD é que o banco recusa; por isso o teste usa
        `DatabaseError`, a superclasse comum às duas."""
        with pytest.raises(DatabaseError, match="[Ss]obrepost"):
            with transaction.atomic():
                Season.objects.create(
                    company=company,
                    name="2026/2027 sobreposta",
                    start_date=datetime.date(2026, 1, 1),
                    end_date=datetime.date(2027, 6, 30),
                )

    def test_safras_nao_sobrepostas_sao_aceitas(self, company, season_atual):
        nova = Season.objects.create(
            company=company,
            name="2026/2027",
            start_date=datetime.date(2026, 7, 1),
            end_date=datetime.date(2027, 6, 30),
        )
        assert nova.pk is not None

    def test_editar_a_propria_safra_nao_se_autobloqueia(self, company, season_atual):
        season_atual.end_date = datetime.date(2026, 6, 29)
        season_atual.save()  # não deve levantar, mesmo comparando com ela mesma


class TestSafraCorrenteUnica:
    def test_constraint_de_banco_impede_duas_correntes(self, company, season_atual):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Season.objects.create(
                    company=company,
                    name="2026/2027",
                    start_date=datetime.date(2026, 7, 1),
                    end_date=datetime.date(2027, 6, 30),
                    is_current=True,
                )

    def test_marcar_como_corrente_troca_sem_violar_constraint(
        self, company, season_atual, gestor
    ):
        outra = Season.objects.create(
            company=company,
            name="2026/2027",
            start_date=datetime.date(2026, 7, 1),
            end_date=datetime.date(2027, 6, 30),
        )

        services.marcar_como_corrente(outra, usuario=gestor)

        season_atual.refresh_from_db()
        outra.refresh_from_db()
        assert season_atual.is_current is False
        assert outra.is_current is True


class TestEncerrarEReabrirSafra:
    def test_encerrar_muda_status_e_audita(self, season_atual, gestor):
        services.encerrar_safra(season_atual, usuario=gestor)

        season_atual.refresh_from_db()
        assert season_atual.status == SeasonStatus.ENCERRADA
        assert AuditEvent.objects.filter(
            entity_type="Season",
            entity_id=str(season_atual.pk),
            reason="Safra encerrada",
        ).exists()

    def test_encerrar_duas_vezes_e_recusado_com_mensagem_clara(
        self, season_atual, gestor
    ):
        services.encerrar_safra(season_atual, usuario=gestor)
        with pytest.raises(Exception, match="já está encerrada"):
            services.encerrar_safra(season_atual, usuario=gestor)

    def test_view_de_reabrir_recusa_para_quem_nao_e_admin(
        self, client, season_atual, gestor
    ):
        services.encerrar_safra(season_atual, usuario=gestor)
        client.force_login(gestor)

        client.post(reverse("organizations:safra_reabrir", args=[season_atual.pk]))

        season_atual.refresh_from_db()
        assert season_atual.status == SeasonStatus.ENCERRADA

    def test_view_de_reabrir_funciona_para_admin(self, client, season_atual, admin):
        services.encerrar_safra(season_atual, usuario=admin)
        client.force_login(admin)

        client.post(reverse("organizations:safra_reabrir", args=[season_atual.pk]))

        season_atual.refresh_from_db()
        assert season_atual.status == SeasonStatus.ABERTA


class TestTelasDeCadastro:
    def test_lista_de_safras_exige_permissao(self, client, company, season_atual):
        consulta = User.objects.create_user(
            username="consulta", password="x", role=Role.CONSULTA
        )
        client.force_login(consulta)
        response = client.get(reverse("organizations:safra_lista"))
        assert response.status_code == 403

    def test_gestor_cria_safra_pela_tela(self, client, company, gestor):
        client.force_login(gestor)
        response = client.post(
            reverse("organizations:safra_nova"),
            {
                "company": company.pk,
                "name": "2025/2026",
                "start_date": "2025-07-01",
                "end_date": "2026-06-30",
            },
        )
        assert response.status_code == 302
        assert Season.objects.filter(name="2025/2026").exists()
        assert AuditEvent.objects.filter(entity_type="Season", action="CREATE").exists()

    def test_trocar_safra_persiste_na_sessao(self, client, company, gestor):
        outra = Season.objects.create(
            company=company,
            name="2024/2025",
            start_date=datetime.date(2024, 7, 1),
            end_date=datetime.date(2025, 6, 30),
        )
        client.force_login(gestor)

        client.post(
            reverse("organizations:trocar_safra"),
            {"season_id": outra.pk, "next": "/"},
        )

        assert client.session["ctx_season_id"] == outra.pk


def test_trigger_acusa_sobreposicao_mesmo_via_sql_direto(company, season_atual):
    """Camada mais baixa possível: SQL cru, contornando o ORM inteiro."""
    with pytest.raises(Exception, match="[Ss]obrepost"):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO organizations_season "
                    "(company_id, name, start_date, end_date, status, is_current) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [company.pk, "direto", "2026-01-01", "2026-12-31", "ABERTA", False],
                )
