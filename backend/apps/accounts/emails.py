"""E-mails do gerenciamento de acesso.

Três regras:

1. **Nunca vai senha por e-mail.** Quem recebe uma conta recebe um link para
   *definir* a senha (o mesmo token do "esqueci minha senha", que morre
   quando a senha muda e expira em `PASSWORD_RESET_TIMEOUT`).
2. **Só depois do commit** (`transaction.on_commit`): e-mail de uma ação que
   foi desfeita não pode ter saído.
3. **E-mail com problema não derruba a ação.** Vai pela fila (Celery); se o
   broker estiver fora, tenta na hora; se também falhar, vai para o log. O
   pedido continua na tela de solicitações — o e-mail é aviso, não o registro.
"""

import logging
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.accounts.models import AccessRequest, Role, User
from apps.accounts.tasks import enviar_email

logger = logging.getLogger(__name__)

ASSINATURA = "\n\n--\nRebanho360"


def _linha(texto: str) -> str:
    """Valor de campo livre numa linha só: quebra de linha em assunto de e-mail
    é injeção de cabeçalho."""
    return " ".join(str(texto).split())


def _despachar(assunto: str, corpo: str, destinatarios: list[str]) -> None:
    destinatarios = sorted({d for d in destinatarios if d})
    if not destinatarios:
        return
    assunto = _linha(assunto)

    def enviar():
        try:
            enviar_email.delay(assunto, corpo, destinatarios)
        except Exception:  # broker fora do ar
            logger.warning("Fila de e-mail indisponível; enviando direto.")
            try:
                enviar_email.run(assunto, corpo, destinatarios)
            except Exception:
                logger.exception("Falha ao enviar e-mail '%s'", assunto)

    transaction.on_commit(enviar)


def url_absoluta(base_url: str, nome: str, **kwargs) -> str:
    return urljoin(base_url, reverse(nome, kwargs=kwargs))


def link_de_definir_senha(usuario: User, base_url: str) -> str:
    return url_absoluta(
        base_url,
        "accounts:password_reset_confirm",
        uidb64=urlsafe_base64_encode(force_bytes(usuario.pk)),
        token=default_token_generator.make_token(usuario),
    )


def destinatarios_dos_administradores() -> list[str]:
    from apps.accounts.user_management import administradores_ativos

    emails = list(
        administradores_ativos()
        .exclude(email="")
        .filter(role=Role.ADMIN)
        .values_list("email", flat=True)
    )
    emails += list(getattr(settings, "ACCESS_REQUEST_NOTIFY_EMAILS", []))
    return emails


def avisar_administradores(solicitacao: AccessRequest, base_url: str) -> bool:
    """Devolve `False` quando não há para quem avisar (o pedido segue na tela)."""
    destinatarios = destinatarios_dos_administradores()
    if not destinatarios:
        logger.warning("Solicitação de acesso sem e-mail de administrador para avisar.")
        return False
    corpo = (
        "Há uma nova solicitação de acesso ao Rebanho360.\n\n"
        f"Nome: {_linha(solicitacao.full_name)}\n"
        f"E-mail: {solicitacao.email}\n"
        f"Telefone: {_linha(solicitacao.phone) or '—'}\n\n"
        f"Quem é e por que precisa de acesso:\n{solicitacao.message}\n\n"
        "O e-mail acima não foi confirmado: quem pediu informou o endereço, "
        "mas ninguém provou que é dele. Confira com a pessoa antes de aprovar.\n\n"
        "Aprovar ou recusar:\n"
        f"{url_absoluta(base_url, 'accounts:solicitacoes')}"
        f"{ASSINATURA}"
    )
    _despachar(
        f"Nova solicitação de acesso: {_linha(solicitacao.full_name)}",
        corpo,
        destinatarios,
    )
    return True


def enviar_conta_criada(
    usuario: User, base_url: str, *, aprovada: bool, validade_dias: int
) -> None:
    """Confirmação ao novo usuário: o login e o link para definir a senha."""
    if not usuario.email:
        return
    abertura = (
        "Sua solicitação de acesso ao Rebanho360 foi aprovada."
        if aprovada
        else "Uma conta no Rebanho360 foi criada para você."
    )
    corpo = (
        f"Olá {usuario.get_full_name() or usuario.username},\n\n"
        f"{abertura}\n\n"
        f"Seu usuário (para entrar): {usuario.username}\n"
        f"Seu papel: {usuario.get_role_display()}\n\n"
        "Para começar, defina a sua senha neste link:\n"
        f"{link_de_definir_senha(usuario, base_url)}\n\n"
        f"O link vale por {validade_dias} dias e só funciona uma vez. Depois "
        f"disso, entre em {url_absoluta(base_url, 'accounts:login')}\n\n"
        "Se você não esperava este e-mail, ignore-o."
        f"{ASSINATURA}"
    )
    _despachar(
        (
            "Seu acesso ao Rebanho360 foi aprovado"
            if aprovada
            else "Sua conta no Rebanho360"
        ),
        corpo,
        [usuario.email],
    )


def enviar_link_de_senha(usuario: User, base_url: str, *, validade_dias: int) -> None:
    """Reenvio de convite ou redefinição pedida por um administrador."""
    if not usuario.email:
        return
    corpo = (
        f"Olá {usuario.get_full_name() or usuario.username},\n\n"
        "Um administrador pediu que você defina uma nova senha no Rebanho360.\n\n"
        f"Seu usuário: {usuario.username}\n"
        f"Defina a senha neste link:\n{link_de_definir_senha(usuario, base_url)}\n\n"
        f"O link vale por {validade_dias} dias e só funciona uma vez.\n\n"
        "Se você não esperava este e-mail, avise o administrador do sistema."
        f"{ASSINATURA}"
    )
    _despachar("Defina sua senha no Rebanho360", corpo, [usuario.email])


def enviar_recusa(solicitacao: AccessRequest) -> None:
    """Aviso de recusa, **sem** o motivo: ele é anotação interna."""
    corpo = (
        f"Olá {_linha(solicitacao.full_name)},\n\n"
        "Sua solicitação de acesso ao Rebanho360 não foi aprovada.\n"
        "Se acha que houve engano, fale com quem administra o sistema na sua "
        "fazenda."
        f"{ASSINATURA}"
    )
    _despachar("Sua solicitação de acesso ao Rebanho360", corpo, [solicitacao.email])
