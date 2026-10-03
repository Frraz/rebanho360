"""Escrita da infraestrutura e do parque de máquinas. Cadastro audita criação e
mudança; o uso da máquina é lançamento reversível (motivo e auditoria)."""

from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import reversible
from apps.core.exceptions import BusinessError
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.serialization import diff_fields, snapshot
from apps.herd.permissions import tem_acesso_de_escrita_a_fazenda
from apps.infrastructure.models import Machine, MachineLog
from apps.infrastructure.permissions import pode_cadastrar, pode_lancar_uso


@transaction.atomic
def salvar_cadastro(instancia, *, usuario, criando: bool):
    """Estrutura ou máquina: audita quem criou e mudou o quê."""
    if not pode_cadastrar(usuario):
        raise BusinessError("Você não tem permissão para alterar este cadastro.")
    if not tem_acesso_de_escrita_a_fazenda(usuario, instancia.farm):
        raise BusinessError(
            f"Você não tem permissão de lançamento em {instancia.farm}."
        )
    antes = None if criando else snapshot(type(instancia).objects.get(pk=instancia.pk))
    instancia.save()
    depois = snapshot(instancia)
    registrar_auditoria(
        action=AuditAction.CREATE if criando else AuditAction.UPDATE,
        entity=instancia,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois) if antes else None,
        actor=usuario,
    )
    return instancia


CAMPOS_DO_USO = (
    "date",
    "hours",
    "fuel_liters",
    "fuel_cost",
    "maintenance_cost",
    "notes",
)


def _codigo(machine: Machine) -> str:
    base = f"UM-{machine.pk}-"
    return f"{base}{MachineLog.objects.filter(code__startswith=base).count() + 1:04d}"


@transaction.atomic
def registrar_uso(*, usuario, machine: Machine, **dados) -> MachineLog:
    if not pode_lancar_uso(usuario):
        raise BusinessError("Você não tem permissão para lançar uso de máquina.")
    if not tem_acesso_de_escrita_a_fazenda(usuario, machine.farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {machine.farm}.")
    if not machine.is_active:
        raise BusinessError(f"A máquina {machine} está inativa.")
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    campos = {c: dados.get(c) for c in CAMPOS_DO_USO}
    campos["notes"] = campos.get("notes") or ""
    _validar_uso(campos)
    uso = MachineLog(
        machine=machine, created_by=usuario, code=_codigo(machine), **campos
    )
    uso.save()
    registrar_auditoria(
        action=AuditAction.CREATE, entity=uso, after=snapshot(uso), actor=usuario
    )
    return reversible.confirmar(uso, usuario=usuario)


def _validar_uso(dados: dict) -> None:
    if not dados.get("hours") or dados["hours"] <= 0:
        raise BusinessError("Informe as horas trabalhadas (mais de zero).")
    for campo, rotulo in (
        ("fuel_liters", "o combustível (litros)"),
        ("fuel_cost", "o combustível (R$)"),
        ("maintenance_cost", "a manutenção (R$)"),
    ):
        if dados.get(campo) is not None and dados[campo] < 0:
            raise BusinessError(f"{rotulo.capitalize()} não pode ser negativo.")


@transaction.atomic
def editar_uso(uso: MachineLog, dados: dict, *, usuario, motivo: str) -> MachineLog:
    if not pode_editar_confirmado(usuario):
        raise BusinessError("Você não tem permissão para editar este lançamento.")
    novos = {c: dados.get(c, getattr(uso, c)) for c in CAMPOS_DO_USO}
    _validar_uso(novos)
    return reversible.editar(uso, novos, usuario=usuario, motivo=motivo)


@transaction.atomic
def excluir_uso(uso: MachineLog, *, usuario, motivo: str, cascata: bool = False):
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para excluir este lançamento.")
    return reversible.excluir(uso, usuario=usuario, motivo=motivo, cascata=cascata)


@transaction.atomic
def restaurar_uso(uso: MachineLog, *, usuario) -> MachineLog:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para restaurar este lançamento.")
    if uso.status != Status.EXCLUIDA:
        raise BusinessError("Só é possível restaurar um lançamento excluído.")
    return reversible.restaurar(uso, usuario=usuario)
