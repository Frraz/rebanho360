"""F0-03: `prod.py` recusa subir em configuração insegura — com mensagem
clara, não stack trace genérico."""

import importlib
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured


def _reimport_prod_settings(monkeypatch, **env):
    for key in (
        "DJANGO_SECRET_KEY",
        "DJANGO_DEBUG",
        "DJANGO_ALLOWED_HOSTS",
        "DATABASE_URL",
        "REDIS_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("config.settings.prod", None)
    sys.modules.pop("config.settings.base", None)
    return importlib.import_module("config.settings.prod")


class TestProdRecusaSubirInseguro:
    def test_sem_secret_key_recusa_subir(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
            _reimport_prod_settings(
                monkeypatch,
                DJANGO_ALLOWED_HOSTS="rebanho360.exemplo.com",
                DATABASE_URL="postgres://u:p@localhost:5432/d",
            )

    def test_com_debug_true_recusa_subir(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="DEBUG"):
            _reimport_prod_settings(
                monkeypatch,
                DJANGO_SECRET_KEY="x" * 50,
                DJANGO_DEBUG="True",
                DJANGO_ALLOWED_HOSTS="rebanho360.exemplo.com",
                DATABASE_URL="postgres://u:p@localhost:5432/d",
            )

    def test_allowed_hosts_com_asterisco_recusa_subir(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="ALLOWED_HOSTS"):
            _reimport_prod_settings(
                monkeypatch,
                DJANGO_SECRET_KEY="x" * 50,
                DJANGO_ALLOWED_HOSTS="*",
                DATABASE_URL="postgres://u:p@localhost:5432/d",
            )

    def test_configuracao_valida_sobe(self, monkeypatch):
        settings = _reimport_prod_settings(
            monkeypatch,
            DJANGO_SECRET_KEY="x" * 50,
            DJANGO_ALLOWED_HOSTS="rebanho360.exemplo.com",
            DATABASE_URL="postgres://u:p@localhost:5432/d",
        )
        assert settings.DEBUG is False
        assert settings.ALLOWED_HOSTS == ["rebanho360.exemplo.com"]
