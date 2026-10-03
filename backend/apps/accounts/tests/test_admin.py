"""F0-05: `createsuperuser` funciona e o papel aparece no admin."""

import pytest
from django.core.management import call_command

from apps.accounts.admin import UserAdmin
from apps.accounts.models import Role, User

pytestmark = pytest.mark.django_db


def test_createsuperuser_funciona(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_USERNAME", "root")
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "root@teste.com")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "senha-do-root-123")

    call_command("createsuperuser", "--noinput")

    root = User.objects.get(username="root")
    assert root.is_superuser is True
    assert root.is_staff is True


def test_papel_aparece_nos_fieldsets_do_admin():
    campos = {campo for _, secao in UserAdmin.fieldsets for campo in secao["fields"]}
    assert "role" in campos


def test_role_tem_as_seis_opcoes_do_negocio():
    valores = {value for value, _ in Role.choices}
    assert valores == {
        "ADMIN",
        "GESTOR",
        "ESCRITORIO",
        "CAMPO",
        "FINANCEIRO",
        "CONSULTA",
    }
