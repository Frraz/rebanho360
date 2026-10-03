from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from apps.accounts import services as account_services
from apps.accounts import trusted_devices, two_factor
from apps.accounts import user_management as usuarios
from apps.accounts.forms import ContaForm
from apps.accounts.models import TrustedDevice
from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.exceptions import BusinessError
from apps.core.request_context import client_ip
from apps.core.validators import formatar_cpf


class LoginView(auth_views.LoginView):
    """Login com rate limit de 5 tentativas por usuário e por IP em 15 min."""

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        self._ip = client_ip(request)
        username = request.POST.get("username", "")

        if account_services.is_rate_limited(username=username, ip_address=self._ip):
            registrar_auditoria(
                action=AuditAction.LOGIN_FAILED,
                entity_type="User",
                entity_id=username,
                reason="Bloqueado por limite de tentativas (rate limit)",
            )
            form = self.get_form_class()(request, data=request.POST)
            form.add_error(
                None,
                "Muitas tentativas de login. Tente novamente em alguns minutos.",
            )
            return self.render_to_response(self.get_context_data(form=form))

        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        username = form.get_user().username
        account_services.limpar_tentativas(username=username, ip_address=self._ip)
        # As tentativas falhas são contadas sob o texto digitado (usuário ou e-mail).
        digitado = form.data.get("username", "")
        if digitado and digitado != username:
            account_services.limpar_tentativas(username=digitado, ip_address=self._ip)
        response = super().form_valid(form)

        user = form.get_user()
        user.last_login_ip = self._ip
        user.save(update_fields=["last_login_ip"])
        registrar_auditoria(action=AuditAction.LOGIN, entity=user, actor=user)
        return response

    def form_invalid(self, form):
        username = form.data.get("username", "")
        account_services.registrar_tentativa_falha(
            username=username, ip_address=self._ip
        )
        registrar_auditoria(
            action=AuditAction.LOGIN_FAILED,
            entity_type="User",
            entity_id=username,
            reason="Credenciais inválidas",
        )
        return super().form_invalid(form)


class LogoutView(auth_views.LogoutView):
    def post(self, request, *args, **kwargs):
        user = request.user
        response = super().post(request, *args, **kwargs)
        if user.is_authenticated:
            registrar_auditoria(action=AuditAction.LOGOUT, entity=user, actor=user)
        return response


# --------------------------------------------------------------------------
# Conta: perfil, senha e segundo fator do próprio usuário
# --------------------------------------------------------------------------


def contexto_da_conta(request, *, form=None, senha_form=None) -> dict:
    """Tudo o que a página Conta mostra. Compartilhado com a troca de senha, que
    reabre a página com os erros quando a senha nova é recusada."""
    usuario = request.user
    acessos = []
    if not usuario.has_broad_access:
        acessos = [
            a.farm.name
            for a in usuario.farm_access.select_related("farm").order_by("farm__name")
        ]
    return {
        "form": form or ContaForm(usuario=usuario),
        "senha_form": senha_form or PasswordChangeForm(usuario),
        "cpf_formatado": formatar_cpf(usuario.cpf),
        "fazendas_do_usuario": acessos,
        "segundo_fator_ativo": two_factor.dispositivo_confirmado(usuario) is not None,
        "codigos_restantes": two_factor.codigos_de_recuperacao_restantes(usuario),
        "dispositivos_confiaveis": _dispositivos_para_a_conta(request),
    }


def _dispositivos_para_a_conta(request) -> list[dict]:
    """Os dispositivos confiáveis do usuário, com o que a lista precisa mostrar:
    qual é este navegador e se o IP mudou desde que a confiança foi dada."""
    atual = trusted_devices.dispositivo_valido(request)
    return [
        {
            "dispositivo": d,
            "este": atual is not None and d.pk == atual.pk,
            "ip_mudou": bool(d.created_ip) and d.created_ip != d.last_ip,
        }
        for d in trusted_devices.dispositivos_ativos(request.user)
    ]


