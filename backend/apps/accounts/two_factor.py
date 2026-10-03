"""Segundo fator por TOTP (RFC 6238) — F4-09.

Código nosso, sem biblioteca de OTP: são ~30 linhas, testadas contra os
vetores da própria RFC, e não há o que atualizar nem auditar em terceiros.
O QR code é a única coisa que vem de fora (`segno`, Python puro).

Segurança, em ordem de importância:

1. O segredo nunca vai para log, auditoria ou URL.
2. O mesmo código não vale duas vezes (`last_used_step`).
3. Tentativas erradas têm limite (5 em 15 minutos, por usuário).
4. Códigos de recuperação valem uma vez e ficam guardados só como HMAC.
5. Recuperar é possível: perdeu o celular → código de recuperação; perdeu os
   dois → `ADMIN` (tela do admin) ou `manage.py resetar_segundo_fator`, e
   ambos deixam rastro na auditoria.
"""

import base64
import datetime
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.accounts import trusted_devices
from apps.accounts.models import RecoveryCode, TOTPDevice, TrustedDevice, User
from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria

PASSO_EM_SEGUNDOS = 30
DIGITOS = 6
SESSION_OTP_VERIFICADO = "otp_verificado_em"

#: Sem 0/O, 1/I/L: o código de recuperação é copiado à mão de um papel.
ALFABETO_DE_RECUPERACAO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
QUANTOS_CODIGOS = 10
TAMANHO_DO_CODIGO = 10

LIMITE_DE_TENTATIVAS = 5
JANELA_DE_TENTATIVAS = 15 * 60


# --------------------------------------------------------------------------
# TOTP (RFC 4226 / 6238)
# --------------------------------------------------------------------------


