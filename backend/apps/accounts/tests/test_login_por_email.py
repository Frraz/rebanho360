"""Login por usuário ou e-mail (cliente, 2026-10-03, #31)."""

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def maria():
    return User.objects.create_user(
        username="maria",
        password="senha-da-maria-1",
        email="Maria@Exemplo.com",
        role=Role.CAMPO,
    )


def _entrar(client, usuario, senha="senha-da-maria-1"):
    return client.post(
        reverse("accounts:login"), {"username": usuario, "password": senha}
    )


def test_entra_pelo_usuario(client, maria):
    assert _entrar(client, "maria").status_code == 302
    assert client.session["_auth_user_id"] == str(maria.pk)


def test_entra_pelo_email_sem_diferenciar_maiusculas(client, maria):
    assert _entrar(client, "maria@exemplo.com").status_code == 302
    assert client.session["_auth_user_id"] == str(maria.pk)


def test_senha_errada_pelo_email_nao_entra(client, maria):
    assert _entrar(client, "maria@exemplo.com", "errada").status_code == 200
    assert "_auth_user_id" not in client.session


def test_email_inexistente_nao_entra(client, maria):
    assert _entrar(client, "ninguem@exemplo.com").status_code == 200
    assert "_auth_user_id" not in client.session


def test_conta_excluida_nao_entra_pelo_email(client, maria):
    from django.utils import timezone

    maria.deleted_at = timezone.now()
    maria.is_active = False
    maria.save()
    assert _entrar(client, "maria@exemplo.com").status_code == 200
    assert "_auth_user_id" not in client.session