class ContaView(LoginRequiredMixin, View):
    """O próprio usuário vê e edita o seu perfil. O registro é sempre o de
    `request.user` — não há id na URL, então não há como abrir a conta de outro
    (e por isso nem escopo por fazenda)."""

    template_name = "accounts/conta.html"

    def get(self, request):
        return render(request, self.template_name, contexto_da_conta(request))

    def post(self, request):
        form = ContaForm(request.POST, usuario=request.user)
        if form.is_valid():
            try:
                mudou = usuarios.atualizar_propria_conta(
                    request.user, dados=form.cleaned_data
                )
            except BusinessError as exc:
                form.add_error("cpf", str(exc))
            else:
                if mudou:
                    messages.success(request, "✓ Perfil atualizado.")
                else:
                    messages.info(request, "Nada mudou: os dados já estavam assim.")
                return redirect("accounts:conta")
        return render(
            request, self.template_name, contexto_da_conta(request, form=form)
        )


class PasswordChangeView(auth_views.PasswordChangeView):
    """Troca de senha. Fora da troca obrigatória (senha temporária), a tela é a
    seção "Senha" da página Conta; na obrigatória, o usuário ainda não pode ir
    a outro lugar, então a tela é só esta."""

    template_name = "registration/password_change_form.html"
    success_url = "/"

    def get(self, request, *args, **kwargs):
        if not request.user.must_change_password:
            return redirect(reverse("accounts:conta") + "#senha")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["troca_obrigatoria"] = self.request.user.must_change_password
        return context

    def form_valid(self, form):
        usuario = form.user
        era_obrigatoria = usuario.must_change_password
        response = super().form_valid(form)
        if era_obrigatoria:
            usuario.must_change_password = False
            usuario.save(update_fields=["must_change_password"])
        usuarios.auditar_troca_de_senha(usuario)
        # Quem trocou a senha quer fechar portas: os outros navegadores voltam a
        # pedir o código. O atual segue confiável (a sessão continua aberta).
        atual = trusted_devices.dispositivo_valido(self.request)
        trusted_devices.revogar_todos(
            usuario,
            motivo="Troca de senha pelo próprio usuário",
            ator=usuario,
            exceto_id=atual.pk if atual else None,
        )
        if era_obrigatoria:
            return response
        messages.success(self.request, "✓ Senha alterada.")
        return redirect(reverse("accounts:conta") + "#senha")

    def form_invalid(self, form):
        if self.request.user.must_change_password:
            return super().form_invalid(form)
        return render(
            self.request,
            "accounts/conta.html",
            contexto_da_conta(self.request, senha_form=form),
        )


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.html"
    success_url = "/contas/senha/redefinir/enviado/"


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    success_url = "/contas/senha/redefinir/concluido/"

    def form_valid(self, form):
        response = super().form_valid(form)
        trusted_devices.revogar_todos(
            form.user, motivo="Senha definida por link", ator=form.user
        )
        # Quem definiu a própria senha por link não tem mais senha "temporária".
        if form.user.must_change_password:
            form.user.must_change_password = False
            form.user.save(update_fields=["must_change_password"])
        return response


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "registration/password_reset_complete.html"


# --------------------------------------------------------------------------
# Segundo fator (F4-09)
# --------------------------------------------------------------------------


def render_2fa(request, template, contexto=None):
    """As telas do segundo fator usam o layout sem menu: quem ainda não provou
    o segundo fator não deve ver — nem clicar em — o sistema."""
    return render(request, template, {"layout_minimo": True, **(contexto or {})})


def _destino_seguro(request, padrao="dashboards:inicio") -> str:
    """`next` só vale se for do próprio site — senão é redirecionamento aberto."""
    destino = request.POST.get("next") or request.GET.get("next") or ""
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}
    ):
        return destino
    return padrao


