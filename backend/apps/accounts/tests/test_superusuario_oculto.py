"""O superusuário de suporte: acesso total e invisível para os demais."""

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts import selectors
from apps.accounts.models import Role, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def suporte(db, monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "senha-do-suporte-123")
    call_command("criar_superusuario_oculto", "obs_oculto", "--noinput")
    return User.objects.get(username="obs_oculto")


def test_comando_cria_admin_com_acesso_amplo(suporte):
    assert suporte.is_superuser and suporte.is_staff
    assert suporte.role == Role.ADMIN
    assert suporte.has_broad_access
    assert str(suporte) == "Suporte Técnico"


def test_superusuario_enxerga_todas_as_fazendas_mesmo_sem_papel_amplo(db):
    root = User.objects.create_superuser(username="root", password="s")
    assert root.role == Role.CONSULTA
    assert root.has_broad_access


def test_nao_aparece_na_lista_dos_outros(cliente_admin, suporte):
    html = cliente_admin.get(reverse("accounts:usuarios") + "?estado=todos").content
    assert b"obs_oculto" not in html
    assert b"Suporte" not in html


def test_detalhe_e_acoes_sobre_ele_dao_404_para_os_outros(cliente_admin, suporte):
    for rota in (
        "accounts:usuario_detalhe",
        "accounts:usuario_editar",
        "accounts:usuario_desativar",
        "accounts:usuario_excluir",
    ):
        url = reverse(rota, args=[suporte.pk])
        assert cliente_admin.get(url).status_code == 404
        if rota != "accounts:usuario_detalhe":  # o detalhe só aceita GET
            assert cliente_admin.post(url).status_code == 404


def test_ele_mesmo_ve_todos_inclusive_a_si(admin, suporte):
    assert set(selectors.usuarios_visiveis(suporte)) >= {admin, suporte}
    assert suporte not in selectors.usuarios_visiveis(admin)
    assert suporte not in selectors.listar_usuarios(ator=admin, estado="todos")


def test_nao_entra_no_filtro_da_auditoria(cliente_admin, suporte):
    resposta = cliente_admin.get(reverse("audit:console"))
    assert suporte not in resposta.context["usuarios"]


def test_admin_do_django_nao_lista_o_superusuario(admin, suporte, rf):
    from django.contrib.admin.sites import site

    modelo = site._registry[User]
    request = rf.get("/")
    request.user = admin
    assert suporte not in modelo.get_queryset(request)
    request.user = suporte
    assert suporte in modelo.get_queryset(request)


def test_comando_recusa_usuario_repetido_e_senha_fraca(suporte, monkeypatch):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="Já existe"):
        call_command("criar_superusuario_oculto", "obs_oculto", "--noinput")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "123")
    with pytest.raises(CommandError):
        call_command("criar_superusuario_oculto", "outro", "--noinput")
