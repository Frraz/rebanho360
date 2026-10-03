"""Contexto da requisição corrente, via `contextvars`.

Populado pelo `RequestContextMiddleware` (F0-09). Permite que serviços
gravem auditoria sem receber `request` como parâmetro — só importam disso
o ator, o IP, o user-agent e o `request_id`.
"""

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    actor: object | None = None
    ip_address: str | None = None
    user_agent: str = ""
    request_id: uuid.UUID | None = None


_current: ContextVar[RequestContext] = ContextVar(
    "rebanho360_request_context", default=RequestContext()
)


def get_current() -> RequestContext:
    return _current.get()


def set_current(context: RequestContext) -> None:
    _current.set(context)


def reset() -> None:
    _current.set(RequestContext())


@contextmanager
def use_context(**kwargs):
    """Para tasks Celery e testes: define o contexto dentro do bloco `with`."""
    token = _current.set(RequestContext(**kwargs))
    try:
        yield
    finally:
        _current.reset(token)


def client_ip(request) -> str | None:
    """IP do cliente, considerando proxy reverso (Nginx do host)."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
