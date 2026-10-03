"""Escrita dos cadastros comerciais. Cadastro estrutural não tem efeito a
desfazer — só auditoria de quem criou e mudou o quê."""

from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.commercial.permissions import pode_gerenciar_o_comercial
from apps.core.exceptions import BusinessError
from apps.core.serialization import diff_fields, snapshot


@transaction.atomic
def salvar_cadastro(instancia, *, usuario, criando: bool):
    if not pode_gerenciar_o_comercial(usuario):
        raise BusinessError("Você não tem permissão para alterar o cadastro comercial.")
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
