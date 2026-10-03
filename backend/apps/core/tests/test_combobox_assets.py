"""O seletor com busca (static/js/combobox.js) é melhoria progressiva: estes
testes só garantem que ele chega à página e que o cabeçalho não o atrapalha."""

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User


@pytest.fixture
def gestor(db):
    return User.objects.create_user(
        username="gestor1", password="x-senha-123456", role=Role.GESTOR
    )


@pytest.mark.django_db
def test_pagina_autenticada_carrega_o_seletor_com_o_sprite(client, gestor):
    client.force_login(gestor)
    html = client.get(reverse("dashboards:inicio")).content.decode()
    assert "js/combobox.js" in html
    assert 'data-icons="' in html and "img/icons.svg" in html


@pytest.mark.django_db
def test_contexto_nao_usa_label_em_volta_do_select(client, gestor):
    # Clicar num <label> cai no <select> escondido; o rótulo é um <span> ligado por aria.
    client.force_login(gestor)
    html = client.get(reverse("dashboards:inicio")).content.decode()
    assert 'class="ctx-bar' in html
    assert 'class="ctx"' not in html
    assert 'aria-labelledby="ctx-safra-d"' in html or "Nenhuma cadastrada" in html


@pytest.mark.django_db
def test_menu_do_avatar_so_tem_conta_e_sair(client, gestor):
    client.force_login(gestor)
    html = client.get(reverse("dashboards:inicio")).content.decode()
    assert reverse("accounts:conta") in html
    assert "Alterar senha" not in html
    assert "Segundo fator" not in html
