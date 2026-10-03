"""Gerenciamento de usuários pelo administrador.

Aplica ao usuário a regra 5 do projeto: tudo é editável e excluível, tudo
fica auditado, com motivo.

- **Excluir é lógico** (`deleted_at`). O usuário sai da operação, mas a
  auditoria e tudo o que ele lançou continuam apontando para ele; dá para
  restaurar.
- **Ninguém tranca o sistema por engano.** Não se desativa, exclui ou rebaixa
  a si mesmo, e nunca o último administrador ativo.
- **Senha nunca vai para a auditoria** (nem o hash): o retrato do usuário é
  montado campo a campo, sem `snapshot()`.
- Toda função confere a permissão de quem chama, além da view.
"""

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts import emails, two_factor
from apps.accounts.models import Role, User, UserFarmAccess
from apps.accounts.permissions import pode_gerenciar_usuarios
from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.exceptions import BusinessError
from apps.core.serialization import diff_fields
from apps.core.validators import mascarar_cpf

CAMPOS_DO_PERFIL = ("first_name", "last_name", "email", "phone", "role")
# O que o próprio usuário edita na página Conta. Lista fechada de propósito:
# papel, e-mail, usuário e situação são do administrador, mesmo que um POST
# adulterado mande esses campos.
CAMPOS_DA_PROPRIA_CONTA = ("first_name", "last_name", "phone", "birth_date", "cpf")


