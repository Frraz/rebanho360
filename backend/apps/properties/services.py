"""Escrita. Toda operação que altera estado passa por aqui."""

from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.serialization import diff_fields, snapshot


@transaction.atomic
def salvar_cadastro(instancia, *, usuario, criando: bool):
    """Salva Farm/Paddock com auditoria simples — cadastro estrutural,
    não documento com efeito a desfazer (ver apps/organizations/services.py)."""
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
