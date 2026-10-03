"""ADR 0009 — "Confiar neste dispositivo": o segundo fator deixa de ser pedido
em navegador já confiável, sem abrir mão da senha, e a confiança some quando
deve (revogação, troca de senha, vencimento, inatividade)."""

import datetime
import time

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts import trusted_devices, two_factor
from apps.accounts.models import Role, TOTPDevice, TrustedDevice, User
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db

SENHA = "senha-correta-123"
COOKIE = settings.TRUSTED_DEVICE_COOKIE
PAGINA = "/financeiro/"  # exige o segundo fator para quem o ativou


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
def outro_financeiro():
    return User.objects.create_user(
        username="fin2", password=SENHA, role=Role.FINANCEIRO
    )


def entrar(client, usuario, **extra):
    return client.post(
        reverse("accounts:login"),
        {"username": usuario.username, "password": SENHA},
        **extra,
    )


def codigo_de(usuario, *, deslocamento=0):
    segredo = TOTPDevice.objects.get(user=usuario).secret
    return two_factor.codigo_totp(segredo, two_factor.passo_atual() + deslocamento)


def ativar(client, usuario, *, confiar):
    """Entra e configura o aplicativo; `confiar` marca (ou não) a caixa."""
    entrar(client, usuario)
    client.get(reverse("accounts:2fa_configurar"))
    dados = {"codigo": codigo_de(usuario)}
    if confiar:
        dados["confiar"] = "1"
    return client.post(reverse("accounts:2fa_configurar"), dados)


def navegador_com_cookie_de(origem: Client) -> Client:
    """Outro navegador, mas com o cookie de dispositivo confiável do `origem`."""
    novo = Client()
    novo.cookies[COOKIE] = origem.cookies[COOKIE].value
    return novo


@pytest.fixture
def confiado(client, financeiro):
    """Um navegador que ativou o 2FA e marcou 'confiar'."""
    ativar(client, financeiro, confiar=True)
    return client


def pede_codigo(client) -> bool:
    resposta = client.get(PAGINA)
    return resposta.status_code == 302 and resposta["Location"].startswith(
        reverse("accounts:2fa_verificar")
    )


class TestDarConfianca:
    def test_marcar_a_caixa_ao_ativar_poe_o_cookie_e_grava_so_o_hash(
        self, confiado, financeiro
    ):
        cookie = confiado.cookies[COOKIE]
        dispositivo = TrustedDevice.objects.get(user=financeiro)

        assert cookie["httponly"] and cookie["samesite"] == "Lax"
        assert int(cookie["max-age"]) == settings.TRUSTED_DEVICE_MAX_DAYS * 86400
        assert dispositivo.token_hash != cookie.value
        assert not TrustedDevice.objects.filter(token_hash=cookie.value).exists()
        assert dispositivo.label  # "Navegador no ..." — para reconhecer na lista

    def test_sem_marcar_a_caixa_nao_ha_confianca(self, client, financeiro):
        ativar(client, financeiro, confiar=False)

        assert COOKIE not in client.cookies
        assert not TrustedDevice.objects.exists()
        assert client.session.get_expire_at_browser_close()  # como antes

    def test_marcar_ao_verificar_tambem_vale(self, client, financeiro):
        ativar(client, financeiro, confiar=False)
        outro = Client()
        entrar(outro, financeiro)

        resposta = outro.post(
            reverse("accounts:2fa_verificar"),
            {"codigo": codigo_de(financeiro, deslocamento=1), "confiar": "1"},
        )

        assert resposta.status_code == 302 and COOKIE in outro.cookies
        assert AuditEvent.objects.filter(
            action="LOGIN", reason__contains="dispositivo marcado como confiável"
        ).exists()
        assert AuditEvent.objects.filter(
            action="UPDATE", entity_type="TrustedDevice", reason__contains="confiável"
        ).exists()

    def test_sessao_do_dispositivo_confiavel_e_longa(self, confiado):
        sessao = confiado.session

        assert not sessao.get_expire_at_browser_close()
        assert sessao.get_expiry_age() == pytest.approx(
            settings.TRUSTED_SESSION_DAYS * 86400, abs=60
        )

    def test_rotulo_do_navegador(self):
        chrome_linux = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
        edge_windows = (
            "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36 Edg/120.0"
        )
        assert trusted_devices.rotulo_do_navegador(chrome_linux) == "Chrome no Linux"
        assert trusted_devices.rotulo_do_navegador(edge_windows) == "Edge no Windows"
        assert trusted_devices.rotulo_do_navegador("") == "Navegador"


