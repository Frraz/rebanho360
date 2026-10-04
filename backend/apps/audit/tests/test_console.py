import pytest
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.audit.models import AuditAction, AuditEvent
from apps.core import reversible
from apps.core.models import CounterTestModel, ReversibleTestModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return User.objects.create_user(username="admin", password="x", role=Role.ADMIN)


@pytest.fixture
def campo():
    return User.objects.create_user(username="campo", password="x", role=Role.CAMPO)


class TestAcessoAoConsole:
    def test_admin_acessa_console(self, client, admin):
        client.force_login(admin)
        response = client.get(reverse("audit:console"))
        assert response.status_code == 200

    def test_papel_sem_permissao_recebe_403(self, client, campo):
        client.force_login(campo)
        response = client.get(reverse("audit:console"))
        assert response.status_code == 403

    def test_anonimo_e_redirecionado_para_login(self, client):
        response = client.get(reverse("audit:console"))
        assert response.status_code == 302


class TestExportacaoCsv:
    def test_exportar_csv_gera_audit_event_de_export(self, client, admin):
        client.force_login(admin)
        response = client.get(reverse("audit:export_csv"))
        assert response.status_code == 200
        assert response["Content-Type"] == "text/csv"
        assert AuditEvent.objects.filter(
            action=AuditAction.EXPORT, actor=admin
        ).exists()


class TestRestaurarPeloConsole:
    def test_restaurar_a_partir_do_evento_reaplica_o_efeito(self, client, admin):
        counter = CounterTestModel.objects.create(total=0)
        registro = ReversibleTestModel.objects.create(
            counter=counter, amount=126, created_by=admin
        )
        reversible.confirmar(registro, usuario=admin)
        reversible.excluir(registro, usuario=admin, motivo="Duplicada")
        counter.refresh_from_db()
        assert counter.total == 0

        evento_exclusao = AuditEvent.objects.get(
            entity_type="ReversibleTestModel",
            entity_id=str(registro.pk),
            action=AuditAction.DELETE,
        )

        client.force_login(admin)
        response = client.post(
            reverse("audit:restore", args=[evento_exclusao.pk]), follow=True
        )

        assert response.status_code == 200
        registro.refresh_from_db()
        counter.refresh_from_db()
        assert registro.status == "CONFIRMADA"
        assert counter.total == 126
        assert AuditEvent.objects.filter(
            entity_type="ReversibleTestModel",
            entity_id=str(registro.pk),
            action=AuditAction.RESTORE,
        ).exists()


class TestFiltroPorData:
    """O filtro de data virou uma faixa de instantes (para usar o índice de
    `timestamp`); o recorte do dia, no fuso do sistema, tem de ser o mesmo que
    `timestamp__date` fazia: inclusive nas duas pontas."""

    def _evento(self, quando, entidade):
        from freezegun import freeze_time

        with freeze_time(quando):
            return AuditEvent.objects.create(
                action=AuditAction.CREATE, entity_type=entidade, entity_id="1"
            )

    def test_o_dia_vai_de_meia_noite_a_meia_noite_no_fuso_de_sao_paulo(self):
        import datetime

        from apps.audit import selectors

        # 02:59 UTC de 10/03 ainda é 23:59 de 09/03 em São Paulo (UTC−3).
        self._evento("2025-03-10 02:59:59+00:00", "Antes")
        self._evento("2025-03-10 03:00:00+00:00", "AbreODia")
        self._evento("2025-03-11 02:59:59+00:00", "FechaODia")
        self._evento("2025-03-11 03:00:00+00:00", "Depois")
        dia = datetime.date(2025, 3, 10)

        achados = selectors.filter_events(date_from=dia, date_to=dia)

        assert sorted(achados.values_list("entity_type", flat=True)) == [
            "AbreODia",
            "FechaODia",
        ]

    def test_aceita_o_texto_que_vem_da_tela(self):
        from apps.audit import selectors

        self._evento("2025-03-10 15:00:00+00:00", "NoDia")
        self._evento("2025-03-20 15:00:00+00:00", "Fora")

        achados = selectors.filter_events(date_from="2025-03-10", date_to="2025-03-12")

        assert list(achados.values_list("entity_type", flat=True)) == ["NoDia"]

    def test_data_invalida_nao_filtra_nem_quebra(self):
        from apps.audit import selectors

        self._evento("2025-03-10 15:00:00+00:00", "Qualquer")

        assert selectors.filter_events(date_from="lixo", date_to="").count() == 1
