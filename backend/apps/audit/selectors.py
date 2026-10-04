"""Consultas do console de auditoria. Leitura, nunca escrita."""

import datetime

from django.apps import apps as django_apps
from django.core.cache import cache
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.audit.models import AuditEvent


def filter_events(
    *,
    user_id: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    date_from=None,
    date_to=None,
    ip_address: str | None = None,
) -> QuerySet[AuditEvent]:
    qs = AuditEvent.objects.select_related("actor").all()
    if user_id:
        qs = qs.filter(actor_id=user_id)
    if action:
        qs = qs.filter(action=action)
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    # Faixa de instantes, não `timestamp__date`: converter a coluna para data
    # impede o banco de usar o índice de `timestamp` e varre a tabela inteira.
    # O dia vai de 00:00 do dia inicial a 00:00 do dia seguinte ao final, no
    # fuso do sistema — o mesmo recorte que `__date` fazia.
    inicio = _inicio_do_dia(date_from)
    if inicio is not None:
        qs = qs.filter(timestamp__gte=inicio)
    fim = _inicio_do_dia(date_to, dias_depois=1)
    if fim is not None:
        qs = qs.filter(timestamp__lt=fim)
    if ip_address:
        qs = qs.filter(ip_address=ip_address)
    return qs


def _inicio_do_dia(valor, *, dias_depois: int = 0):
    """00:00 do dia (no fuso do sistema), `dias_depois` dias adiante. Aceita
    `date` ou texto `AAAA-MM-DD`; vazio ou inválido não filtra."""
    if not valor:
        return None
    dia = valor if isinstance(valor, datetime.date) else parse_date(str(valor))
    if dia is None:
        return None
    dia += datetime.timedelta(days=dias_depois)
    return timezone.make_aware(datetime.datetime.combine(dia, datetime.time.min))


def timeline_for(entity_type: str, entity_id: str) -> QuerySet[AuditEvent]:
    """Tudo que já aconteceu com um registro específico."""
    return AuditEvent.objects.filter(
        entity_type=entity_type, entity_id=str(entity_id)
    ).order_by("timestamp")


def distinct_entity_types() -> list[str]:
    """Os tipos que já aparecem na auditoria, para o filtro do console. A tabela
    só cresce e o `DISTINCT` a percorre inteira: o resultado fica 10 minutos em
    cache (é uma lista de opções de filtro, não um indicador)."""
    return cache.get_or_set(
        "audit:entity_types",
        lambda: sorted(
            AuditEvent.objects.order_by()
            .values_list("entity_type", flat=True)
            .distinct()
        ),
        600,
    )


def resolve_model(entity_type: str):
    """Acha a classe de modelo cujo nome é `entity_type`, em qualquer app.

    Usado para restaurar a partir do console sem o console precisar saber
    de antemão de cada modelo transacional do sistema.
    """
    for model in django_apps.get_models():
        if model.__name__ == entity_type:
            return model
    return None