class TestUsarConfianca:
    def test_outro_navegador_com_o_cookie_e_a_senha_nao_pede_o_codigo(
        self, confiado, financeiro
    ):
        novo = navegador_com_cookie_de(confiado)
        entrar(novo, financeiro)

        assert novo.get(PAGINA).status_code == 200
        assert AuditEvent.objects.filter(
            action="LOGIN", reason__startswith="Segundo fator dispensado"
        ).exists()
        assert not novo.session.get_expire_at_browser_close()

    def test_sem_o_cookie_pede_o_codigo(self, confiado, financeiro):
        novo = Client()
        entrar(novo, financeiro)

        assert pede_codigo(novo)

    def test_a_senha_continua_sendo_exigida(self, confiado, financeiro):
        novo = navegador_com_cookie_de(confiado)

        resposta = novo.post(
            reverse("accounts:login"),
            {"username": financeiro.username, "password": "errada-errada-1"},
        )

        assert resposta.status_code == 200  # volta ao formulário
        assert novo.get(PAGINA).status_code == 302
        assert "/contas/entrar/" in novo.get(PAGINA)["Location"]

    def test_cookie_de_outro_usuario_nao_vale(
        self, confiado, financeiro, outro_financeiro
    ):
        ativar(Client(), outro_financeiro, confiar=False)
        intruso = navegador_com_cookie_de(confiado)
        entrar(intruso, outro_financeiro)

        assert pede_codigo(intruso)

    def test_cookie_adulterado_nao_vale(self, confiado, financeiro):
        novo = Client()
        novo.cookies[COOKIE] = confiado.cookies[COOKIE].value + "x"
        entrar(novo, financeiro)

        assert pede_codigo(novo)

    @pytest.mark.parametrize("campo", ["expires_at", "absolute_expires_at"])
    def test_vencido_nao_vale(self, confiado, financeiro, campo):
        passado = timezone.now() - datetime.timedelta(minutes=1)
        # O CHECK pede expires_at <= teto: ao vencer o teto, a janela vai junto.
        TrustedDevice.objects.update(**{"expires_at": passado, campo: passado})
        novo = navegador_com_cookie_de(confiado)
        entrar(novo, financeiro)

        assert pede_codigo(novo)

    def test_revogado_nao_vale(self, confiado, financeiro):
        trusted_devices.revogar(
            TrustedDevice.objects.get(user=financeiro), motivo="teste"
        )
        novo = navegador_com_cookie_de(confiado)
        entrar(novo, financeiro)

        assert pede_codigo(novo)

    def test_uso_renova_a_janela_mas_nao_passa_do_teto(self, confiado, financeiro):
        agora = timezone.now()
        TrustedDevice.objects.update(
            last_used_at=agora - datetime.timedelta(hours=2),
            expires_at=agora + datetime.timedelta(days=2),
            absolute_expires_at=agora + datetime.timedelta(days=10),
        )
        novo = navegador_com_cookie_de(confiado)
        entrar(novo, financeiro)
        novo.get(PAGINA)

        dispositivo = TrustedDevice.objects.get()
        # 30 dias pediriam mais que o teto: fica no teto.
        assert dispositivo.expires_at == dispositivo.absolute_expires_at

    def test_uso_renova_para_30_dias_quando_o_teto_permite(self, confiado, financeiro):
        agora = timezone.now()
        TrustedDevice.objects.update(
            last_used_at=agora - datetime.timedelta(hours=2),
            expires_at=agora + datetime.timedelta(days=2),
        )
        novo = navegador_com_cookie_de(confiado)
        entrar(novo, financeiro)
        novo.get(PAGINA)

        restante = TrustedDevice.objects.get().expires_at - timezone.now()
        assert restante > datetime.timedelta(days=settings.TRUSTED_DEVICE_DAYS - 1)

    def test_ip_novo_nao_revoga_so_audita(self, confiado, financeiro):
        novo = navegador_com_cookie_de(confiado)
        entrar(novo, financeiro, REMOTE_ADDR="203.0.113.9")

        assert novo.get(PAGINA, REMOTE_ADDR="203.0.113.9").status_code == 200

        dispositivo = TrustedDevice.objects.get()
        assert dispositivo.revoked_at is None
        assert dispositivo.last_ip == "203.0.113.9"
        assert AuditEvent.objects.filter(
            entity_type="TrustedDevice", reason__contains="IP novo"
        ).exists()


