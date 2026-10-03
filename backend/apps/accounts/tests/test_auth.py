import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def limpar_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def usuario():
    return User.objects.create_user(username="maria", password="senha-correta-123")


class TestLogin:
    def test_login_com_senha_correta_funciona(self, client, usuario):
        response = client.post(
            reverse("accounts:login"),
            {"username": "maria", "password": "senha-correta-123"},
        )
        assert response.status_code == 302

    def test_usuario_inativo_nao_autentica_mesmo_com_senha_correta(
        self, client, usuario
    ):
        usuario.is_active = False
        usuario.save(update_fields=["is_active"])
        response = client.post(
            reverse("accounts:login"),
            {"username": "maria", "password": "senha-correta-123"},
        )
        assert response.status_code == 200  # form_invalid, sem redirect
        assert not response.wsgi_request.user.is_authenticated

    def test_sexta_tentativa_em_15_minutos_e_bloqueada(self, client, usuario):
        for _ in range(5):
            client.post(
                reverse("accounts:login"),
                {"username": "maria", "password": "senha-errada"},
            )
        response = client.post(
            reverse("accounts:login"),
            {"username": "maria", "password": "senha-correta-123"},
        )
        assert "Muitas tentativas" in response.content.decode()

    def test_post_sem_csrf_e_recusado(self, client, usuario):
        client.handler.enforce_csrf_checks = True
        response = client.post(
            reverse("accounts:login"),
            {"username": "maria", "password": "senha-correta-123"},
        )
        assert response.status_code == 403