def validade_do_link_em_dias() -> int:
    return max(1, settings.PASSWORD_RESET_TIMEOUT // 86400)


# --------------------------------------------------------------------------
# Consultas de apoio
# --------------------------------------------------------------------------


def administradores_ativos():
    """Quem hoje consegue administrar: `ADMIN` ou superusuário, ativo e não excluído."""
    return User.objects.filter(is_active=True, deleted_at__isnull=True).filter(
        Q(role=Role.ADMIN) | Q(is_superuser=True)
    )


def email_em_uso(email: str, *, exceto_pk: int | None = None) -> bool:
    """Já há outra conta (não excluída) com este e-mail, sem diferenciar maiúsculas."""
    if not email:
        return False
    qs = User.objects.filter(email__iexact=email, deleted_at__isnull=True)
    if exceto_pk is not None:
        qs = qs.exclude(pk=exceto_pk)
    return qs.exists()


def cpf_em_uso(cpf: str, *, exceto_pk: int | None = None) -> bool:
    """Já há outra conta (não excluída) com este CPF. `cpf` vem só com dígitos."""
    if not cpf:
        return False
    qs = User.objects.filter(cpf=cpf, deleted_at__isnull=True)
    if exceto_pk is not None:
        qs = qs.exclude(pk=exceto_pk)
    return qs.exists()


def usuario_em_uso(username: str) -> bool:
    return User.objects.filter(username__iexact=username).exists()


# --------------------------------------------------------------------------
# Internos
# --------------------------------------------------------------------------


def _exigir_permissao(ator) -> None:
    if not pode_gerenciar_usuarios(ator):
        raise PermissionDenied("Só o administrador gerencia usuários.")


def _motivo(motivo: str) -> str:
    motivo = (motivo or "").strip()
    if not motivo:
        raise BusinessError("Informe o motivo: ele fica registrado na auditoria.")
    return motivo


def _retrato(usuario: User) -> dict:
    """Campos que importam para a auditoria — sem senha, sem segredo."""
    acessos = {
        a.farm.code: a.can_write
        for a in usuario.farm_access.select_related("farm").all()
    }
    return {
        "username": usuario.username,
        "first_name": usuario.first_name,
        "last_name": usuario.last_name,
        "email": usuario.email,
        "phone": usuario.phone,
        "birth_date": usuario.birth_date.isoformat() if usuario.birth_date else None,
        # CPF inteiro nunca vai para a auditoria (docs/seguranca/01-seguranca.md).
        "cpf": mascarar_cpf(usuario.cpf),
        "role": usuario.role,
        "is_active": usuario.is_active,
        "deleted_at": usuario.deleted_at.isoformat() if usuario.deleted_at else None,
        "must_change_password": usuario.must_change_password,
        "acessos": dict(sorted(acessos.items())),
    }


def _auditar(usuario, ator, acao, *, antes, depois, motivo):
    registrar_auditoria(
        action=acao,
        entity=usuario,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        reason=motivo,
        actor=ator,
    )


def _travar(usuario: User) -> User:
    return User.objects.select_for_update().get(pk=usuario.pk)


def _garantir_outro_administrador(usuario: User) -> None:
    """Falha se `usuario` é o único administrador ativo. Trava os administradores
    antes de contar: duas desativações simultâneas não podem passar juntas."""
    ids = set(administradores_ativos().select_for_update().values_list("pk", flat=True))
    if usuario.pk in ids and not (ids - {usuario.pk}):
        raise BusinessError(
            "Este é o único administrador ativo. Torne outra pessoa administradora "
            "antes — sem ele, ninguém mais consegue gerenciar usuários."
        )


def _nao_a_si_mesmo(usuario: User, ator, frase: str) -> None:
    if usuario.pk == ator.pk:
        raise BusinessError(f"Você não pode {frase}: peça a outro administrador.")


def _gravar_acessos(usuario: User, acessos: dict) -> None:
    """`acessos`: {Farm: pode_lancar}; `None` deixa como está. Papel de acesso
    amplo (`ADMIN`, `GESTOR`) vê todas as fazendas por definição e não guarda
    linha nenhuma."""
    if acessos is None:
        return
    if usuario.has_broad_access:
        acessos = {}
    atuais = {a.farm_id: a for a in usuario.farm_access.all()}
    desejados = {farm.pk: (farm, pode) for farm, pode in acessos.items()}

    for farm_id, acesso in atuais.items():
        if farm_id not in desejados:
            acesso.delete()
    for farm_id, (farm, pode) in desejados.items():
        atual = atuais.get(farm_id)
        if atual is None:
            UserFarmAccess.objects.create(user=usuario, farm=farm, can_write=pode)
        elif atual.can_write != pode:
            atual.can_write = pode
            atual.save(update_fields=["can_write"])


def _encerrar_sessoes(usuario: User) -> int:
    return two_factor.encerrar_sessoes(usuario)


# --------------------------------------------------------------------------
# Criar
# --------------------------------------------------------------------------


def _validar_senha(senha: str, usuario: User) -> None:
    try:
        password_validation.validate_password(senha, usuario)
    except ValidationError as exc:
        raise BusinessError(" ".join(exc.messages)) from exc


@transaction.atomic
def criar_usuario(
    *,
    ator,
    dados: dict,
    acessos: dict,
    senha_temporaria: str | None = None,
    base_url: str = "",
    veio_de_solicitacao: bool = False,
) -> User:
    """Cria a conta. Sem `senha_temporaria`, a conta nasce sem senha utilizável
    e o usuário recebe por e-mail o link para definir a dele; com ela, o
    administrador a repassa por fora e a pessoa troca no primeiro acesso."""
    _exigir_permissao(ator)
    if not senha_temporaria and not dados.get("email"):
        raise BusinessError(
            "Sem e-mail não há como enviar o convite: defina uma senha temporária."
        )
    if usuario_em_uso(dados["username"]):
        raise BusinessError(f"O usuário '{dados['username']}' já existe.")
    if email_em_uso(dados.get("email", "")):
        raise BusinessError(f"Já existe uma conta com o e-mail {dados['email']}.")

    usuario = User(
        username=dados["username"],
        first_name=dados.get("first_name", ""),
        last_name=dados.get("last_name", ""),
        email=dados.get("email", ""),
        phone=dados.get("phone", ""),
        role=dados["role"],
    )
    if senha_temporaria:
        _validar_senha(senha_temporaria, usuario)
        usuario.set_password(senha_temporaria)
        usuario.must_change_password = True
    else:
        usuario.set_unusable_password()
    try:
        usuario.save()
    except IntegrityError as exc:  # corrida: outro administrador criou antes
        raise BusinessError("Já existe uma conta com este usuário ou e-mail.") from exc
    _gravar_acessos(usuario, acessos)

    _auditar(
        usuario,
        ator,
        AuditAction.CREATE,
        antes=None,
        depois=_retrato(usuario),
        motivo=(
            "Conta criada a partir de uma solicitação de acesso"
            if veio_de_solicitacao
            else "Conta criada por um administrador"
        ),
    )
    if not senha_temporaria:
        emails.enviar_conta_criada(
            usuario,
            base_url,
            aprovada=veio_de_solicitacao,
            validade_dias=validade_do_link_em_dias(),
        )
    return usuario


# --------------------------------------------------------------------------
# Editar
# --------------------------------------------------------------------------


@transaction.atomic
def editar_usuario(
    usuario: User, *, ator, dados: dict, acessos: dict, motivo: str
) -> bool:
    """Devolve `False` se nada mudou (e então nada é gravado)."""
    _exigir_permissao(ator)
    motivo = _motivo(motivo)
    usuario = _travar(usuario)
    if usuario.deleted_at:
        raise BusinessError("Restaure o usuário antes de editá-lo.")

    antes = _retrato(usuario)
    novo_papel = dados["role"]
    if novo_papel != usuario.role:
        _nao_a_si_mesmo(usuario, ator, "mudar o seu próprio papel")
        deixa_de_administrar = (
            usuario.role == Role.ADMIN
            and novo_papel != Role.ADMIN
            and not usuario.is_superuser
        )
        if deixa_de_administrar:
            _garantir_outro_administrador(usuario)
    if email_em_uso(dados.get("email", ""), exceto_pk=usuario.pk):
        raise BusinessError(f"Já existe uma conta com o e-mail {dados['email']}.")

    for campo in CAMPOS_DO_PERFIL:
        if campo in dados:
            setattr(usuario, campo, dados[campo])
    try:
        usuario.save(update_fields=list(CAMPOS_DO_PERFIL))
    except IntegrityError as exc:
        raise BusinessError("Já existe uma conta com este e-mail.") from exc
    # O próprio escopo não se mexe aqui (o papel também não muda: ver acima).
    _gravar_acessos(usuario, None if usuario.pk == ator.pk else acessos)

    depois = _retrato(usuario)
    if depois == antes:
        return False
    _auditar(
        usuario, ator, AuditAction.UPDATE, antes=antes, depois=depois, motivo=motivo
    )
    return True


@transaction.atomic
def atualizar_propria_conta(usuario: User, *, dados: dict) -> bool:
    """O usuário edita o *próprio* perfil (página Conta).

    Não pede permissão nem motivo — é a pessoa cuidando dos próprios dados —,
    mas só mexe em `CAMPOS_DA_PROPRIA_CONTA` e audita antes/depois com ela
    mesma como autora. Devolve `False` se nada mudou (e então nada é gravado).
    """
    usuario = _travar(usuario)
    antes = _retrato(usuario)
    cpf = dados.get("cpf", "")
    if cpf_em_uso(cpf, exceto_pk=usuario.pk):
        raise BusinessError(
            "Este CPF já está cadastrado em outra conta. "
            "Se o CPF é seu, fale com o administrador."
        )
    for campo in CAMPOS_DA_PROPRIA_CONTA:
        if campo in dados:
            setattr(usuario, campo, dados[campo])
    try:
        usuario.save(update_fields=list(CAMPOS_DA_PROPRIA_CONTA))
    except IntegrityError as exc:
        # Duas gravações simultâneas do mesmo CPF: a constraint do banco decide.
        raise BusinessError("Este CPF já está cadastrado em outra conta.") from exc
    depois = _retrato(usuario)
    if depois == antes:
        return False
    _auditar(
        usuario,
        usuario,
        AuditAction.UPDATE,
        antes=antes,
        depois=depois,
        motivo="Alteração feita pelo próprio usuário",
    )
    return True


def auditar_troca_de_senha(usuario: User) -> None:
    """Registra que a senha mudou. O valor (nem o hash) nunca vai para a auditoria."""
    # `request.user` chega como SimpleLazyObject: o tipo vai explícito.
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity_type="User",
        entity_id=str(usuario.pk),
        changed_fields=["password"],
        reason="Troca de senha pelo próprio usuário",
        actor=usuario,
    )


