"""Tema claro/escuro: preferência de cada usuário, escolhida na página Conta."""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from apps.accounts.models import Role, User

SENHA = "senha-antiga-9182"


@pytest.fixture
def gestor(db):
    return User.objects.create_user(
        username="gestor1", password=SENHA, role=Role.GESTOR, email="g1@fazenda.com.br"
    )


@pytest.fixture
def cliente(client, gestor):
    client.force_login(gestor)
    return client


def _tema_do_html(resposta) -> str:
    html = resposta.content.decode()
    inicio = html.index('data-theme="') + len('data-theme="')
    return html[inicio : html.index('"', inicio)]


class TestPadrao:
    def test_quem_nunca_escolheu_fica_no_claro(self, cliente, gestor):
        assert gestor.theme == "light"
        assert _tema_do_html(cliente.get(reverse("accounts:conta"))) == "light"

    def test_a_conta_oferece_os_dois_temas_e_o_botao_de_salvar(self, cliente):
        html = cliente.get(reverse("accounts:conta")).content.decode()
        assert 'id="aparencia"' in html
        assert 'name="tema" value="light"' in html
        assert 'name="tema" value="dark"' in html
        assert "Salvar aparência" in html

    def test_a_escolha_nao_aparece_fora_da_conta(self, cliente):
        """O tema mora só na página Conta: nada de alternador no cabeçalho."""
        for nome in ("dashboards:inicio", "livestock:lote_lista"):
            html = cliente.get(reverse(nome)).content.decode()
            assert 'name="tema"' not in html
            assert reverse("accounts:tema") not in html


class TestEscolha:
    def test_escolher_o_escuro_grava_no_usuario_e_vale_na_proxima_tela(
        self, cliente, gestor
    ):
        resposta = cliente.post(reverse("accounts:tema"), {"tema": "dark"})
        assert resposta.status_code == 302
        assert resposta["Location"].endswith(reverse("accounts:conta") + "#aparencia")
        gestor.refresh_from_db()
        assert gestor.theme == "dark"
        assert _tema_do_html(cliente.get(reverse("accounts:conta"))) == "dark"
        assert _tema_do_html(cliente.get(reverse("dashboards:inicio"))) == "dark"

    def test_diz_o_que_aconteceu(self, cliente):
        resposta = cliente.post(reverse("accounts:tema"), {"tema": "dark"}, follow=True)
        assert "Tema escuro ativado" in resposta.content.decode()

    def test_voltar_ao_claro(self, cliente, gestor):
        cliente.post(reverse("accounts:tema"), {"tema": "dark"})
        cliente.post(reverse("accounts:tema"), {"tema": "light"})
        gestor.refresh_from_db()
        assert gestor.theme == "light"

    def test_escolher_o_que_ja_esta_ativo_avisa_e_nao_grava(self, cliente):
        resposta = cliente.post(
            reverse("accounts:tema"), {"tema": "light"}, follow=True
        )
        assert "Nada mudou" in resposta.content.decode()

    @pytest.mark.parametrize("valor", ["", "azul", "DARK", "dark; x", "<script>"])
    def test_valor_invalido_e_recusado_sem_mexer_no_tema(self, cliente, gestor, valor):
        resposta = cliente.post(reverse("accounts:tema"), {"tema": valor}, follow=True)
        gestor.refresh_from_db()
        assert gestor.theme == "light"
        assert "Escolha o tema claro ou o escuro" in resposta.content.decode()

    def test_so_aceita_post(self, cliente):
        assert cliente.get(reverse("accounts:tema")).status_code == 405

    def test_exige_login(self, client):
        resposta = client.post(reverse("accounts:tema"), {"tema": "dark"})
        assert resposta.status_code == 302
        assert reverse("accounts:login") in resposta["Location"]

    def test_post_sem_csrf_e_recusado(self, gestor):
        seguro = Client(enforce_csrf_checks=True)
        seguro.force_login(gestor)
        resposta = seguro.post(reverse("accounts:tema"), {"tema": "dark"})
        assert resposta.status_code == 403
        gestor.refresh_from_db()
        assert gestor.theme == "light"

    def test_cada_usuario_tem_o_seu(self, cliente, gestor, db):
        outro = User.objects.create_user(
            username="leitor", password=SENHA, role=Role.CONSULTA
        )
        cliente.post(reverse("accounts:tema"), {"tema": "dark"})
        outro.refresh_from_db()
        assert outro.theme == "light"

        outro_cliente = Client()
        outro_cliente.force_login(outro)
        assert _tema_do_html(outro_cliente.get(reverse("accounts:conta"))) == "light"


class TestCookieDaTelaDeEntrada:
    """A tela de entrar não sabe quem é o usuário: usa o último tema deste navegador."""

    def test_escolher_grava_o_cookie(self, cliente):
        resposta = cliente.post(reverse("accounts:tema"), {"tema": "dark"})
        cookie = resposta.cookies[settings.THEME_COOKIE]
        assert cookie.value == "dark"
        assert cookie["httponly"]
        assert cookie["samesite"] == "Lax"

    def test_login_aparece_no_tema_do_cookie(self, client, db):
        client.cookies[settings.THEME_COOKIE] = "dark"
        assert _tema_do_html(client.get(reverse("accounts:login"))) == "dark"

    def test_sem_cookie_ou_com_lixo_o_login_fica_claro(self, client, db):
        assert _tema_do_html(client.get(reverse("accounts:login"))) == "light"
        client.cookies[settings.THEME_COOKIE] = '"><script>'
        assert _tema_do_html(client.get(reverse("accounts:login"))) == "light"

    def test_o_cookie_acompanha_o_tema_do_usuario_que_entra(self, client, gestor):
        """Outro usuário no mesmo navegador: o cookie deixa de ser o do anterior."""
        gestor.theme = "dark"
        gestor.save(update_fields=["theme"])
        client.cookies[settings.THEME_COOKIE] = "light"
        client.force_login(gestor)
        resposta = client.get(reverse("accounts:conta"))
        assert resposta.cookies[settings.THEME_COOKIE].value == "dark"

    def test_nao_regrava_o_cookie_quando_ja_esta_certo(self, client, gestor):
        client.force_login(gestor)
        client.cookies[settings.THEME_COOKIE] = "light"
        resposta = client.get(reverse("accounts:conta"))
        assert settings.THEME_COOKIE not in resposta.cookies


@pytest.mark.django_db(transaction=True)
def test_salvar_dados_pessoais_funciona_fora_da_transacao_do_teste(client, gestor):
    """`atualizar_propria_conta` usa `select_for_update`, que exige transação.
    O `db` comum embrulha o teste numa e esconderia a falta do `atomic`."""
    client.force_login(gestor)
    resposta = client.post(
        reverse("accounts:conta"),
        {
            "username": "gestor1",
            "first_name": "Gil",
            "last_name": "",
            "phone": "",
            "birth_date": "",
            "cpf": "",
        },
    )
    assert resposta.status_code == 302
