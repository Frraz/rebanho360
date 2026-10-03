"""Telas de gerenciamento de usuários (só `ADMIN`) e a tela pública de
solicitação de acesso. Finas: só HTTP — a regra mora em `user_management`
e `access_requests`."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts import access_requests, selectors, two_factor
from apps.accounts import user_management as usuarios
from apps.accounts.forms import (
    MotivoForm,
    RecusarSolicitacaoForm,
    RedefinirSenhaForm,
    SolicitacaoAcessoForm,
    UsuarioForm,
)
from apps.accounts.models import AccessRequest, AccessRequestStatus, Role
from apps.accounts.permissions import AprovaAcessosMixin, GerenciaUsuariosMixin
from apps.audit.models import AuditEvent
from apps.core.exceptions import BusinessError
from apps.core.request_context import client_ip


def _base_url(request) -> str:
    return request.build_absolute_uri("/")


def _contexto_base(**extra) -> dict:
    """Todas as telas do gerenciamento mostram a contagem de pedidos nas abas."""
    return {"pendentes": selectors.contar_solicitacoes_pendentes(), **extra}


def _erro_de_negocio(request, form, exc: BusinessError) -> None:
    """O erro de regra aparece no topo do formulário, específico."""
    form.add_error(None, str(exc))


# --------------------------------------------------------------------------
# Lista e detalhe
# --------------------------------------------------------------------------


class UsuarioListView(GerenciaUsuariosMixin, View):
    por_pagina = 25

    def get(self, request):
        estado = request.GET.get("estado", "ativos")
        if estado not in dict(selectors.ESTADOS):
            estado = "ativos"
        papel = request.GET.get("papel", "")
        if papel not in Role.values:
            papel = ""
        termo = request.GET.get("q", "")

        lista = selectors.listar_usuarios(
            ator=request.user, termo=termo, papel=papel, estado=estado
        )
        pagina = Paginator(lista, self.por_pagina).get_page(request.GET.get("page"))
        params = request.GET.copy()
        params.pop("page", None)
        return render(
            request,
            "accounts/usuarios/lista.html",
            _contexto_base(
                aba="usuarios",
                pagina=pagina,
                estado=estado,
                estados=selectors.ESTADOS,
                papel=papel,
                papeis=Role.choices,
                termo=termo,
                url_pagina=params.urlencode(),
            ),
        )


class UsuarioDetailView(GerenciaUsuariosMixin, View):
    def get(self, request, pk):
        usuario = get_object_or_404(selectors.usuarios_visiveis(request.user), pk=pk)
        historico = AuditEvent.objects.filter(
            entity_type="User", entity_id=str(usuario.pk)
        ).select_related("actor")[:12]
        return render(
            request,
            "accounts/usuarios/detalhe.html",
            _contexto_base(
                aba="usuarios",
                u=usuario,
                acessos=usuario.farm_access.select_related("farm").order_by(
                    "farm__name"
                ),
                segundo_fator=two_factor.dispositivo_confirmado(usuario),
                historico=historico,
                eu=usuario.pk == request.user.pk,
            ),
        )


# --------------------------------------------------------------------------
# Criar e editar
# --------------------------------------------------------------------------


class UsuarioFormBase(GerenciaUsuariosMixin, View):
    template_name = "accounts/usuarios/form.html"
    modo = "criar"

    def form_context(self, form, **extra):
        return _contexto_base(aba="usuarios", form=form, modo=self.modo, **extra)

    def render_form(self, request, form, **extra):
        return render(request, self.template_name, self.form_context(form, **extra))


class UsuarioCreateView(UsuarioFormBase):
    def get(self, request):
        return self.render_form(request, UsuarioForm(modo="criar"))

    def post(self, request):
        form = UsuarioForm(request.POST, modo="criar")
        if not form.is_valid():
            return self.render_form(request, form)
        dados = form.cleaned_data
        temporaria = dados["senha_modo"] == "temporaria"
        try:
            usuario = usuarios.criar_usuario(
                ator=request.user,
                dados={
                    campo: dados[campo]
                    for campo in (
                        "username",
                        "first_name",
                        "last_name",
                        "email",
                        "phone",
                        "role",
                    )
                },
                acessos=dados["acessos"],
                senha_temporaria=dados["senha"] if temporaria else None,
                base_url=_base_url(request),
            )
        except BusinessError as exc:
            _erro_de_negocio(request, form, exc)
            return self.render_form(request, form)
        if temporaria:
            messages.success(
                request,
                f"✓ Usuário {usuario.username} criado. Passe a senha temporária "
                "por um canal seguro: ele troca no primeiro acesso.",
            )
        else:
            messages.success(
                request,
                f"✓ Usuário {usuario.username} criado. Convite enviado para "
                f"{usuario.email}.",
            )
        return redirect("accounts:usuario_detalhe", pk=usuario.pk)


class UsuarioUpdateView(UsuarioFormBase):
    modo = "editar"

    def _usuario(self, pk):
        return get_object_or_404(selectors.usuarios_visiveis(self.request.user), pk=pk)

    def get(self, request, pk):
        usuario = self._usuario(pk)
        return self.render_form(
            request,
            UsuarioForm(
                modo="editar", usuario=usuario, proprio=usuario.pk == request.user.pk
            ),
            u=usuario,
            eu=usuario.pk == request.user.pk,
        )

    def post(self, request, pk):
        usuario = self._usuario(pk)
        form = UsuarioForm(
            request.POST,
            modo="editar",
            usuario=usuario,
            proprio=usuario.pk == request.user.pk,
        )
        contexto = {"u": usuario, "eu": usuario.pk == request.user.pk}
        if not form.is_valid():
            return self.render_form(request, form, **contexto)
        dados = form.cleaned_data
        try:
            mudou = usuarios.editar_usuario(
                usuario,
                ator=request.user,
                dados={
                    campo: dados[campo]
                    for campo in ("first_name", "last_name", "email", "phone", "role")
                },
                acessos=dados["acessos"],
                motivo=dados["motivo"],
            )
        except BusinessError as exc:
            _erro_de_negocio(request, form, exc)
            return self.render_form(request, form, **contexto)
        if mudou:
            messages.success(request, f"✓ Dados de {usuario.username} atualizados.")
        else:
            messages.info(request, "Nada mudou: os dados já estavam assim.")
        return redirect("accounts:usuario_detalhe", pk=usuario.pk)


# --------------------------------------------------------------------------
# Ações sobre um usuário (todas com motivo)
# --------------------------------------------------------------------------


class AcaoUsuarioView(GerenciaUsuariosMixin, View):
    """GET mostra o que vai acontecer (e o que impede); POST executa, com
    motivo obrigatório. Subclasses definem o texto e `executar()`."""

    template_name = "accounts/usuarios/acao.html"
    form_class = MotivoForm
    titulo = ""
    botao = ""
    perigo = False
    icone = "check"

    def get_usuario(self, pk):
        return get_object_or_404(selectors.usuarios_visiveis(self.request.user), pk=pk)

    def efeitos(self, usuario) -> list[str]:
        return []

    def bloqueios(self, usuario) -> list[str]:
        return []

    def executar(self, request, usuario, form) -> str:
        raise NotImplementedError

    def get_form(self, usuario, data=None):
        return self.form_class(data)

    def _render(self, request, usuario, form):
        bloqueios = self.bloqueios(usuario)
        return render(
            request,
            self.template_name,
            _contexto_base(
                aba="usuarios",
                u=usuario,
                form=form,
                titulo=self.titulo,
                botao=self.botao,
                perigo=self.perigo,
                icone=self.icone,
                efeitos=[] if bloqueios else self.efeitos(usuario),
                bloqueios=bloqueios,
            ),
        )

    def get(self, request, pk):
        usuario = self.get_usuario(pk)
        return self._render(request, usuario, self.get_form(usuario))

    def post(self, request, pk):
        usuario = self.get_usuario(pk)
        form = self.get_form(usuario, request.POST)
        if self.bloqueios(usuario) or not form.is_valid():
            return self._render(request, usuario, form)
        try:
            aviso = self.executar(request, usuario, form)
        except BusinessError as exc:
            _erro_de_negocio(request, form, exc)
            return self._render(request, usuario, form)
        messages.success(request, aviso)
        return redirect("accounts:usuario_detalhe", pk=usuario.pk)


def _sessoes_texto(n: int) -> str:
    if n == 0:
        return "Não há sessão aberta no momento."
    return f"{n} sessão aberta será encerrada: a pessoa precisa entrar de novo."


class DesativarUsuarioView(AcaoUsuarioView):
    titulo = "Desativar usuário"
    botao = "Desativar"
    perigo = True
    icone = "lock"

    def bloqueios(self, usuario):
        if not usuario.is_active:
            return ["Este usuário já está desativado."]
        return usuarios.bloqueios_para_remover(usuario, self.request.user, "desativar")

    def efeitos(self, usuario):
        return [
            "A pessoa não consegue mais entrar, mesmo com a senha correta.",
            _sessoes_texto(usuarios.contar_sessoes(usuario)),
            "Tudo o que ela lançou continua no sistema e na auditoria.",
            "Dá para reativar a qualquer momento.",
        ]

    def executar(self, request, usuario, form):
        usuarios.desativar_usuario(
            usuario, ator=request.user, motivo=form.cleaned_data["motivo"]
        )
        return f"✓ {usuario.username} desativado."


class ReativarUsuarioView(AcaoUsuarioView):
    titulo = "Reativar usuário"
    botao = "Reativar"

    def bloqueios(self, usuario):
        if usuario.deleted_at:
            return ["Este usuário está excluído. Restaure-o antes."]
        if usuario.is_active:
            return ["Este usuário já está ativo."]
        return []

    def efeitos(self, usuario):
        return [
            "A pessoa volta a poder entrar, com a mesma senha, papel e fazendas de antes."
        ]

    def executar(self, request, usuario, form):
        usuarios.reativar_usuario(
            usuario, ator=request.user, motivo=form.cleaned_data["motivo"]
        )
        return f"✓ {usuario.username} reativado."


class ExcluirUsuarioView(AcaoUsuarioView):
    titulo = "Excluir usuário"
    botao = "Excluir"
    perigo = True
    icone = "trash-2"

    def bloqueios(self, usuario):
        if usuario.deleted_at:
            return ["Este usuário já foi excluído."]
        return usuarios.bloqueios_para_remover(usuario, self.request.user, "excluir")

    def efeitos(self, usuario):
        return [
            "A conta sai da lista e do login.",
            _sessoes_texto(usuarios.contar_sessoes(usuario)),
            "Nada sai do banco: o que ela lançou e o histórico dela continuam na "
            "auditoria, com o nome dela.",
            "O e-mail dela fica livre para outra conta.",
            "Dá para restaurar depois (volta desativada, para você conferir).",
        ]

    def executar(self, request, usuario, form):
        usuarios.excluir_usuario(
            usuario, ator=request.user, motivo=form.cleaned_data["motivo"]
        )
        return f"✓ {usuario.username} excluído. Ele continua na auditoria."


class RestaurarUsuarioView(AcaoUsuarioView):
    titulo = "Restaurar usuário"
    botao = "Restaurar"
    icone = "rotate-ccw"

    def bloqueios(self, usuario):
        return [] if usuario.deleted_at else ["Este usuário não está excluído."]

    def efeitos(self, usuario):
        return [
            "A conta volta para a lista, ainda desativada.",
            "Confira os dados e use Reativar para devolver o acesso.",
        ]

    def executar(self, request, usuario, form):
        usuarios.restaurar_usuario(
            usuario, ator=request.user, motivo=form.cleaned_data["motivo"]
        )
        return f"✓ {usuario.username} restaurado. Reative para devolver o acesso."


class EncerrarSessoesView(AcaoUsuarioView):
    titulo = "Encerrar sessões"
    botao = "Encerrar sessões"
    perigo = True

    def efeitos(self, usuario):
        return [
            _sessoes_texto(usuarios.contar_sessoes(usuario)),
            "A conta continua ativa: a pessoa entra de novo com usuário e senha.",
            "Use quando alguém esqueceu o sistema aberto num aparelho que não é dele.",
        ]

    def executar(self, request, usuario, form):
        n = usuarios.encerrar_sessoes_do_usuario(
            usuario, ator=request.user, motivo=form.cleaned_data["motivo"]
        )
        return f"✓ {n} sessão(ões) de {usuario.username} encerrada(s)."


class RedefinirSegundoFatorView(AcaoUsuarioView):
    titulo = "Redefinir segundo fator"
    botao = "Redefinir segundo fator"
    perigo = True

    def bloqueios(self, usuario):
        if usuario.pk == self.request.user.pk:
            return [
                "Você não pode redefinir o seu próprio segundo fator: peça a outro "
                "administrador."
            ]
        if not two_factor.dispositivo_confirmado(usuario):
            return ["Este usuário não usa segundo fator."]
        return []

    def efeitos(self, usuario):
        return [
            "O aplicativo autenticador e os códigos de recuperação dele são apagados.",
            "As sessões abertas são encerradas.",
            "Ele volta a entrar só com a senha, até ativar o segundo fator de novo.",
            "Use só para quem perdeu o celular e os códigos de recuperação.",
        ]

    def executar(self, request, usuario, form):
        usuarios.redefinir_segundo_fator(
            usuario, ator=request.user, motivo=form.cleaned_data["motivo"]
        )
        return f"✓ Segundo fator de {usuario.username} redefinido."


class RedefinirSenhaView(AcaoUsuarioView):
    titulo = "Redefinir senha"
    botao = "Redefinir senha"
    form_class = RedefinirSenhaForm
    template_name = "accounts/usuarios/senha.html"
    icone = "lock"

    def get_form(self, usuario, data=None):
        return RedefinirSenhaForm(data, usuario=usuario)

    def bloqueios(self, usuario):
        if usuario.deleted_at:
            return ["Este usuário está excluído. Restaure-o antes."]
        if usuario.pk == self.request.user.pk:
            return ["Para a sua própria senha, use Alterar senha no menu do usuário."]
        return []

    def efeitos(self, usuario):
        return []

    def executar(self, request, usuario, form):
        dados = form.cleaned_data
        if dados["modo"] == "temporaria":
            n = usuarios.definir_senha_temporaria(
                usuario, ator=request.user, senha=dados["senha"], motivo=dados["motivo"]
            )
            return (
                f"✓ Senha temporária de {usuario.username} definida"
                f"{f' ({n} sessão(ões) encerrada(s))' if n else ''}. Passe-a por um "
                "canal seguro: ele troca no primeiro acesso."
            )
        usuarios.enviar_link_de_senha(
            usuario,
            ator=request.user,
            motivo=dados["motivo"],
            base_url=_base_url(request),
        )
        return f"✓ Link para definir a senha enviado para {usuario.email}."


# --------------------------------------------------------------------------
# Solicitações de acesso (administrador e gestor)
# --------------------------------------------------------------------------

SITUACOES = (
    ("PENDENTE", "Pendentes"),
    ("APROVADA", "Aprovadas"),
    ("RECUSADA", "Recusadas"),
    ("todas", "Todas"),
)


class SolicitacaoListView(AprovaAcessosMixin, View):
    por_pagina = 25

    def get(self, request):
        situacao = request.GET.get("situacao", "PENDENTE")
        if situacao not in dict(SITUACOES):
            situacao = "PENDENTE"
        lista = selectors.listar_solicitacoes(situacao=situacao)
        pagina = Paginator(lista, self.por_pagina).get_page(request.GET.get("page"))
        params = request.GET.copy()
        params.pop("page", None)
        return render(
            request,
            "accounts/solicitacoes/lista.html",
            _contexto_base(
                aba="solicitacoes",
                pagina=pagina,
                situacao=situacao,
                situacoes=SITUACOES,
                url_pagina=params.urlencode(),
            ),
        )


class SolicitacaoDecisaoBase(AprovaAcessosMixin, View):
    def get_solicitacao(self, pk) -> AccessRequest:
        return get_object_or_404(AccessRequest, pk=pk)

    def ja_decidida(self, request, solicitacao):
        messages.warning(
            request,
            f"Esta solicitação já foi {solicitacao.get_status_display().lower()}"
            f"{f' por {solicitacao.decided_by}' if solicitacao.decided_by else ''}.",
        )
        return redirect("accounts:solicitacoes")


class AprovarSolicitacaoView(SolicitacaoDecisaoBase):
    template_name = "accounts/solicitacoes/aprovar.html"

    def _render(self, request, solicitacao, form):
        return render(
            request,
            self.template_name,
            _contexto_base(
                aba="solicitacoes", s=solicitacao, form=form, modo="aprovar"
            ),
        )

    def get(self, request, pk):
        solicitacao = self.get_solicitacao(pk)
        if solicitacao.status != AccessRequestStatus.PENDENTE:
            return self.ja_decidida(request, solicitacao)
        return self._render(
            request,
            solicitacao,
            UsuarioForm(modo="aprovar", solicitacao=solicitacao, ator=request.user),
        )

    def post(self, request, pk):
        solicitacao = self.get_solicitacao(pk)
        if solicitacao.status != AccessRequestStatus.PENDENTE:
            return self.ja_decidida(request, solicitacao)
        form = UsuarioForm(
            request.POST, modo="aprovar", solicitacao=solicitacao, ator=request.user
        )
        if not form.is_valid():
            return self._render(request, solicitacao, form)
        dados = form.cleaned_data
        try:
            usuario = access_requests.aprovar_solicitacao(
                solicitacao,
                ator=request.user,
                dados={
                    campo: dados[campo]
                    for campo in (
                        "username",
                        "first_name",
                        "last_name",
                        "phone",
                        "role",
                    )
                },
                acessos=dados["acessos"],
                base_url=_base_url(request),
            )
        except BusinessError as exc:
            _erro_de_negocio(request, form, exc)
            return self._render(request, solicitacao, form)
        messages.success(
            request,
            f"✓ Acesso aprovado. A conta {usuario.username} foi criada e o e-mail "
            f"de confirmação, com o link para definir a senha, foi enviado para "
            f"{usuario.email}.",
        )
        return redirect("accounts:usuario_detalhe", pk=usuario.pk)


class RecusarSolicitacaoView(SolicitacaoDecisaoBase):
    template_name = "accounts/solicitacoes/recusar.html"

    def _render(self, request, solicitacao, form):
        return render(
            request,
            self.template_name,
            _contexto_base(aba="solicitacoes", s=solicitacao, form=form),
        )

    def get(self, request, pk):
        solicitacao = self.get_solicitacao(pk)
        if solicitacao.status != AccessRequestStatus.PENDENTE:
            return self.ja_decidida(request, solicitacao)
        return self._render(request, solicitacao, RecusarSolicitacaoForm())

    def post(self, request, pk):
        solicitacao = self.get_solicitacao(pk)
        if solicitacao.status != AccessRequestStatus.PENDENTE:
            return self.ja_decidida(request, solicitacao)
        form = RecusarSolicitacaoForm(request.POST)
        if not form.is_valid():
            return self._render(request, solicitacao, form)
        try:
            access_requests.recusar_solicitacao(
                solicitacao,
                ator=request.user,
                motivo=form.cleaned_data["motivo"],
                avisar=form.cleaned_data["avisar"],
            )
        except BusinessError as exc:
            _erro_de_negocio(request, form, exc)
            return self._render(request, solicitacao, form)
        messages.success(request, f"✓ Solicitação de {solicitacao.full_name} recusada.")
        return redirect("accounts:solicitacoes")


# --------------------------------------------------------------------------
# Tela pública
# --------------------------------------------------------------------------


class SolicitarAcessoView(View):
    template_name = "registration/solicitar_acesso.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("dashboards:inicio")
        return render(request, self.template_name, {"form": SolicitacaoAcessoForm()})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect("dashboards:inicio")
        ip = client_ip(request)
        form = SolicitacaoAcessoForm(request.POST)

        if access_requests.limite_por_ip_excedido(ip):
            form.add_error(
                None,
                "Muitas solicitações deste endereço. Tente de novo em uma hora.",
            )
            return render(request, self.template_name, {"form": form}, status=429)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        access_requests.contar_envio(ip)
        # Robô preencheu a isca: parece sucesso, não grava nada.
        if not form.parece_robo:
            dados = form.cleaned_data
            access_requests.registrar_solicitacao(
                nome=dados["full_name"],
                email=dados["email"],
                telefone=dados["phone"],
                mensagem=dados["message"],
                ip=ip,
                base_url=_base_url(request),
            )
        return redirect("accounts:solicitar_acesso_enviado")


class SolicitacaoEnviadaView(View):
    def get(self, request):
        return render(request, "registration/solicitar_acesso_enviado.html")