# --------------------------------------------------------------------------
# Desativar, reativar, excluir, restaurar
# --------------------------------------------------------------------------


def _gravar_situacao(usuario, ator, motivo, acao, texto, **campos) -> None:
    """Muda `is_active`/`deleted_at` e audita, com antes e depois."""
    antes = _retrato(usuario)
    for campo, valor in campos.items():
        setattr(usuario, campo, valor)
    usuario.save(update_fields=list(campos))
    _auditar(
        usuario,
        ator,
        acao,
        antes=antes,
        depois=_retrato(usuario),
        motivo=f"{texto}: {motivo}",
    )


@transaction.atomic
def desativar_usuario(usuario: User, *, ator, motivo: str) -> int:
    """Bloqueia o acesso sem apagar nada e derruba as sessões abertas.
    Devolve quantas sessões foram encerradas."""
    _exigir_permissao(ator)
    motivo = _motivo(motivo)
    _nao_a_si_mesmo(usuario, ator, "desativar a sua própria conta")
    usuario = _travar(usuario)
    if not usuario.is_active:
        raise BusinessError("Este usuário já está desativado.")
    _garantir_outro_administrador(usuario)
    _gravar_situacao(
        usuario, ator, motivo, AuditAction.UPDATE, "Desativado", is_active=False
    )
    return _encerrar_sessoes(usuario)