def gerar_segredo() -> str:
    """160 bits em base32 — o que os aplicativos esperam."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _hotp(segredo: str, contador: int) -> str:
    chave = base64.b32decode(segredo.upper(), casefold=True)
    digest = hmac.new(chave, struct.pack(">Q", contador), hashlib.sha1).digest()
    deslocamento = digest[-1] & 0x0F
    numero = (
        struct.unpack(">I", digest[deslocamento : deslocamento + 4])[0] & 0x7FFFFFFF
    )
    return str(numero % (10**DIGITOS)).zfill(DIGITOS)


def passo_atual(agora: float | None = None) -> int:
    return int((agora if agora is not None else time.time()) // PASSO_EM_SEGUNDOS)


def codigo_totp(segredo: str, passo: int) -> str:
    return _hotp(segredo, passo)


def passo_do_codigo(
    segredo: str, codigo: str, *, agora: float | None = None
) -> int | None:
    """O passo (janela de 30 s) em que `codigo` é válido, ou `None`.
    Aceita `TWO_FACTOR_WINDOW` passos para cada lado do atual."""
    codigo = "".join(ch for ch in (codigo or "") if ch.isdigit())
    if len(codigo) != DIGITOS:
        return None
    atual = passo_atual(agora)
    janela = settings.TWO_FACTOR_WINDOW
    for passo in range(atual - janela, atual + janela + 1):
        if hmac.compare_digest(_hotp(segredo, passo), codigo):
            return passo
    return None


def uri_de_provisionamento(usuario: User, segredo: str) -> str:
    emissor = settings.TWO_FACTOR_ISSUER
    rotulo = quote(f"{emissor}:{usuario.get_username()}")
    return (
        f"otpauth://totp/{rotulo}?secret={segredo}&issuer={quote(emissor)}"
        f"&algorithm=SHA1&digits={DIGITOS}&period={PASSO_EM_SEGUNDOS}"
    )


def qr_svg(uri: str) -> str:
    """O QR code como SVG embutido na página — nada de URL com o segredo."""
    import segno
    from django.utils.safestring import mark_safe

    # SVG gerado aqui, a partir de dados nossos: seguro para embutir.
    return mark_safe(  # noqa: S308
        segno.make(uri, error="m").svg_inline(
            scale=5, border=2, dark="#0a1d27", title="QR code do segundo fator"
        )
    )


# --------------------------------------------------------------------------
# Quem precisa, e o estado de cada um
# --------------------------------------------------------------------------


def dispositivo_confirmado(usuario: User) -> TOTPDevice | None:
    return TOTPDevice.objects.filter(user=usuario, confirmed=True).first()


def precisa_de_segundo_fator(usuario: User) -> bool:
    """O segundo fator é **opcional**, mas recomendado a todos: quem o ativou
    sempre confirma a cada entrada; quem não ativou entra só com a senha.

    Com `TWO_FACTOR_OBRIGATORIO` ligado (o cliente o manteve desligado), vale
    para todos: quem ainda não ativou é levado à configuração antes de usar o
    sistema."""
    return (
        bool(settings.TWO_FACTOR_OBRIGATORIO)
        or dispositivo_confirmado(usuario) is not None
    )


#: De quanto em quanto tempo o aviso volta, depois de "Agora não".
DIAS_DO_LEMBRETE = 14


def recomenda_segundo_fator(usuario: User) -> bool:
    """Quem ainda não ativou: a tela de Início sugere, sem cobrar — e, depois de
    "Agora não", só volta a sugerir passadas `DIAS_DO_LEMBRETE` dias. Quando o
    segundo fator é obrigatório, não há o que sugerir: o sistema já cobra."""
    if settings.TWO_FACTOR_OBRIGATORIO or dispositivo_confirmado(usuario) is not None:
        return False
    adiado_ate = usuario.two_factor_reminder_until
    return adiado_ate is None or timezone.now() >= adiado_ate


def adiar_lembrete(usuario: User) -> None:
    """ "Agora não": esconde o aviso por `DIAS_DO_LEMBRETE` dias."""
    usuario.two_factor_reminder_until = timezone.now() + datetime.timedelta(
        days=DIAS_DO_LEMBRETE
    )
    usuario.save(update_fields=["two_factor_reminder_until"])


def sessao_verificada(request) -> bool:
    return bool(request.session.get(SESSION_OTP_VERIFICADO))


def marcar_sessao_verificada(request, dispositivo: TrustedDevice | None = None) -> None:
    """Prova de segundo fator vale para esta sessão. Troca a chave da sessão
    (fixação de sessão). Em dispositivo confiável a sessão é longa; fora dele,
    perfil sensível (`TWO_FACTOR_ROLES`) faz o cookie morrer ao fechar o
    navegador (seguranca/01#sessão)."""
    request.session.cycle_key()
    request.session[SESSION_OTP_VERIFICADO] = timezone.now().isoformat()
    if dispositivo is not None:
        trusted_devices.tornar_sessao_longa(request, dispositivo)
    elif request.user.role in settings.TWO_FACTOR_ROLES:
        request.session.set_expiry(0)


# --------------------------------------------------------------------------
# Limite de tentativas
# --------------------------------------------------------------------------


def _chave(usuario: User) -> str:
    return f"otp_falhas:{usuario.pk}"


def bloqueado_por_tentativas(usuario: User) -> bool:
    return cache.get(_chave(usuario), 0) >= LIMITE_DE_TENTATIVAS


def registrar_falha(usuario: User) -> None:
    cache.set(_chave(usuario), cache.get(_chave(usuario), 0) + 1, JANELA_DE_TENTATIVAS)
    registrar_auditoria(
        action=AuditAction.LOGIN_FAILED,
        entity_type="User",
        entity_id=str(usuario.pk),
        reason="Código do segundo fator inválido",
        actor=usuario,
    )


def limpar_falhas(usuario: User) -> None:
    cache.delete(_chave(usuario))


# --------------------------------------------------------------------------
# Configurar, verificar, recuperar
# --------------------------------------------------------------------------


@transaction.atomic
def iniciar_configuracao(usuario: User) -> TOTPDevice:
    """Cria o dispositivo pendente — ou reaproveita o que já está pendente,
    para recarregar a página não trocar o segredo que o usuário já escaneou."""
    dispositivo, _ = TOTPDevice.objects.select_for_update().get_or_create(
        user=usuario, defaults={"secret": gerar_segredo()}
    )
    return dispositivo


@transaction.atomic
def confirmar_configuracao(usuario: User, codigo: str) -> list[str] | None:
    """Prova que o aplicativo gera os códigos. Devolve os códigos de
    recuperação (em texto, a única vez) ou `None` se o código não confere."""
    dispositivo = TOTPDevice.objects.select_for_update().filter(user=usuario).first()
    if dispositivo is None or dispositivo.confirmed:
        return None
    passo = passo_do_codigo(dispositivo.secret, codigo)
    if passo is None:
        return None
    dispositivo.confirmed = True
    dispositivo.confirmed_at = timezone.now()
    dispositivo.last_used_step = passo
    dispositivo.save(update_fields=["confirmed", "confirmed_at", "last_used_step"])
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity_type="TOTPDevice",
        entity_id=str(usuario.pk),
        reason="Segundo fator ativado",
        actor=usuario,
    )
    return gerar_codigos_de_recuperacao(usuario)


