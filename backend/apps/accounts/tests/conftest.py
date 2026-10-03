import pytest
from django.core.cache import cache

from apps.accounts.models import Role, User
from apps.accounts.tasks import enviar_email
from apps.properties.models import Farm


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """E-mail sai na hora (sem broker) para o `mailoutbox` enxergar; o cache
    do rate limit começa e termina vazio."""
    monkeypatch.setattr(enviar_email, "delay", enviar_email.run)
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin(db):
    return User.objects.create_user(
        username="admin1",
        password="senha-admin-123",
        role=Role.ADMIN,
        email="admin1@fazenda.com.br",
        first_name="Ana",
    )


@pytest.fixture
def outro_admin(db):
    return User.objects.create_user(
        username="admin2",
        password="senha-admin-123",
        role=Role.ADMIN,
        email="admin2@fazenda.com.br",
    )


@pytest.fixture
def cliente_admin(client, admin):
    client.force_login(admin)
    return client


@pytest.fixture
def fazenda_a(db):
    return Farm.objects.create(name="Santa Rita", code="SRT")


@pytest.fixture
def fazenda_b(db):
    return Farm.objects.create(name="Baixão", code="BXO")