@transaction.atomic
def reativar_usuario(usuario: User, *, ator, motivo: str) -> None:
    _exigir_permissao(ator)
    motivo = _motivo(motivo)
    usuario = _travar(usuario)
    if usuario.deleted_at:
        raise BusinessError("Restaure o usuário antes de reativá-lo.")
    if usuario.is_active:
        raise BusinessError("Este usuário já está ativo.")
    _gravar_situacao(
        usuario, ator, motivo, AuditAction.UPDATE, "Reativado", is_active=True
    )


@transaction.atomic
def excluir_usuario(usuario: User, *, ator, motivo: str) -> int:
    """Exclusão lógica: sai da lista e do login, fica na auditoria, pode voltar."""
    _exigir_permissao(ator)
    motivo = _motivo(motivo)
    _nao_a_si_mesmo(usuario, ator, "excluir a sua própria conta")
    usuario = _travar(usuario)
    if usuario.deleted_at:
        raise BusinessError("Este usuário já foi excluído.")
    _garantir_outro_administrador(usuario)
    _gravar_situacao(
        usuario,
        ator,
        motivo,
        AuditAction.DELETE,
        "Excluído",
        is_active=False,
        deleted_at=timezone.now(),
    )
    return _encerrar_sessoes(usuario)


@transaction.atomic
def restaurar_usuario(usuario: User, *, ator, motivo: str) -> None:
    """Volta da exclusão **desativado**: quem restaura confere o cadastro e
    reativa em seguida, em vez de devolver o acesso por tabela."""
    _exigir_permissao(ator)
    motivo = _motivo(motivo)
    usuario = _travar(usuario)
    if not usuario.deleted_at:
        raise BusinessError("Este usuário não está excluído.")
    if email_em_uso(usuario.email, exceto_pk=usuario.pk):
        raise BusinessError(
            f"O e-mail {usuario.email} já pertence a outra conta. Troque-o "
            "na conta ativa antes de restaurar este usuário."
        )
    _gravar_situacao(
        usuario, ator, motivo, AuditAction.RESTORE, "Restaurado", deleted_at=None
    )


# --------------------------------------------------------------------------
# Senha, sessões, segundo fator
# --------------------------------------------------------------------------


