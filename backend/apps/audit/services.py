"""Gravação de auditoria. Único ponto de escrita de `AuditEvent`.

Chamado de dentro da mesma transação da ação que ele registra — auditoria
que falha e deixa o dado passar é pior que não ter auditoria.
"""

import uuid

from apps.audit.models import AuditAction, AuditEvent, OperationEvent
from apps.core import request_context, result_cache

ACOES_QUE_NAO_MUDAM_DADO = frozenset(
    {
        AuditAction.LOGIN,
        AuditAction.LOGIN_FAILED,
        AuditAction.LOGOUT,
        AuditAction.EXPORT,
        AuditAction.VIEW,
    }
)


def registrar_auditoria(
    *,
    action: str,
    entity=None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    changed_fields: list[str] | None = None,
    reason: str = "",
    cascade_root: uuid.UUID | None = None,
    actor=None,
) -> AuditEvent:
    """Grava um `AuditEvent`. Nunca atualiza um existente — é um INSERT puro.

    Passe `entity` quando houver uma instância de modelo; passe
    `entity_type`/`entity_id` diretamente nos casos em que não há instância
    (ex.: falha de login, em que o usuário pode nem existir).
    """
    if entity is not None:
        entity_type = type(entity).__name__
        entity_id = str(getattr(entity, "pk", ""))

    ctx = request_context.get_current()
    # Ação que muda dado: o cache de resultados do dashboard recomeça (só depois
    # do commit; desfeita a transação, nada se invalida). Entrar, sair, tentar
    # entrar, consultar e exportar não mudam número: uma sequência de tentativas
    # de login não pode ficar esvaziando o cache de todo mundo.
    if action not in ACOES_QUE_NAO_MUDAM_DADO:
        result_cache.avancar_ao_confirmar()
    return AuditEvent.objects.create(
        actor=actor if actor is not None else ctx.actor,
        action=action,
        entity_type=entity_type or "",
        entity_id=entity_id or "",
        before=before,
        after=after,
        changed_fields=changed_fields,
        reason=reason,
        cascade_root=cascade_root,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
    )


def registrar_operacao(
    *,
    entity,
    title: str,
    description: str = "",
    previous_status: str = "",
    new_status: str = "",
    document: str = "",
    actor=None,
) -> OperationEvent:
    """Grava um `OperationEvent` — a linha do tempo que o usuário lê."""
    ctx = request_context.get_current()
    return OperationEvent.objects.create(
        actor=actor if actor is not None else ctx.actor,
        entity_type=type(entity).__name__,
        entity_id=str(getattr(entity, "pk", "")),
        title=title,
        description=description,
        previous_status=previous_status,
        new_status=new_status,
        document=document,
    )
