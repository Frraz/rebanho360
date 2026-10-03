"""Quem precisa do segundo fator e ainda não o provou nesta sessão não vai
a lugar nenhum — nem ao admin do Django — a não ser às telas do próprio
segundo fator, ao login/logout e ao que não é página (`/health/`, estáticos).

É middleware, e não decorador nas views, para ser impossível esquecer uma
rota: "nunca confiar só em is_staff" vale também para "nunca confiar que cada
view lembrou de checar". Ver docs/seguranca/01#autenticação.
"""

from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from apps.accounts import trusted_devices, two_factor
from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria

#: Caminhos liberados antes do segundo fator. `/contas/entrar/` e `/sair/`
#: (para o usuário poder desistir) e as telas do 2FA; o resto é infraestrutura.
PREFIXOS_LIBERADOS = (
    "/contas/2fa/",
    "/contas/entrar/",
    "/contas/sair/",
    "/health/",
    "/ready/",
    "/static/",
    "/__debug__/",
)


#: A sessão longa não é conferida onde não há página: estáticos, saúde e o
#: próprio logout (que precisa funcionar mesmo com o dispositivo revogado).
PREFIXOS_SEM_SESSAO_LONGA = (
    "/contas/sair/",
    "/health/",
    "/ready/",
    "/static/",
    "/__debug__/",
)


def _redirecionar(request, destino: str):
    if request.headers.get("HX-Request") == "true":
        resposta = HttpResponse(status=204)
        resposta["HX-Redirect"] = destino
        return resposta
    return redirect(destino)


class SessaoLongaMiddleware:
    """Sessão aberta num dispositivo confiável (ADR 0009) cai quando o
    dispositivo é revogado ou vence, ou depois de `TRUSTED_IDLE_HOURS` sem uso.
    Sem isto, revogar na página Conta só valeria na próxima entrada."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, "user", None)
        if (
            usuario is not None
            and usuario.is_authenticated
            and trusted_devices.SESSION_DISPOSITIVO in request.session
            and not request.path.startswith(PREFIXOS_SEM_SESSAO_LONGA)
        ):
            motivo = trusted_devices.motivo_para_encerrar_a_sessao(request)
            if motivo:
                registrar_auditoria(
                    action=AuditAction.LOGOUT,
                    entity_type="User",
                    entity_id=str(usuario.pk),
                    reason=motivo,
                    actor=usuario,
                )
                logout(request)
                destino = (
                    f"{reverse('accounts:login')}?"
                    f"{urlencode({'next': request.get_full_path()})}"
                )
                return _redirecionar(request, destino)
        return self.get_response(request)


class TwoFactorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, "user", None)
        if (
            usuario is not None
            and usuario.is_authenticated
            and not request.path.startswith(PREFIXOS_LIBERADOS)
            and two_factor.precisa_de_segundo_fator(usuario)
            and not two_factor.sessao_verificada(request)
        ):
            # Dispositivo confiável: a senha já foi dada; o código é dispensado.
            if two_factor.dispositivo_confirmado(usuario):
                dispositivo = trusted_devices.dispositivo_valido(request)
                if dispositivo is not None:
                    two_factor.marcar_sessao_verificada(request, dispositivo)
                    trusted_devices.registrar_uso(dispositivo, request)
                    registrar_auditoria(
                        action=AuditAction.LOGIN,
                        entity_type="User",
                        entity_id=str(usuario.pk),
                        reason=(
                            "Segundo fator dispensado: dispositivo confiável "
                            f"({dispositivo.label})"
                        ),
                        actor=usuario,
                    )
                    return self.get_response(request)
            nome = (
                "accounts:2fa_verificar"
                if two_factor.dispositivo_confirmado(usuario)
                else "accounts:2fa_configurar"
            )
            destino = f"{reverse(nome)}?{urlencode({'next': request.get_full_path()})}"
            return _redirecionar(request, destino)
        return self.get_response(request)


#: Quem tem de trocar a senha só consegue trocá-la (ou sair).
PREFIXOS_DA_TROCA_DE_SENHA = (
    "/contas/senha/trocar/",
    "/contas/2fa/",
    "/contas/sair/",
    "/health/",
    "/ready/",
    "/static/",
    "/__debug__/",
)


class PasswordChangeRequiredMiddleware:
    """Senha temporária definida por um administrador vale uma vez: no primeiro
    acesso, a pessoa vai direto para a troca. Middleware, como o do segundo
    fator, para não depender de cada view lembrar."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, "user", None)
        if (
            usuario is not None
            and usuario.is_authenticated
            and usuario.must_change_password
            and not request.path.startswith(PREFIXOS_DA_TROCA_DE_SENHA)
        ):
            destino = reverse("accounts:password_change")
            if request.headers.get("HX-Request") == "true":
                resposta = HttpResponse(status=204)
                resposta["HX-Redirect"] = destino
                return resposta
            messages.warning(
                request,
                "Sua senha é temporária. Defina uma nova para continuar.",
            )
            return redirect(destino)
        return self.get_response(request)


class TemaCookieMiddleware:
    """Mantém o cookie do tema igual ao do usuário logado. O cookie existe para
    a tela de entrar combinar com a última escolha feita neste navegador; sem
    isto, quem usa o tema escuro receberia uma tela de login branca. Só grava
    quando muda (login, troca de tema, outro usuário no mesmo navegador)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        usuario = getattr(request, "user", None)
        if (
            usuario is not None
            and usuario.is_authenticated
            and request.COOKIES.get(settings.THEME_COOKIE) != usuario.theme
        ):
            gravar_cookie_do_tema(response, usuario.theme)
        return response


def gravar_cookie_do_tema(response, tema: str) -> None:
    response.set_cookie(
        settings.THEME_COOKIE,
        tema,
        max_age=60 * 60 * 24 * 365,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
    )
