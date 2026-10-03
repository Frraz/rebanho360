"""Quem precisa do segundo fator e ainda não o provou nesta sessão não vai
a lugar nenhum — nem ao admin do Django — a não ser às telas do próprio
segundo fator, ao login/logout e ao que não é página (`/health/`, estáticos).

É middleware, e não decorador nas views, para ser impossível esquecer uma
rota: "nunca confiar só em is_staff" vale também para "nunca confiar que cada
view lembrou de checar". Ver docs/seguranca/01#autenticação.
"""

from urllib.parse import urlencode

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from apps.accounts import two_factor

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
            nome = (
                "accounts:2fa_verificar"
                if two_factor.dispositivo_confirmado(usuario)
                else "accounts:2fa_configurar"
            )
            destino = f"{reverse(nome)}?{urlencode({'next': request.get_full_path()})}"
            if request.headers.get("HX-Request") == "true":
                resposta = HttpResponse(status=204)
                resposta["HX-Redirect"] = destino
                return resposta
            return redirect(destino)
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