@transaction.atomic
def verificar_codigo_totp(usuario: User, codigo: str) -> bool:
    """Confere o código do aplicativo. O mesmo passo não vale duas vezes."""
    dispositivo = (
        TOTPDevice.objects.select_for_update()
        .filter(user=usuario, confirmed=True)
        .first()
    )
    if dispositivo is None:
        return False
    passo = passo_do_codigo(dispositivo.secret, codigo)
    if passo is None:
        return False
    if dispositivo.last_used_step is not None and passo <= dispositivo.last_used_step:
        return False  # replay: este código (ou um mais antigo) já foi usado
    dispositivo.last_used_step = passo
    dispositivo.save(update_fields=["last_used_step"])
    return True


def _hash_do_codigo(codigo: str) -> str:
    normalizado = "".join(ch for ch in codigo.upper() if ch.isalnum())
    return hmac.new(
        settings.SECRET_KEY.encode(), normalizado.encode(), hashlib.sha256
    ).hexdigest()


def _novo_codigo() -> str:
    letras = "".join(
        secrets.choice(ALFABETO_DE_RECUPERACAO) for _ in range(TAMANHO_DO_CODIGO)
    )
    return f"{letras[:5]}-{letras[5:]}"


@transaction.atomic
def gerar_codigos_de_recuperacao(usuario: User) -> list[str]:
    """Novo lote: os antigos deixam de valer. Devolve os códigos em texto,
    que nunca mais são recuperáveis do banco."""
    RecoveryCode.objects.filter(user=usuario).delete()
    codigos = [_novo_codigo() for _ in range(QUANTOS_CODIGOS)]
    RecoveryCode.objects.bulk_create(
        [RecoveryCode(user=usuario, code_hash=_hash_do_codigo(c)) for c in codigos]
    )
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity_type="TOTPDevice",
        entity_id=str(usuario.pk),
        reason="Códigos de recuperação gerados",
        actor=usuario,
    )
    return codigos


@transaction.atomic
def usar_codigo_de_recuperacao(usuario: User, codigo: str) -> bool:
    """Consome um código de recuperação (uso único)."""
    if not any(ch.isalnum() for ch in codigo or ""):
        return False
    registro = (
        RecoveryCode.objects.select_for_update()
        .filter(user=usuario, code_hash=_hash_do_codigo(codigo), used_at__isnull=True)
        .first()
    )
    if registro is None:
        return False
    registro.used_at = timezone.now()
    registro.save(update_fields=["used_at"])
    return True


def codigos_de_recuperacao_restantes(usuario: User) -> int:
    return RecoveryCode.objects.filter(user=usuario, used_at__isnull=True).count()


def verificar(usuario: User, entrada: str) -> str | None:
    """Aceita o código do aplicativo **ou** um de recuperação, no mesmo
    campo. Devolve `"aplicativo"`, `"recuperacao"` ou `None`."""
    texto = (entrada or "").strip()
    so_digitos = "".join(ch for ch in texto if ch.isdigit())
    if len(so_digitos) == DIGITOS and so_digitos == texto.replace(" ", ""):
        return "aplicativo" if verificar_codigo_totp(usuario, texto) else None
    return "recuperacao" if usar_codigo_de_recuperacao(usuario, texto) else None


