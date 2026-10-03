"""Solicitação de acesso: quem não tem conta pede; o administrador decide.

A tela de pedido é **pública**, então tudo aqui parte de que quem chama pode
ser um robô ou alguém mal-intencionado:

- A resposta é **sempre a mesma**, exista ou não conta com o e-mail, já haja
  ou não pedido pendente. Quem digita não descobre quem tem acesso.
- Há limite por IP, e um teto de e-mails por hora para os administradores: um
  enxame de pedidos não vira enxurrada na caixa deles. Passou do teto, o
  pedido é gravado do mesmo jeito e aparece na tela — só o aviso por e-mail
  é suprimido.
- Aprovar **não** aceita senha de ninguém: cria a conta sem senha e manda ao
  e-mail do pedido o link para definir a dela. Só o dono do e-mail entra, e
  esse é o único jeito de confirmar que o endereço é dele.
"""

import logging

from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts import emails
from apps.accounts import user_management as usuarios
from apps.accounts.models import AccessRequest, AccessRequestStatus, User
from apps.accounts.permissions import pode_aprovar_acessos
from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.exceptions import BusinessError

logger = logging.getLogger(__name__)

LIMITE_POR_IP = 5
JANELA_POR_IP = 60 * 60
TETO_DE_AVISOS_POR_HORA = 20


# --------------------------------------------------------------------------
# Limites da tela pública
# --------------------------------------------------------------------------


def _chave_ip(ip: str | None) -> str:
    return f"acesso_solicitacoes:ip:{ip or 'desconhecido'}"


def limite_por_ip_excedido(ip: str | None) -> bool:
    return cache.get(_chave_ip(ip), 0) >= LIMITE_POR_IP


def contar_envio(ip: str | None) -> None:
    chave = _chave_ip(ip)
    cache.set(chave, cache.get(chave, 0) + 1, JANELA_POR_IP)


def _pode_avisar_por_email() -> bool:
    chave = "acesso_solicitacoes:avisos"
    cache.add(chave, 0, JANELA_POR_IP)
    try:
        return cache.incr(chave) <= TETO_DE_AVISOS_POR_HORA
    except ValueError:
        return True


# --------------------------------------------------------------------------
# Pedir
# --------------------------------------------------------------------------


def registrar_solicitacao(
    *,
    nome: str,
    email: str,
    telefone: str,
    mensagem: str,
    ip: str | None,
    base_url: str,
) -> AccessRequest | None:
    """Grava o pedido e avisa os administradores. Devolve `None` quando não
    houve pedido novo (já existe conta ou pedido pendente com o e-mail) — a
    view responde igual nos dois casos."""
    email = email.strip().lower()

    if usuarios.email_em_uso(email):
        logger.info("Solicitação de acesso ignorada: e-mail já tem conta.")
        return None
    if AccessRequest.objects.filter(
        email__iexact=email, status=AccessRequestStatus.PENDENTE
    ).exists():
        logger.info("Solicitação de acesso ignorada: já há pedido pendente.")
        return None

    try:
        with transaction.atomic():
            solicitacao = AccessRequest.objects.create(
                full_name=nome,
                email=email,
                phone=telefone,
                message=mensagem,
                ip_address=ip,
            )
            registrar_auditoria(
                action=AuditAction.CREATE,
                entity=solicitacao,
                after={
                    "full_name": nome,
                    "email": email,
                    "phone": telefone,
                    "status": solicitacao.status,
                },
                reason="Solicitação de acesso feita pela tela pública",
            )
    except IntegrityError:  # dois cliques ao mesmo tempo
        return None

    if _pode_avisar_por_email():
        emails.avisar_administradores(solicitacao, base_url)
    else:
        logger.warning("Teto de avisos por e-mail atingido; pedido só na tela.")
    return solicitacao


# --------------------------------------------------------------------------
# Decidir
# --------------------------------------------------------------------------


def _travar_pendente(solicitacao: AccessRequest) -> AccessRequest:
    """Duas pessoas decidindo o mesmo pedido: a segunda recebe o que a primeira fez."""
    atual = AccessRequest.objects.select_for_update().get(pk=solicitacao.pk)
    if atual.status != AccessRequestStatus.PENDENTE:
        quem = atual.decided_by or "outro administrador"
        quando = timezone.localtime(atual.decided_at).strftime("%d/%m/%Y %H:%M")
        raise BusinessError(
            f"Esta solicitação já foi {atual.get_status_display().lower()} "
            f"por {quem} em {quando}."
        )
    return atual


@transaction.atomic
def aprovar_solicitacao(
    solicitacao: AccessRequest, *, ator, dados: dict, acessos: dict, base_url: str
) -> User:
    """Cria a conta com o papel e as fazendas que o administrador escolheu e
    envia ao solicitante o e-mail de confirmação com o link da senha."""
    if not pode_aprovar_acessos(ator):
        raise PermissionDenied("Só administrador ou gestor decide solicitações.")
    solicitacao = _travar_pendente(solicitacao)
    # O e-mail é o do pedido: é para ele que o link de senha vai.
    usuario = usuarios.criar_usuario(
        ator=ator,
        dados={**dados, "email": solicitacao.email},
        acessos=acessos,
        base_url=base_url,
        veio_de_solicitacao=True,
    )
    solicitacao.status = AccessRequestStatus.APROVADA
    solicitacao.decided_at = timezone.now()
    solicitacao.decided_by = ator
    solicitacao.user = usuario
    solicitacao.save(update_fields=["status", "decided_at", "decided_by", "user"])
    registrar_auditoria(
        action=AuditAction.APPROVE,
        entity=solicitacao,
        before={"status": AccessRequestStatus.PENDENTE},
        after={"status": solicitacao.status, "user": usuario.username},
        changed_fields=["status"],
        reason=f"Aprovada: conta '{usuario.username}' criada como {usuario.get_role_display()}",
        actor=ator,
    )
    return usuario


@transaction.atomic
def recusar_solicitacao(
    solicitacao: AccessRequest, *, ator, motivo: str, avisar: bool
) -> None:
    if not pode_aprovar_acessos(ator):
        raise PermissionDenied("Só administrador ou gestor decide solicitações.")
    motivo = (motivo or "").strip()
    if not motivo:
        raise BusinessError("Informe o motivo: ele fica registrado na auditoria.")
    solicitacao = _travar_pendente(solicitacao)
    solicitacao.status = AccessRequestStatus.RECUSADA
    solicitacao.decided_at = timezone.now()
    solicitacao.decided_by = ator
    solicitacao.decision_reason = motivo
    solicitacao.save(
        update_fields=["status", "decided_at", "decided_by", "decision_reason"]
    )
    registrar_auditoria(
        action=AuditAction.CANCEL,
        entity=solicitacao,
        before={"status": AccessRequestStatus.PENDENTE},
        after={"status": solicitacao.status},
        changed_fields=["status"],
        reason=f"Recusada: {motivo}",
        actor=ator,
    )
    if avisar:
        emails.enviar_recusa(solicitacao)
