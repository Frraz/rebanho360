"""F0-13: `/health/` e `/ready/` — sem autenticação, banco e Redis checados."""

from unittest.mock import patch

import pytest
from django.db import connections
from django.db.utils import OperationalError
from django.urls import reverse


@pytest.mark.django_db
class TestHealth:
    def test_health_responde_sem_autenticacao(self, client):
        response = client.get(reverse("health"))
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_ready_ok_quando_banco_e_redis_respondem(self, client):
        response = client.get(reverse("ready"))
        assert response.status_code == 200
        assert response.json()["checks"]["database"] == "ok"

    def test_ready_devolve_503_com_banco_fora(self, client):
        with patch.object(
            connections["default"], "cursor", side_effect=OperationalError("fora do ar")
        ):
            response = client.get(reverse("ready"))
        assert response.status_code == 503
        assert response.json()["checks"]["database"] == "erro"
