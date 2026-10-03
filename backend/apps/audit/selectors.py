"""Consultas do console de auditoria. Leitura, nunca escrita."""

from django.apps import apps as django_apps
from django.db.models import QuerySet

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
    if date_from:
        qs = qs.filter(timestamp__date__gte=date_from)
    if date_to:
        qs = qs.filter(timestamp__date__lte=date_to)
    if ip_address:
        qs = qs.filter(ip_address=ip_address)
    return qs


def timeline_for(entity_type: str, entity_id: str) -> QuerySet[AuditEvent]:
    """Tudo que já aconteceu com um registro específico."""
    return AuditEvent.objects.filter(
        entity_type=entity_type, entity_id=str(entity_id)
    ).order_by("timestamp")


def distinct_entity_types() -> list[str]:
    return list(
        AuditEvent.objects.order_by().values_list("entity_type", flat=True).distinct()
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