# --------------------------------------------------------------------------
# Redefinir (quem perdeu celular e códigos)
# --------------------------------------------------------------------------


@transaction.atomic
def redefinir_segundo_fator(usuario: User, *, por=None, motivo: str = "") -> None:
    """Apaga dispositivo e códigos; a pessoa volta a entrar só com a senha
    e pode ativar de novo na página Conta. Quem redefine fica na auditoria — `por=None` é a linha
    de comando do servidor. As sessões abertas do usuário são encerradas."""
    TOTPDevice.objects.filter(user=usuario).delete()
    RecoveryCode.objects.filter(user=usuario).delete()
    encerrar_sessoes(usuario)  # revoga também os dispositivos confiáveis
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity_type="TOTPDevice",
        entity_id=str(usuario.pk),
        reason=(
            f"Segundo fator redefinido por {por or 'linha de comando'}"
            + (f": {motivo}" if motivo else "")
        ),
        actor=por,
    )


class DesativacaoNegada(Exception):
    """Motivo (em português, para o usuário) de a desativação não ter ocorrido."""


def pode_desativar(usuario: User) -> bool:
    """Com `TWO_FACTOR_OBRIGATORIO` ligado, desativar levaria o usuário de volta
    à tela de configuração na requisição seguinte: melhor nem oferecer."""
    return not settings.TWO_FACTOR_OBRIGATORIO and (
        dispositivo_confirmado(usuario) is not None
    )


@transaction.atomic
def desativar_segundo_fator(usuario: User, *, senha: str, codigo: str) -> int:
    """O próprio usuário desliga o segundo fator.

    Exige a **senha** e um código do aplicativo (ou de recuperação): quem deixou
    a sessão aberta num computador alheio não pode tirar a proteção da conta.
    Apaga aplicativo e códigos e revoga os dispositivos confiáveis — sem segundo
    fator, a confiança neles não significa nada. As sessões abertas continuam:
    é a pessoa que acabou de provar quem é. Devolve quantos dispositivos foram
    revogados. Nega com `DesativacaoNegada`; tentativa errada conta para o
    limite, como em qualquer prova de segundo fator."""
    if settings.TWO_FACTOR_OBRIGATORIO:
        raise DesativacaoNegada(
            "O segundo fator é obrigatório neste sistema e não pode ser desativado."
        )
    if dispositivo_confirmado(usuario) is None:
        raise DesativacaoNegada("O segundo fator já está desativado.")
    if bloqueado_por_tentativas(usuario):
        raise DesativacaoNegada("Muitas tentativas. Tente novamente em alguns minutos.")
    if not usuario.check_password(senha or ""):
        registrar_falha(usuario)
        raise DesativacaoNegada("Senha incorreta. O segundo fator continua ativo.")
    if verificar(usuario, codigo) is None:
        registrar_falha(usuario)
        raise DesativacaoNegada(
            "Código inválido. Digite o que o aplicativo mostra agora "
            "(ou um código de recuperação). O segundo fator continua ativo."
        )
    limpar_falhas(usuario)
    TOTPDevice.objects.filter(user=usuario).delete()
    RecoveryCode.objects.filter(user=usuario).delete()
    revogados = trusted_devices.revogar_todos(
        usuario, motivo="Segundo fator desativado", ator=usuario
    )
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity_type="TOTPDevice",
        entity_id=str(usuario.pk),
        reason="Segundo fator desativado pelo próprio usuário",
        actor=usuario,
    )
    return revogados


def encerrar_sessoes(usuario: User) -> int:
    """Derruba as sessões abertas **e** revoga os dispositivos confiáveis:
    encerrar a sessão sem revogar o cookie deixaria o 2FA dispensado na
    próxima entrada. Todo caminho que encerra sessões passa por aqui."""
    from django.contrib.sessions.models import Session

    trusted_devices.revogar_todos(usuario, motivo="Sessões do usuário encerradas")
    encerradas = 0
    for sessao in Session.objects.filter(expire_date__gt=timezone.now()):
        if sessao.get_decoded().get("_auth_user_id") == str(usuario.pk):
            sessao.delete()
            encerradas += 1
    return encerradas
