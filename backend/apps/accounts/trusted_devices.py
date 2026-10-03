"""Dispositivo confiável — "Confiar neste dispositivo" no segundo fator (ADR 0009).

Quem prova o segundo fator e marca a caixa recebe um cookie com um token
aleatório; no banco fica só o HMAC dele (`TrustedDevice.token_hash`). Nas
próximas entradas, com a senha correta e o cookie válido, o código não é
pedido de novo — e a sessão naquele navegador dura `TRUSTED_SESSION_DAYS`,
com logout depois de `TRUSTED_IDLE_HOURS` sem uso.

O que **não** muda: a senha continua valendo em todo login, o rate limit
também, e o cookie só serve para o usuário a quem foi dado.

Regras:

1. Só o HMAC do token vai ao banco; o token em texto só existe no cookie.
2. Vale `TRUSTED_DEVICE_DAYS` dias a partir do último uso, nunca além de
   `TRUSTED_DEVICE_MAX_DAYS` dias desde que foi dado.
3. Mudar de IP **não** revoga (celular/4G troca de IP o tempo todo): fica
   na auditoria e a página Conta avisa. A defesa é o token secreto.
4. Troca de senha, redefinição do segundo fator, sessões encerradas pelo
   administrador e desativação revogam os dispositivos do usuário.
"""

import datetime
import hashlib
import hmac
import secrets
import time

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import TrustedDevice, User
from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.request_context import client_ip

SESSION_DISPOSITIVO = "dispositivo_confiavel_id"
SESSION_ATIVIDADE = "ultima_atividade"

#: A atividade é gravada na sessão no máximo a cada tanto — senão toda
#: requisição reescreveria a sessão no banco.
GRAVAR_ATIVIDADE_A_CADA = 5 * 60
#: `last_used_at` e a renovação da janela seguem o mesmo princípio.
GRAVAR_USO_A_CADA = 60 * 60


def _hash_do_token(token: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(),
        b"dispositivo-confiavel:" + token.encode(),
        hashlib.sha256,
    ).hexdigest()


def rotulo_do_navegador(user_agent: str) -> str:
    """ "Chrome no Linux" — só para a pessoa reconhecer o dispositivo na lista.
    Heurística simples de propósito: um rótulo errado não afeta a segurança."""
    ua = user_agent or ""
    navegador = "Navegador"
    # A ordem importa: Edge e Opera também dizem "Chrome"; Chrome diz "Safari".
    for marca, nome in (
        ("Edg/", "Edge"),
        ("OPR/", "Opera"),
        ("Firefox/", "Firefox"),
        ("Chrome/", "Chrome"),
        ("CriOS/", "Chrome"),
        ("Safari/", "Safari"),
    ):
        if marca in ua:
            navegador = nome
            break
    sistema = ""
    for marca, nome in (
        ("Android", "Android"),
        ("iPhone", "iPhone"),
        ("iPad", "iPad"),
        ("Windows", "Windows"),
        ("Macintosh", "Mac"),
        ("Linux", "Linux"),
    ):
        if marca in ua:
            sistema = nome
            break
    return f"{navegador} no {sistema}" if sistema else navegador


# --------------------------------------------------------------------------
# Dar, conferir e renovar a confiança
# --------------------------------------------------------------------------


def confiar_neste_dispositivo(request, response) -> TrustedDevice:
    """Chamado logo depois de o segundo fator ser provado. Cria o registro,
    põe o cookie na resposta e torna longa a sessão atual."""
    agora = timezone.now()
    token = secrets.token_urlsafe(32)
    ip = client_ip(request)
    agente = request.META.get("HTTP_USER_AGENT", "")[:400]
    dispositivo = TrustedDevice.objects.create(
        user=request.user,
        token_hash=_hash_do_token(token),
        label=rotulo_do_navegador(agente),
        user_agent=agente,
        created_ip=ip,
        last_ip=ip,
        last_used_at=agora,
        expires_at=agora + datetime.timedelta(days=settings.TRUSTED_DEVICE_DAYS),
        absolute_expires_at=agora
        + datetime.timedelta(days=settings.TRUSTED_DEVICE_MAX_DAYS),
    )
    response.set_cookie(
        settings.TRUSTED_DEVICE_COOKIE,
        token,
        max_age=settings.TRUSTED_DEVICE_MAX_DAYS * 24 * 60 * 60,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
    )
    tornar_sessao_longa(request, dispositivo)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity_type="TrustedDevice",
        entity_id=str(dispositivo.pk),
        reason=f"Dispositivo marcado como confiável ({dispositivo.label})",
        actor=request.user,
    )
    return dispositivo


def dispositivo_valido(request) -> TrustedDevice | None:
    """O dispositivo a que o cookie desta requisição dá direito, ou `None`.
    Todo motivo de recusa é igual por fora: não ensina nada a quem tenta."""
    token = request.COOKIES.get(settings.TRUSTED_DEVICE_COOKIE)
    if not token:
        return None
    agora = timezone.now()
    return TrustedDevice.objects.filter(
        token_hash=_hash_do_token(token),
        user=request.user,
        revoked_at__isnull=True,
        expires_at__gt=agora,
        absolute_expires_at__gt=agora,
    ).first()


