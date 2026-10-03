"""Serialização de instâncias de modelo para `before`/`after` de auditoria."""

from decimal import Decimal


def snapshot(instance) -> dict:
    """Converte os campos concretos de uma instância em um dict serializável.

    Usado para `AuditEvent.before`/`after`. FKs viram o id relacionado;
    `Decimal` vira string (JSON não tem tipo decimal, e string preserva
    precisão — nunca `float`).
    """
    data = {}
    for field in instance._meta.concrete_fields:
        value = field.value_from_object(instance)
        if isinstance(value, Decimal):
            value = str(value)
        else:
            value = _json_safe(value)
        data[field.name] = value
    return data


def _json_safe(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def diff_fields(before: dict | None, after: dict | None) -> list[str]:
    """Lista os campos que mudaram entre dois snapshots."""
    if before is None or after is None:
        return []
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k) != after.get(k))
