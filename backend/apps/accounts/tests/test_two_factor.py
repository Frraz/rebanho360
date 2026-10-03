"""F4-09 — segundo fator (TOTP), opcional e recomendado a todos: o algoritmo
contra os vetores da RFC 6238, o fluxo de configurar/verificar/recuperar e a
garantia de que quem o ativou não entra sem ele."""

import base64

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.accounts import two_factor
from apps.accounts.models import RecoveryCode, Role, TOTPDevice, User
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db

SENHA = "senha-correta-123"


@pytest.fixture(autouse=True)
def limpar_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def financeiro():
    return User.objects.create_user(
        username="fin", password=SENHA, role=Role.FINANCEIRO
    )


@pytest.fixture
def admin():
    return User.objects.create_user(username="adm", password=SENHA, role=Role.ADMIN)


@pytest.fixture
def gestor():
    return User.objects.create_user(username="ges", password=SENHA, role=Role.GESTOR)


def entrar(client, usuario):
    return client.post(
        reverse("accounts:login"), {"username": usuario.username, "password": SENHA}
    )


def codigo_de(usuario, *, deslocamento=0):
    """O código que o aplicativo mostraria — `deslocamento` em passos de 30 s."""
    segredo = TOTPDevice.objects.get(user=usuario).secret
    return two_factor.codigo_totp(segredo, two_factor.passo_atual() + deslocamento)


def ativar(client, usuario):
    """Entra, configura o aplicativo e devolve os códigos de recuperação."""
    entrar(client, usuario)
    client.get(reverse("accounts:2fa_configurar"))
    resposta = client.post(
        reverse("accounts:2fa_configurar"), {"codigo": codigo_de(usuario)}
    )
    return [c for c in resposta.context["codigos"]], resposta