def _dispositivo_da_sessao(request) -> TrustedDevice | None:
    """O dispositivo a que a sessão longa está presa, se ainda vale."""
    agora = timezone.now()
    return TrustedDevice.objects.filter(
        pk=request.session.get(SESSION_DISPOSITIVO),
        user=request.user,
        revoked_at__isnull=True,
        expires_at__gt=agora,
        absolute_expires_at__gt=agora,
    ).first()


def tornar_sessao_longa(request, dispositivo: TrustedDevice) -> None:
    """Sessão que sobrevive ao navegador fechado, presa a este dispositivo."""
    request.session.set_expiry(settings.TRUSTED_SESSION_DAYS * 24 * 60 * 60)
    request.session[SESSION_DISPOSITIVO] = dispositivo.pk
    request.session[SESSION_ATIVIDADE] = int(time.time())


def registrar_uso(dispositivo: TrustedDevice, request) -> None:
    """Renova a janela e anota o IP. IP novo é gravado na hora e auditado;
    o resto, no máximo uma vez por hora. Não revoga em nenhum caso."""
    agora = timezone.now()
    ip = client_ip(request)
    mudou_o_ip = bool(ip) and ip != dispositivo.last_ip
    if not mudou_o_ip and (
        (agora - dispositivo.last_used_at).total_seconds() < GRAVAR_USO_A_CADA
    ):
        return
    campos = {
        "last_used_at": agora,
        "expires_at": min(
            agora + datetime.timedelta(days=settings.TRUSTED_DEVICE_DAYS),
            dispositivo.absolute_expires_at,
        ),
    }
    if mudou_o_ip:
        campos["last_ip"] = ip
    TrustedDevice.objects.filter(pk=dispositivo.pk).update(**campos)
    if mudou_o_ip:
        registrar_auditoria(
            action=AuditAction.UPDATE,
            entity_type="TrustedDevice",
            entity_id=str(dispositivo.pk),
            reason=(
                "Dispositivo confiável usado de IP novo: "
                f"{dispositivo.last_ip or 'desconhecido'} → {ip}"
            ),
            actor=request.user,
        )


def motivo_para_encerrar_a_sessao(request) -> str | None:
    """Para a sessão longa: por que ela deve cair agora, ou `None` se segue.
    De passagem, renova o dispositivo e a marca de atividade."""
    dispositivo = _dispositivo_da_sessao(request)
    if dispositivo is None:
        return "Dispositivo confiável revogado ou vencido"
    agora = int(time.time())
    ultima = request.session.get(SESSION_ATIVIDADE, 0)
    if agora - ultima > settings.TRUSTED_IDLE_HOURS * 60 * 60:
        return "Sessão encerrada por inatividade"
    if agora - ultima > GRAVAR_ATIVIDADE_A_CADA:
        request.session[SESSION_ATIVIDADE] = agora
    registrar_uso(dispositivo, request)
    return None


# --------------------------------------------------------------------------
# Revogar
# --------------------------------------------------------------------------


def revogar(dispositivo: TrustedDevice, *, motivo: str, ator=None) -> None:
    """A sessão presa a este dispositivo cai na próxima requisição
    (`SessaoLongaMiddleware`), sem varrer a tabela de sessões."""
    if dispositivo.revoked_at is not None:
        return
    TrustedDevice.objects.filter(pk=dispositivo.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoked_reason=motivo[:200]
    )
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity_type="TrustedDevice",
        entity_id=str(dispositivo.pk),
        reason=f"Dispositivo confiável revogado ({dispositivo.label}): {motivo}",
        actor=ator,
    )


def revogar_todos(
    usuario: User, *, motivo: str, ator=None, exceto_id: int | None = None
) -> int:
    """Revoga todos os dispositivos ativos do usuário (menos `exceto_id`).
    Devolve quantos. Só audita se havia o que revogar."""
    ativos = TrustedDevice.objects.filter(user=usuario, revoked_at__isnull=True)
    if exceto_id is not None:
        ativos = ativos.exclude(pk=exceto_id)
    quantos = ativos.update(revoked_at=timezone.now(), revoked_reason=motivo[:200])
    if quantos:
        registrar_auditoria(
            action=AuditAction.UPDATE,
            entity_type="TrustedDevice",
            entity_id=str(usuario.pk),
            reason=f"Dispositivos confiáveis revogados ({quantos}): {motivo}",
            actor=ator,
        )
    return quantos


def dispositivos_ativos(usuario: User):
    agora = timezone.now()
    return TrustedDevice.objects.filter(
        user=usuario,
        revoked_at__isnull=True,
        expires_at__gt=agora,
        absolute_expires_at__gt=agora,
    )


def limpar_antigos() -> int:
    """Apaga o que venceu ou foi revogado há mais de 30 dias. A trilha de
    quem confiou em quê fica na auditoria, que é imutável."""
    limite = timezone.now() - datetime.timedelta(days=30)
    apagados, _ = (
        TrustedDevice.objects.filter(expires_at__lt=limite)
        | TrustedDevice.objects.filter(revoked_at__lt=limite)
    ).delete()
    return apagados