class ConfigurarSegundoFatorView(LoginRequiredMixin, View):
    """Mostra o QR code e o segredo; o usuário prova que o aplicativo gera
    os códigos antes de o segundo fator valer."""

    template_name = "registration/2fa_configurar.html"

    def _contexto(self, request, dispositivo, **extra):
        uri = two_factor.uri_de_provisionamento(request.user, dispositivo.secret)
        return {
            "qr_svg": two_factor.qr_svg(uri),
            # Para digitar à mão, em blocos de 4 — mais fácil de conferir.
            "segredo": " ".join(
                dispositivo.secret[i : i + 4]
                for i in range(0, len(dispositivo.secret), 4)
            ),
            "next": _destino_seguro(request, padrao=""),
            **extra,
        }

    def get(self, request):
        if two_factor.dispositivo_confirmado(request.user):
            return redirect("accounts:2fa_status")
        dispositivo = two_factor.iniciar_configuracao(request.user)
        return render_2fa(
            request, self.template_name, self._contexto(request, dispositivo)
        )

    def post(self, request):
        if two_factor.dispositivo_confirmado(request.user):
            return redirect("accounts:2fa_status")
        dispositivo = two_factor.iniciar_configuracao(request.user)
        if two_factor.bloqueado_por_tentativas(request.user):
            return render_2fa(
                request,
                self.template_name,
                self._contexto(
                    request,
                    dispositivo,
                    erro="Muitas tentativas. Tente novamente em alguns minutos.",
                ),
            )
        codigos = two_factor.confirmar_configuracao(
            request.user, request.POST.get("codigo", "")
        )
        if codigos is None:
            two_factor.registrar_falha(request.user)
            return render_2fa(
                request,
                self.template_name,
                self._contexto(
                    request,
                    dispositivo,
                    erro=(
                        "O código não confere. Digite o que o aplicativo mostra agora — "
                        "e confira se o relógio do celular está no horário automático."
                    ),
                ),
            )
        two_factor.limpar_falhas(request.user)
        two_factor.marcar_sessao_verificada(request)
        resposta = render_2fa(
            request,
            "registration/2fa_codigos.html",
            {
                "codigos": codigos,
                "recem_ativado": True,
                "continuar": _destino_seguro(request),
            },
        )
        if request.POST.get("confiar"):
            trusted_devices.confiar_neste_dispositivo(request, resposta)
        return resposta


class VerificarSegundoFatorView(LoginRequiredMixin, View):
    template_name = "registration/2fa_verificar.html"

    def get(self, request):
        if not two_factor.dispositivo_confirmado(request.user):
            return redirect("accounts:2fa_configurar")
        if two_factor.sessao_verificada(request):
            return redirect(_destino_seguro(request))
        return render_2fa(
            request, self.template_name, {"next": _destino_seguro(request, "")}
        )

    def post(self, request):
        if not two_factor.dispositivo_confirmado(request.user):
            return redirect("accounts:2fa_configurar")
        contexto = {"next": _destino_seguro(request, "")}
        if two_factor.bloqueado_por_tentativas(request.user):
            registrar_auditoria(
                action=AuditAction.LOGIN_FAILED,
                entity_type="User",
                entity_id=str(request.user.pk),
                reason="Segundo fator bloqueado por limite de tentativas",
                actor=request.user,
            )
            contexto["erro"] = "Muitas tentativas. Tente novamente em alguns minutos."
            return render_2fa(request, self.template_name, contexto)

        como = two_factor.verificar(request.user, request.POST.get("codigo", ""))
        if como is None:
            two_factor.registrar_falha(request.user)
            contexto["erro"] = (
                "Código inválido. Use o que o aplicativo mostra agora, "
                "ou um código de recuperação."
            )
            return render_2fa(request, self.template_name, contexto)

        two_factor.limpar_falhas(request.user)
        two_factor.marcar_sessao_verificada(request)
        confiar = bool(request.POST.get("confiar"))
        registrar_auditoria(
            action=AuditAction.LOGIN,
            entity=request.user,
            reason=(
                "Segundo fator verificado (código de recuperação)"
                if como == "recuperacao"
                else "Segundo fator verificado"
            )
            + (" — dispositivo marcado como confiável" if confiar else ""),
            actor=request.user,
        )
        if como == "recuperacao":
            restantes = two_factor.codigos_de_recuperacao_restantes(request.user)
            messages.warning(
                request,
                "Você entrou com um código de recuperação. "
                f"Restam {restantes}. Se perdeu o celular, configure o aplicativo "
                "de novo e gere códigos novos.",
            )
        resposta = redirect(_destino_seguro(request))
        if confiar:
            trusted_devices.confiar_neste_dispositivo(request, resposta)
        return resposta