class TestAlgoritmoTOTP:
    """Vetores do Apêndice B da RFC 6238 (SHA-1, segredo ASCII
    `12345678901234567890`). A RFC dá 8 dígitos; os 6 de que precisamos são os
    seis últimos, porque a truncagem é a mesma módulo 10^6."""

    SEGREDO = base64.b32encode(b"12345678901234567890").decode()

    @pytest.mark.parametrize(
        "tempo,esperado",
        [
            (59, "287082"),
            (1111111109, "081804"),
            (1111111111, "050471"),
            (1234567890, "005924"),
            (2000000000, "279037"),
            (20000000000, "353130"),
        ],
    )
    def test_vetores_da_rfc(self, tempo, esperado):
        assert two_factor.codigo_totp(self.SEGREDO, tempo // 30) == esperado

    def test_aceita_o_passo_anterior_e_o_seguinte_mas_nao_dois_para_tras(self):
        agora = 1_700_000_000
        passo = agora // 30

        assert (
            two_factor.passo_do_codigo(
                self.SEGREDO, two_factor.codigo_totp(self.SEGREDO, passo), agora=agora
            )
            == passo
        )
        assert (
            two_factor.passo_do_codigo(
                self.SEGREDO,
                two_factor.codigo_totp(self.SEGREDO, passo - 1),
                agora=agora,
            )
            == passo - 1
        )
        assert (
            two_factor.passo_do_codigo(
                self.SEGREDO,
                two_factor.codigo_totp(self.SEGREDO, passo + 1),
                agora=agora,
            )
            == passo + 1
        )
        assert (
            two_factor.passo_do_codigo(
                self.SEGREDO,
                two_factor.codigo_totp(self.SEGREDO, passo - 2),
                agora=agora,
            )
            is None
        )

    @pytest.mark.parametrize("lixo", ["", "abc", "12345", "1234567", None])
    def test_codigo_mal_formado_e_recusado(self, lixo):
        assert two_factor.passo_do_codigo(self.SEGREDO, lixo) is None

    def test_uri_de_provisionamento(self, financeiro):
        uri = two_factor.uri_de_provisionamento(financeiro, "ABCDEFGH")

        assert uri.startswith("otpauth://totp/Rebanho360%3Afin?secret=ABCDEFGH")
        assert "issuer=Rebanho360" in uri and "period=30" in uri and "digits=6" in uri

    def test_segredo_tem_160_bits_em_base32(self):
        segredo = two_factor.gerar_segredo()

        assert len(base64.b32decode(segredo)) == 20
        assert two_factor.gerar_segredo() != segredo


class TestOpcional:
    def test_financeiro_e_admin_entram_sem_segundo_fator(
        self, client, financeiro, admin
    ):
        for usuario in (financeiro, admin):
            entrar(client, usuario)
            for url in ("/", "/financeiro/", "/relatorios/"):
                assert client.get(url).status_code == 200, url
            client.post(reverse("accounts:logout"))

    def test_inicio_recomenda_e_deixa_de_recomendar_depois_de_ativar(
        self, client, financeiro
    ):
        entrar(client, financeiro)
        assert (
            "Proteja a sua conta com o segundo fator"
            in client.get("/").content.decode()
        )

        ativar(Client(), financeiro)
        client.post(reverse("accounts:logout"))
        outro = Client()
        entrar(outro, financeiro)
        outro.post(reverse("accounts:2fa_verificar"), {"codigo": codigo_de(financeiro)})
        assert "Proteja a sua conta" not in outro.get("/").content.decode()

    def test_conta_diz_que_nao_e_obrigatorio(self, client, gestor):
        entrar(client, gestor)

        html = client.get(reverse("accounts:conta")).content.decode()

        assert "Não é obrigatório" in html and "Ativar o segundo fator" in html

    def test_adesao_voluntaria_vale_para_qualquer_papel(self, client, gestor):
        ativar(client, gestor)
        outro = Client()
        entrar(outro, gestor)

        assert "/2fa/verificar/" in outro.get("/")["Location"]

    def test_quem_ativou_nao_entra_nem_com_post_sem_verificar(self, client, gestor):
        ativar(client, gestor)
        outro = Client()
        entrar(outro, gestor)

        resposta = outro.post(reverse("finance:titulo_novo"), {})

        assert resposta.status_code == 302
        assert "/2fa/" in resposta["Location"]

    def test_login_e_logout_e_health_ficam_liberados(self, client, financeiro):
        entrar(client, financeiro)

        assert client.get("/health/").status_code == 200
        assert client.get(reverse("accounts:2fa_configurar")).status_code == 200

    def test_requisicao_htmx_recebe_hx_redirect(self, client, financeiro):
        ativar(Client(), financeiro)
        entrar(client, financeiro)

        resposta = client.get("/financeiro/", HTTP_HX_REQUEST="true")

        assert resposta.status_code == 204
        assert "/2fa/verificar/" in resposta["HX-Redirect"]


class TestConfigurar:
    def test_pagina_mostra_qr_e_chave_e_o_segredo_nao_vai_para_a_url(
        self, client, financeiro
    ):
        entrar(client, financeiro)

        resposta = client.get(reverse("accounts:2fa_configurar"))
        html = resposta.content.decode()
        segredo = TOTPDevice.objects.get(user=financeiro).secret

        assert "<svg" in html and "QR code do segundo fator" in html
        assert " ".join(segredo[i : i + 4] for i in range(0, 32, 4)) in html
        assert segredo not in resposta.wsgi_request.get_full_path()
        # Sem menu: quem não provou o segundo fator não clica no sistema.
        assert 'aria-label="Menu principal"' not in html

    def test_recarregar_nao_troca_o_segredo(self, client, financeiro):
        entrar(client, financeiro)
        client.get(reverse("accounts:2fa_configurar"))
        primeiro = TOTPDevice.objects.get(user=financeiro).secret

        client.get(reverse("accounts:2fa_configurar"))

        assert TOTPDevice.objects.get(user=financeiro).secret == primeiro

    def test_codigo_errado_nao_ativa(self, client, financeiro):
        entrar(client, financeiro)
        client.get(reverse("accounts:2fa_configurar"))

        resposta = client.post(reverse("accounts:2fa_configurar"), {"codigo": "000000"})

        assert "O código não confere" in resposta.content.decode()
        assert not TOTPDevice.objects.get(user=financeiro).confirmed
        # Configurar pela metade não tranca ninguém: o sistema segue aberto.
        assert client.get("/").status_code == 200

    def test_codigo_certo_ativa_mostra_codigos_de_recuperacao_e_libera_a_sessao(
        self, client, financeiro
    ):
        codigos, resposta = ativar(client, financeiro)

        assert TOTPDevice.objects.get(user=financeiro).confirmed
        assert len(codigos) == 10 and all(len(c) == 11 and "-" in c for c in codigos)
        assert "Guarde estes códigos" in resposta.content.decode()
        assert client.get("/financeiro/").status_code == 200

    def test_codigos_de_recuperacao_ficam_so_como_hash(self, client, financeiro):
        codigos, _ = ativar(client, financeiro)

        guardados = set(RecoveryCode.objects.values_list("code_hash", flat=True))

        assert len(guardados) == 10
        assert not any(c.replace("-", "") in guardados for c in codigos)
        assert all(len(h) == 64 for h in guardados)

    def test_segredo_e_codigos_nao_aparecem_na_auditoria(self, client, financeiro):
        codigos, _ = ativar(client, financeiro)
        segredo = TOTPDevice.objects.get(user=financeiro).secret

        for evento in AuditEvent.objects.all():
            texto = f"{evento.before}{evento.after}{evento.reason}{evento.entity_id}"
            assert segredo not in texto
            assert not any(c in texto for c in codigos)
        assert AuditEvent.objects.filter(reason="Segundo fator ativado").exists()


class TestVerificar:
    def test_entrada_seguinte_pede_o_codigo_e_aceita_o_certo(self, client, financeiro):
        ativar(client, financeiro)
        outro = Client()
        entrar(outro, financeiro)

        pedido = outro.get("/financeiro/")
        assert pedido["Location"].startswith(reverse("accounts:2fa_verificar"))
        # O passo atual já foi usado ao ativar: o do próximo vale (dentro da janela).
        resposta = outro.post(
            reverse("accounts:2fa_verificar"),
            {"codigo": codigo_de(financeiro, deslocamento=1), "next": "/financeiro/"},
        )

        assert resposta.status_code == 302 and resposta["Location"] == "/financeiro/"
        assert outro.get("/financeiro/").status_code == 200
        assert AuditEvent.objects.filter(
            action="LOGIN", reason="Segundo fator verificado"
        ).exists()

    def test_codigo_errado_e_recusado_e_audita(self, client, financeiro):
        ativar(client, financeiro)
        outro = Client()
        entrar(outro, financeiro)

        resposta = outro.post(reverse("accounts:2fa_verificar"), {"codigo": "123456"})

        assert "Código inválido" in resposta.content.decode()
        assert "/2fa/verificar/" in outro.get("/financeiro/")["Location"]
        assert AuditEvent.objects.filter(
            action="LOGIN_FAILED", reason="Código do segundo fator inválido"
        ).exists()

    def test_o_mesmo_codigo_nao_vale_duas_vezes(self, client, financeiro):
        ativar(client, financeiro)
        codigo = codigo_de(financeiro, deslocamento=1)
        um, dois = Client(), Client()
        entrar(um, financeiro)
        entrar(dois, financeiro)

        um.post(reverse("accounts:2fa_verificar"), {"codigo": codigo})
        replay = dois.post(reverse("accounts:2fa_verificar"), {"codigo": codigo})

        assert "Código inválido" in replay.content.decode()
        assert "/2fa/verificar/" in dois.get("/financeiro/")["Location"]

    def test_sexta_tentativa_e_bloqueada(self, client, financeiro):
        ativar(client, financeiro)
        outro = Client()
        entrar(outro, financeiro)

        for _ in range(5):
            outro.post(reverse("accounts:2fa_verificar"), {"codigo": "000000"})
        resposta = outro.post(
            reverse("accounts:2fa_verificar"),
            {"codigo": codigo_de(financeiro, deslocamento=1)},
        )

        assert "Muitas tentativas" in resposta.content.decode()
        assert "/2fa/verificar/" in outro.get("/financeiro/")["Location"]

    def test_next_externo_e_ignorado(self, client, financeiro):
        ativar(client, financeiro)
        outro = Client()
        entrar(outro, financeiro)

        resposta = outro.post(
            reverse("accounts:2fa_verificar"),
            {
                "codigo": codigo_de(financeiro, deslocamento=1),
                "next": "https://malicioso.example/",
            },
        )

        assert resposta["Location"] == reverse("dashboards:inicio")

    def test_post_sem_csrf_e_recusado(self, financeiro):
        ativar(Client(), financeiro)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(financeiro)

        resposta = cliente.post(reverse("accounts:2fa_verificar"), {"codigo": "000000"})

        assert resposta.status_code == 403

    def test_sessao_sensivel_expira_ao_fechar_o_navegador(self, client, financeiro):
        ativar(client, financeiro)

        assert client.session.get_expire_at_browser_close()


class TestRecuperacao:
    def test_codigo_de_recuperacao_entra_uma_vez_so(self, client, financeiro):
        codigos, _ = ativar(client, financeiro)
        um, dois = Client(), Client()
        entrar(um, financeiro)
        entrar(dois, financeiro)

        entrou = um.post(
            reverse("accounts:2fa_verificar"), {"codigo": codigos[0]}, follow=True
        )
        de_novo = dois.post(reverse("accounts:2fa_verificar"), {"codigo": codigos[0]})

        assert "código de recuperação" in entrou.content.decode()
        assert um.get("/financeiro/").status_code == 200
        assert "Código inválido" in de_novo.content.decode()
        assert two_factor.codigos_de_recuperacao_restantes(financeiro) == 9

    def test_aceita_minusculas_e_sem_hifen(self, client, financeiro):
        codigos, _ = ativar(client, financeiro)
        outro = Client()
        entrar(outro, financeiro)

        outro.post(
            reverse("accounts:2fa_verificar"),
            {"codigo": codigos[3].replace("-", "").lower()},
        )

        assert outro.get("/financeiro/").status_code == 200

    def test_gerar_novos_codigos_exige_codigo_do_aplicativo_e_invalida_os_antigos(
        self, client, financeiro
    ):
        antigos, _ = ativar(client, financeiro)

        recusado = client.post(reverse("accounts:2fa_status"), {"codigo": "000000"})
        assert "Código inválido" in recusado.content.decode()
        assert two_factor.codigos_de_recuperacao_restantes(financeiro) == 10

        aceito = client.post(
            reverse("accounts:2fa_status"),
            {"codigo": codigo_de(financeiro, deslocamento=1)},
        )
        novos = aceito.context["codigos"]
        outro = Client()
        entrar(outro, financeiro)
        resposta = outro.post(reverse("accounts:2fa_verificar"), {"codigo": antigos[0]})

        assert len(novos) == 10 and set(novos).isdisjoint(antigos)
        assert "Código inválido" in resposta.content.decode()

    def test_redefinir_apaga_tudo_encerra_sessoes_e_audita(
        self, client, financeiro, admin
    ):
        ativar(client, financeiro)

        two_factor.redefinir_segundo_fator(
            financeiro, por=admin, motivo="Perdeu o celular"
        )

        assert not TOTPDevice.objects.filter(user=financeiro).exists()
        assert not RecoveryCode.objects.filter(user=financeiro).exists()
        assert client.get("/financeiro/")["Location"].startswith("/contas/entrar/")
        evento = AuditEvent.objects.filter(
            reason__startswith="Segundo fator redefinido"
        ).get()
        assert evento.actor == admin and "Perdeu o celular" in evento.reason
        # Volta a entrar só com a senha e pode ativar de novo.
        novo = Client()
        entrar(novo, financeiro)
        assert novo.get("/").status_code == 200

    def test_comando_resetar_segundo_fator_audita_sem_ator(self, client, financeiro):
        ativar(client, financeiro)

        call_command("resetar_segundo_fator", "fin", "--motivo", "chamado 12")

        assert not TOTPDevice.objects.filter(user=financeiro).exists()
        evento = AuditEvent.objects.filter(
            reason__startswith="Segundo fator redefinido"
        ).get()
        assert evento.actor is None and "linha de comando" in evento.reason

    def test_comando_conferir_lista_quem_falta(self, financeiro, admin, capsys):
        call_command("conferir_segundo_fator")

        saida = capsys.readouterr().out
        assert "não usa" in saida and "fin" in saida and "adm" in saida
        assert "Hora do servidor" in saida


class TestAdminDoDjango:
    def test_admin_redefine_o_de_outro_mas_nao_o_proprio(
        self, client, financeiro, admin
    ):
        from django.contrib import admin as django_admin

        from apps.accounts.admin import UserAdmin

        ativar(Client(), financeiro)
        TOTPDevice.objects.create(
            user=admin, secret=two_factor.gerar_segredo(), confirmed=True
        )
        admin.is_staff = admin.is_superuser = True
        admin.save()

        class Req:
            user = admin

        modelo = UserAdmin(User, django_admin.site)
        mensagens = []
        modelo.message_user = lambda request, texto, nivel=None: mensagens.append(texto)

        modelo.redefinir_segundo_fator(
            Req, User.objects.filter(pk__in=[financeiro.pk, admin.pk])
        )

        assert not TOTPDevice.objects.filter(user=financeiro).exists()
        assert TOTPDevice.objects.filter(user=admin).exists()  # o próprio fica
        assert any("próprio segundo fator" in m for m in mensagens)

    def test_so_admin_redefine(self, financeiro, gestor):
        from django.contrib import admin as django_admin

        from apps.accounts.admin import UserAdmin

        TOTPDevice.objects.create(user=financeiro, secret="X" * 32, confirmed=True)

        class Req:
            user = gestor

        modelo = UserAdmin(User, django_admin.site)
        modelo.message_user = lambda *a, **k: None
        modelo.redefinir_segundo_fator(Req, User.objects.filter(pk=financeiro.pk))

        assert TOTPDevice.objects.filter(user=financeiro).exists()