class TestRevogar:
    def test_trocar_a_senha_revoga_os_outros_e_mantem_o_atual(
        self, confiado, financeiro
    ):
        # Um segundo dispositivo, de outro navegador.
        segundo = TrustedDevice.objects.create(
            user=financeiro,
            token_hash="b" * 64,
            last_used_at=timezone.now(),
            expires_at=timezone.now() + datetime.timedelta(days=5),
            absolute_expires_at=timezone.now() + datetime.timedelta(days=5),
        )

        resposta = confiado.post(
            reverse("accounts:password_change"),
            {
                "old_password": SENHA,
                "new_password1": "outra-senha-forte-987",
                "new_password2": "outra-senha-forte-987",
            },
        )

        assert resposta.status_code == 302
        segundo.refresh_from_db()
        atual = TrustedDevice.objects.exclude(pk=segundo.pk).get()
        assert segundo.revoked_at is not None
        assert atual.revoked_at is None
        assert confiado.get(PAGINA).status_code == 200  # a sessão atual segue

    def test_encerrar_sessoes_revoga_os_dispositivos(self, confiado, financeiro):
        two_factor.encerrar_sessoes(financeiro)

        assert TrustedDevice.objects.get().revoked_at is not None
        novo = navegador_com_cookie_de(confiado)
        entrar(novo, financeiro)
        assert pede_codigo(novo)

    def test_redefinir_o_segundo_fator_revoga_os_dispositivos(
        self, confiado, financeiro
    ):
        two_factor.redefinir_segundo_fator(financeiro, motivo="perdeu o celular")

        assert TrustedDevice.objects.get().revoked_at is not None

    def test_revogar_na_conta_derruba_a_sessao_daquele_navegador(
        self, confiado, financeiro
    ):
        outro = navegador_com_cookie_de(confiado)
        entrar(outro, financeiro)
        assert outro.get(PAGINA).status_code == 200
        dispositivo = TrustedDevice.objects.get()

        resposta = confiado.post(
            reverse("accounts:dispositivo_revogar", args=[dispositivo.pk])
        )

        assert resposta.status_code == 302
        dispositivo.refresh_from_db()
        assert dispositivo.revoked_at is not None
        # O outro navegador usava o mesmo dispositivo: cai na próxima requisição.
        derrubado = outro.get(PAGINA)
        assert (
            derrubado.status_code == 302 and "/contas/entrar/" in derrubado["Location"]
        )
        assert AuditEvent.objects.filter(
            action="LOGOUT", reason__contains="revogado"
        ).exists()

    def test_revogar_todos(self, confiado, financeiro):
        resposta = confiado.post(reverse("accounts:dispositivos_revogar_todos"))

        assert resposta.status_code == 302
        assert not trusted_devices.dispositivos_ativos(financeiro).exists()

    def test_dispositivo_de_outro_usuario_responde_404(
        self, confiado, financeiro, outro_financeiro
    ):
        alheio = TrustedDevice.objects.get(user=financeiro)
        invasor = Client()
        invasor.force_login(outro_financeiro)

        resposta = invasor.post(
            reverse("accounts:dispositivo_revogar", args=[alheio.pk])
        )

        assert resposta.status_code == 404
        alheio.refresh_from_db()
        assert alheio.revoked_at is None

    def test_revogar_exige_csrf(self, confiado, financeiro):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(financeiro)
        sessao = cliente.session
        sessao[two_factor.SESSION_OTP_VERIFICADO] = timezone.now().isoformat()
        sessao.save()
        dispositivo = TrustedDevice.objects.get()

        resposta = cliente.post(
            reverse("accounts:dispositivo_revogar", args=[dispositivo.pk])
        )

        assert resposta.status_code == 403


