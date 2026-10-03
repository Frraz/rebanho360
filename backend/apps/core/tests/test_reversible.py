import threading

import pytest
from django.db import connection

from apps.accounts.models import Role, User
from apps.audit.models import AuditEvent
from apps.core import request_context, reversible
from apps.core.exceptions import BlockingDependencyError, BusinessError, DependencyError
from apps.core.models import CounterTestModel, DependentTestModel, ReversibleTestModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario():
    return User.objects.create_user(username="maria", password="x", role=Role.GESTOR)


@pytest.fixture
def confirmado(usuario):
    counter = CounterTestModel.objects.create(total=0)
    registro = ReversibleTestModel.objects.create(
        counter=counter, amount=126, created_by=usuario
    )
    reversible.confirmar(registro, usuario=usuario)
    registro.refresh_from_db()
    return registro


class TestEditar:
    def test_editar_confirmado_corrige_efeito(self, confirmado, usuario):
        reversible.editar(
            confirmado,
            {"amount": 120},
            usuario=usuario,
            motivo="Contagem corrigida no curral",
        )
        confirmado.counter.refresh_from_db()
        assert confirmado.counter.total == 120  # não 126 + 120

    def test_editar_sem_motivo_e_recusada(self, confirmado, usuario):
        with pytest.raises(BusinessError):
            reversible.editar(confirmado, {"amount": 120}, usuario=usuario, motivo="")

    def test_editar_gera_audit_event_com_before_after_reason(self, confirmado, usuario):
        reversible.editar(
            confirmado, {"amount": 120}, usuario=usuario, motivo="Contagem corrigida"
        )
        evento = AuditEvent.objects.filter(
            entity_type="ReversibleTestModel",
            entity_id=str(confirmado.pk),
            action="UPDATE",
        ).latest("timestamp")
        assert evento.before["amount"] == 126
        assert evento.after["amount"] == 120
        assert evento.reason == "Contagem corrigida"
        assert "amount" in evento.changed_fields


class TestExcluir:
    def test_excluir_desfaz_efeito(self, confirmado, usuario):
        reversible.excluir(confirmado, usuario=usuario, motivo="Duplicada")
        confirmado.counter.refresh_from_db()
        assert confirmado.counter.total == 0

    def test_excluir_com_dependente_sem_cascata_e_recusado(self, confirmado, usuario):
        DependentTestModel.objects.create(
            parent=confirmado,
            counter=confirmado.counter,
            amount=10,
            status="CONFIRMADA",
            created_by=usuario,
        )
        with pytest.raises(DependencyError) as exc:
            reversible.excluir(confirmado, usuario=usuario, motivo="Duplicada")
        assert len(exc.value.dependents) == 1

    def test_exclusao_em_cascata_desfaz_tudo(self, confirmado, usuario):
        dep = DependentTestModel.objects.create(
            parent=confirmado,
            counter=confirmado.counter,
            amount=10,
            created_by=usuario,
        )
        reversible.confirmar(dep, usuario=usuario)
        confirmado.counter.refresh_from_db()
        assert confirmado.counter.total == 136

        reversible.excluir(
            confirmado, usuario=usuario, motivo="Duplicada", cascata=True
        )
        confirmado.counter.refresh_from_db()
        assert confirmado.counter.total == 0

    def test_falha_no_meio_da_cascata_nao_deixa_residuo(self, confirmado, usuario):
        dep = DependentTestModel.objects.create(
            parent=confirmado,
            counter=confirmado.counter,
            amount=10,
            created_by=usuario,
        )
        reversible.confirmar(dep, usuario=usuario)
        confirmado.fails_on_undo = True
        confirmado.save(update_fields=["fails_on_undo"])
        confirmado.counter.refresh_from_db()
        total_antes = confirmado.counter.total

        with pytest.raises(RuntimeError):
            reversible.excluir(
                confirmado, usuario=usuario, motivo="Duplicada", cascata=True
            )

        confirmado.refresh_from_db()
        dep.refresh_from_db()
        confirmado.counter.refresh_from_db()
        assert confirmado.status == "CONFIRMADA"
        assert dep.status == "CONFIRMADA"
        assert confirmado.counter.total == total_antes

    def test_excluir_registro_bloqueado_e_recusado_com_explicacao(
        self, confirmado, usuario
    ):
        confirmado.blocked = True
        confirmado.save(update_fields=["blocked"])
        with pytest.raises(BlockingDependencyError):
            reversible.excluir(confirmado, usuario=usuario, motivo="Duplicada")

    def test_segunda_exclusao_do_mesmo_registro_recebe_erro_claro(
        self, confirmado, usuario
    ):
        reversible.excluir(confirmado, usuario=usuario, motivo="Duplicada")
        with pytest.raises(BusinessError, match="já foi excluído"):
            reversible.excluir(confirmado, usuario=usuario, motivo="De novo")