@transaction.atomic
def definir_senha_temporaria(usuario: User, *, ator, senha: str, motivo: str) -> int:
    """Para quem não tem e-mail (ou não pode esperar): o administrador define,
    repassa por fora, e a pessoa troca no primeiro acesso. Derruba as sessões
    abertas — quem tinha a senha antiga não segue logado com ela."""
    _exigir_permissao(ator)
    motivo = _motivo(motivo)
    _nao_a_si_mesmo(
        usuario, ator, "definir senha temporária para si (use Alterar senha)"
    )
    usuario = _travar(usuario)
    if usuario.deleted_at:
        raise BusinessError("Restaure o usuário antes de mudar a senha.")
    _validar_senha(senha, usuario)

    antes = _retrato(usuario)
    usuario.set_password(senha)
    usuario.must_change_password = True
    usuario.save(update_fields=["password", "must_change_password"])
    _auditar(
        usuario,
        ator,
        AuditAction.UPDATE,
        antes=antes,
        depois=_retrato(usuario),
        motivo=f"Senha temporária definida: {motivo}",
    )
    return _encerrar_sessoes(usuario)


@transaction.atomic
def enviar_link_de_senha(usuario: User, *, ator, motivo: str, base_url: str) -> None:
    """Convite (ou redefinição) por e-mail. A senha atual continua valendo até
    o usuário usar o link."""
    _exigir_permissao(ator)
    motivo = _motivo(motivo)
    usuario = _travar(usuario)
    if usuario.deleted_at or not usuario.is_active:
        raise BusinessError("Reative o usuário antes de enviar o link de senha.")
    if not usuario.email:
        raise BusinessError(
            "Este usuário não tem e-mail cadastrado. Cadastre um e-mail ou defina "
            "uma senha temporária."
        )
    emails.enviar_link_de_senha(
        usuario, base_url, validade_dias=validade_do_link_em_dias()
    )
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=usuario,
        reason=f"Link para definir a senha enviado para {usuario.email}: {motivo}",
        actor=ator,
    )


@transaction.atomic
def encerrar_sessoes_do_usuario(usuario: User, *, ator, motivo: str) -> int:
    _exigir_permissao(ator)
    motivo = _motivo(motivo)
    encerradas = _encerrar_sessoes(usuario)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=usuario,
        reason=f"Sessões encerradas ({encerradas}): {motivo}",
        actor=ator,
    )
    return encerradas


@transaction.atomic
def redefinir_segundo_fator(usuario: User, *, ator, motivo: str) -> None:
    """Perdeu celular e códigos. Nunca em si mesmo: senão seria um atalho para
    fugir do segundo fator (mesma regra da tela do admin do Django)."""
    _exigir_permissao(ator)
    motivo = _motivo(motivo)
    _nao_a_si_mesmo(usuario, ator, "redefinir o seu próprio segundo fator")
    two_factor.redefinir_segundo_fator(usuario, por=ator, motivo=motivo)


# --------------------------------------------------------------------------
# Apoio às telas: o que vai acontecer, e o que impede
# --------------------------------------------------------------------------


def contar_sessoes(usuario: User) -> int:
    from django.contrib.sessions.models import Session

    return sum(
        1
        for sessao in Session.objects.filter(expire_date__gt=timezone.now())
        if sessao.get_decoded().get("_auth_user_id") == str(usuario.pk)
    )


def bloqueios_para_remover(usuario: User, ator, acao: str) -> list[str]:
    """Por que `acao` ("desativar" ou "excluir") não vale agora — com o caminho,
    para a tela explicar em vez de só recusar."""
    if usuario.pk == ator.pk:
        return [
            f"Você não pode {acao} a sua própria conta. Peça a outro administrador."
        ]
    ids = set(administradores_ativos().values_list("pk", flat=True))
    if usuario.pk in ids and not (ids - {usuario.pk}):
        return [
            "Este é o único administrador ativo. Torne outra pessoa administradora "
            f"(Editar → Papel) antes de {acao} esta conta."
        ]
    return []
