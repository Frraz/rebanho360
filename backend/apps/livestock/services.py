"""Escrita. Toda operação que altera estado passa por aqui."""

from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.serialization import diff_fields, snapshot
from apps.livestock.models import Lot


@transaction.atomic
def salvar_cadastro(instancia, *, usuario, criando: bool):
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


def gerar_codigo_lote(farm) -> str:
    """`LT-{código da fazenda}-{sequência de 3 dígitos}` — sequência por
    fazenda, como na planilha (`LT-SFR-004`, `LT-SFR-014`, ...)."""
    prefixo = f"LT-{farm.code}-"
    existentes = Lot.objects.filter(code__startswith=prefixo).count()
    return f"{prefixo}{existentes + 1:03d}"


@transaction.atomic
def criar_lote(lot: Lot, *, usuario) -> Lot:
    lot.code = gerar_codigo_lote(lot.farm)
    lot.save()
    registrar_auditoria(
        action=AuditAction.CREATE, entity=lot, after=snapshot(lot), actor=usuario
    )
    return lot


@transaction.atomic
def editar_lote(lot: Lot, *, usuario) -> Lot:
    antes = snapshot(Lot.objects.get(pk=lot.pk))
    lot.save()
    depois = snapshot(lot)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=lot,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        actor=usuario,
    )
    return lot