class AdiarLembreteDoSegundoFatorView(LoginRequiredMixin, View):
    """ "Agora não" no aviso da tela de Início: o lembrete volta daqui a 14 dias.
    Só POST (grava), com CSRF."""

    http_method_names = ["post"]

    def post(self, request):
        two_factor.adiar_lembrete(request.user)
        proximo = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(
            proximo,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            proximo = reverse("dashboards:inicio")
        return redirect(proximo)


class StatusSegundoFatorView(LoginRequiredMixin, View):
    template_name = "registration/2fa_status.html"

    def _contexto(self, request, **extra):
        return {
            "ativo": two_factor.dispositivo_confirmado(request.user) is not None,
            "restantes": two_factor.codigos_de_recuperacao_restantes(request.user),
            **extra,
        }

    def get(self, request):
        # O status do segundo fator mora na página Conta; esta URL segue valendo
        # (links antigos, retorno das telas de configuração).
        return redirect(reverse("accounts:conta") + "#seguranca")

    def post(self, request):
        """Gerar novos códigos de recuperação exige um código do aplicativo
        agora: quem esqueceu a sessão aberta num computador alheio não pode
        trocar a rede de segurança."""
        if not two_factor.dispositivo_confirmado(request.user):
            return redirect("accounts:2fa_configurar")
        if two_factor.bloqueado_por_tentativas(request.user):
            return render_2fa(
                request,
                self.template_name,
                self._contexto(
                    request,
                    erro="Muitas tentativas. Tente novamente em alguns minutos.",
                ),
            )
        if not two_factor.verificar_codigo_totp(
            request.user, request.POST.get("codigo", "")
        ):
            two_factor.registrar_falha(request.user)
            return render_2fa(
                request,
                self.template_name,
                self._contexto(
                    request,
                    erro="Código inválido. Digite o que o aplicativo mostra agora.",
                ),
            )
        two_factor.limpar_falhas(request.user)
        codigos = two_factor.gerar_codigos_de_recuperacao(request.user)
        return render_2fa(
            request,
            "registration/2fa_codigos.html",
            {"codigos": codigos, "recem_ativado": False},
        )


# --------------------------------------------------------------------------
# Dispositivos confiáveis (ADR 0009)
# --------------------------------------------------------------------------


class RevogarDispositivoConfiavelView(LoginRequiredMixin, View):
    """Revoga um dispositivo confiável do próprio usuário. O registro de outro
    usuário responde 404, como fora de escopo (regra 4)."""

    http_method_names = ["post"]

    def post(self, request, pk):
        dispositivo = get_object_or_404(
            TrustedDevice, pk=pk, user=request.user, revoked_at__isnull=True
        )
        trusted_devices.revogar(
            dispositivo, motivo="Revogado pelo próprio usuário", ator=request.user
        )
        messages.success(
            request,
            f"✓ Dispositivo revogado ({dispositivo.label}). "
            "Nele, o código volta a ser pedido na próxima entrada.",
        )
        return redirect(reverse("accounts:conta") + "#seguranca")


class RevogarDispositivosConfiaveisView(LoginRequiredMixin, View):
    """ "Revogar todos": inclusive o deste navegador, que cai na próxima requisição."""

    http_method_names = ["post"]

    def post(self, request):
        quantos = trusted_devices.revogar_todos(
            request.user, motivo="Revogados pelo próprio usuário", ator=request.user
        )
        if quantos:
            messages.success(request, f"✓ {quantos} dispositivo(s) revogado(s).")
        else:
            messages.info(request, "Não havia dispositivo confiável para revogar.")
        return redirect(reverse("accounts:conta") + "#seguranca")
