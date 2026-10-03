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
