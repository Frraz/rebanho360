"""F0-09: dois eventos gerados na mesma requisição compartilham `request_id`."""

import pytest
from django.test import RequestFactory

from apps.accounts.models import Role, User
from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import request_context
from apps.core.middleware import RequestContextMiddleware

pytestmark = pytest.mark.django_db


def test_dois_eventos_na_mesma_requisicao_compartilham_request_id():
    eventos = []

    def get_response(request):
        eventos.append(
            registrar_auditoria(
                action=AuditAction.CREATE, entity_type="X", entity_id="1"
            )
        )
        eventos.append(
            registrar_auditoria(
                action=AuditAction.UPDATE, entity_type="X", entity_id="1"
            )
        )
        return _FakeResponse()

    middleware = RequestContextMiddleware(get_response)
    request = RequestFactory().get("/qualquer/")
    request.user = User.objects.create_user(
        username="joao", password="x", role=Role.CAMPO
    )

    middleware(request)

    assert len(eventos) == 2
    assert eventos[0].request_id == eventos[1].request_id
    assert eventos[0].request_id is not None
    assert eventos[0].actor == request.user


def test_contexto_e_limpo_apos_a_requisicao():
    middleware = RequestContextMiddleware(lambda req: _FakeResponse())
    request = RequestFactory().get("/qualquer/")
    request.user = User.objects.create_user(
        username="maria", password="x", role=Role.CAMPO
    )

    middleware(request)

    assert request_context.get_current().request_id is None


class _FakeResponse(dict):
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