class TestInatividade:
    def test_oito_horas_sem_uso_encerram_a_sessao(self, confiado, financeiro):
        sessao = confiado.session
        sessao[trusted_devices.SESSION_ATIVIDADE] = int(time.time()) - (
            settings.TRUSTED_IDLE_HOURS * 3600 + 60
        )
        sessao.save()

        resposta = confiado.get(PAGINA)

        assert resposta.status_code == 302 and "/contas/entrar/" in resposta["Location"]
        assert AuditEvent.objects.filter(
            action="LOGOUT", reason="Sessão encerrada por inatividade"
        ).exists()

    def test_pedido_htmx_recebe_hx_redirect(self, confiado):
        sessao = confiado.session
        sessao[trusted_devices.SESSION_ATIVIDADE] = 0
        sessao.save()

        resposta = confiado.get(PAGINA, HTTP_HX_REQUEST="true")

        assert resposta.status_code == 204 and "HX-Redirect" in resposta

    def test_dentro_do_prazo_segue_e_renova_a_atividade(self, confiado):
        antiga = int(time.time()) - 3600
        sessao = confiado.session
        sessao[trusted_devices.SESSION_ATIVIDADE] = antiga
        sessao.save()

        assert confiado.get(PAGINA).status_code == 200
        assert confiado.session[trusted_devices.SESSION_ATIVIDADE] > antiga

    def test_ao_voltar_apos_inatividade_so_a_senha_e_pedida(self, confiado, financeiro):
        sessao = confiado.session
        sessao[trusted_devices.SESSION_ATIVIDADE] = 0
        sessao.save()
        confiado.get(PAGINA)  # cai

        entrar(confiado, financeiro)

        assert confiado.get(PAGINA).status_code == 200


class TestContaEManutencao:
    def test_conta_lista_o_dispositivo_e_avisa_do_ip(self, confiado, financeiro):
        TrustedDevice.objects.update(last_ip="198.51.100.7", created_ip="203.0.113.1")

        html = confiado.get(
            reverse("accounts:conta"), REMOTE_ADDR="198.51.100.7"
        ).content.decode()

        assert "Dispositivos confiáveis" in html
        assert "Este dispositivo" in html
        assert "IP mudou" in html and "198.51.100.7" in html

    def test_limpeza_apaga_so_o_que_venceu_ha_mais_de_30_dias(
        self, confiado, financeiro
    ):
        agora = timezone.now()
        velho = TrustedDevice.objects.create(
            user=financeiro,
            token_hash="c" * 64,
            last_used_at=agora - datetime.timedelta(days=80),
            expires_at=agora - datetime.timedelta(days=40),
            absolute_expires_at=agora - datetime.timedelta(days=40),
        )

        assert trusted_devices.limpar_antigos() == 1
        assert not TrustedDevice.objects.filter(pk=velho.pk).exists()
        assert TrustedDevice.objects.count() == 1  # o ativo fica

    def test_dispositivo_nao_e_exportavel_nem_aparece_para_outro(self):
        from apps.exports.catalog import NAO_EXPORTAVEIS

        assert "accounts.TrustedDevice" in NAO_EXPORTAVEIS