class TestRestaurar:
    def test_restaurar_reaplica_efeitos_originais(self, confirmado, usuario):
        reversible.excluir(confirmado, usuario=usuario, motivo="Duplicada")
        reversible.restaurar(confirmado, usuario=usuario)
        confirmado.counter.refresh_from_db()
        assert confirmado.counter.total == 126
        confirmado.refresh_from_db()
        assert confirmado.status == "CONFIRMADA"


class TestCascataCompartilhaRaizERequestId:
    def test_eventos_da_cascata_compartilham_cascade_root_e_request_id(
        self, confirmado, usuario
    ):
        dep = DependentTestModel.objects.create(
            parent=confirmado,
            counter=confirmado.counter,
            amount=10,
            status="CONFIRMADA",
            created_by=usuario,
        )
        reversible.confirmar(dep, usuario=usuario)

        with request_context.use_context(
            actor=usuario, request_id="11111111-1111-1111-1111-111111111111"
        ):
            reversible.excluir(
                confirmado, usuario=usuario, motivo="Duplicada", cascata=True
            )

        eventos = AuditEvent.objects.filter(action="DELETE").order_by("id")
        assert eventos.count() == 2
        raizes = {e.cascade_root for e in eventos}
        assert len(raizes) == 1
        request_ids = {e.request_id for e in eventos}
        assert len(request_ids) == 1


class TestImutabilidadeDoAuditEvent:
    def test_nao_existe_update_de_evento_gravado(self, confirmado, usuario):
        evento = AuditEvent.objects.filter(entity_id=str(confirmado.pk)).first()
        evento.reason = "tentando alterar"
        with pytest.raises(PermissionError):
            evento.save()

    def test_nao_existe_delete_de_evento(self, confirmado):
        evento = AuditEvent.objects.filter(entity_id=str(confirmado.pk)).first()
        with pytest.raises(PermissionError):
            evento.delete()

    def test_nao_existe_update_delete_em_massa(self):
        with pytest.raises(PermissionError):
            AuditEvent.objects.all().update(reason="x")
        with pytest.raises(PermissionError):
            AuditEvent.objects.all().delete()


class TestPermissaoDeExclusao:
    def test_usuario_sem_permissao_nao_exclui_confirmado(self):
        from apps.core.permissions import pode_excluir_confirmado

        campo = User.objects.create_user(username="joao", password="x", role=Role.CAMPO)
        assert pode_excluir_confirmado(campo) is False

        gestor = User.objects.create_user(
            username="ana", password="x", role=Role.GESTOR
        )
        assert pode_excluir_confirmado(gestor) is True


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason=(
        "select_for_update() em SQLite não bloqueia entre conexões/threads "
        "do jeito que faz no Postgres (motor real de produção e dev) — "
        "validar este teste via docker compose."
    ),
)
@pytest.mark.django_db(transaction=True)
def test_duas_exclusoes_concorrentes_uma_vence_a_outra_recebe_erro_claro():
    usuario = User.objects.create_user(
        username="concorrente", password="x", role=Role.GESTOR
    )
    counter = CounterTestModel.objects.create(total=0)
    registro = ReversibleTestModel.objects.create(
        counter=counter, amount=50, created_by=usuario
    )
    reversible.confirmar(registro, usuario=usuario)

    resultados = []
    barreira = threading.Barrier(2)

    def tentar_excluir():
        barreira.wait()
        try:
            reversible.excluir(registro, usuario=usuario, motivo="Concorrência")
            resultados.append("ok")
        except BusinessError:
            resultados.append("erro")
        finally:
            connection.close()

    t1 = threading.Thread(target=tentar_excluir)
    t2 = threading.Thread(target=tentar_excluir)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(resultados) == ["erro", "ok"]
    counter.refresh_from_db()
    assert counter.total == 0
