"""O mecanismo reversível: toda ação transacional é editável e excluível,
com os efeitos desfeitos junto, na mesma transação (ADR 0006).

Ver docs/regras-negocio/06-edicao-exclusao-e-auditoria.md.
"""

import uuid

from django.conf import settings
from django.db import models, transaction

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.exceptions import BlockingDependencyError, BusinessError, DependencyError
from apps.core.serialization import diff_fields, snapshot


class Status(models.TextChoices):
    RASCUNHO = "RASCUNHO", "Rascunho"
    CONFIRMADA = "CONFIRMADA", "Confirmada"
    EXCLUIDA = "EXCLUIDA", "Excluída"


class ReversibleModel(models.Model):
    """Mixin de todo registro transacional: `Purchase`, `Sale`,
    `HerdMovement`, `CostEntry`, `Weighing`.

    A subclasse implementa o contrato:

        aplicar_efeitos(self, *, usuario)      -> None
        desfazer_efeitos(self, *, usuario)     -> None
        dependentes(self)                      -> list[ReversibleModel]
        bloqueios(self)                        -> list[str]   (opcional)

    `bloqueios()` devolve a lista de motivos que impedem excluir/editar
    agora (pagamento baixado, safra encerrada, saldo ficaria negativo).
    Lista vazia = nada bloqueia.
    """

    status = models.CharField(
        "Situação", max_length=20, choices=Status.choices, default=Status.RASCUNHO
    )
    version = models.PositiveIntegerField("Versão", default=1)

    deleted_at = models.DateTimeField("Excluído em", null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Excluído por",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    delete_reason = models.TextField("Motivo da exclusão", blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Criado por",
        null=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Atualizado por",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        abstract = True

    def dependentes(self) -> list:
        return []

    def bloqueios(self) -> list[str]:
        return []

    def aplicar_efeitos(self, *, usuario):
        raise NotImplementedError

    def desfazer_efeitos(self, *, usuario):
        raise NotImplementedError

    def descrever_efeitos(self) -> list[str]:
        """Frases do que desfazer vai desfazer, para a análise de impacto
        ("entrada de 126 cabeças no lote LT-SFR-014"). Opcional."""
        return []


def _explicar_bloqueios(bloqueios: list[str]) -> str:
    primeiro = bloqueios[0]
    return f"Não é possível prosseguir: {primeiro}"


@transaction.atomic
def confirmar(registro: ReversibleModel, *, usuario):
    """RASCUNHO → CONFIRMADA. Aplica os efeitos pela primeira vez."""
    registro = type(registro).objects.select_for_update().get(pk=registro.pk)
    antes = snapshot(registro)

    registro.aplicar_efeitos(usuario=usuario)
    registro.status = Status.CONFIRMADA
    registro.updated_by = usuario
    registro.save()

    registrar_auditoria(
        action=AuditAction.CONFIRM,
        entity=registro,
        before=antes,
        after=snapshot(registro),
        actor=usuario,
    )
    return registro


@transaction.atomic
def editar(registro: ReversibleModel, dados: dict, *, usuario, motivo: str):
    """Edita um registro confirmado: desfaz os efeitos antigos, aplica os novos."""
    if not motivo or not motivo.strip():
        raise BusinessError("Motivo é obrigatório para editar um registro confirmado.")

    registro = type(registro).objects.select_for_update().get(pk=registro.pk)
    antes = snapshot(registro)

    bloqueios = registro.bloqueios()
    if bloqueios:
        raise BlockingDependencyError(_explicar_bloqueios(bloqueios))

    era_confirmada = registro.status == Status.CONFIRMADA
    if era_confirmada:
        registro.desfazer_efeitos(usuario=usuario)

    for campo, valor in dados.items():
        setattr(registro, campo, valor)

    if era_confirmada:
        registro.aplicar_efeitos(usuario=usuario)

    registro.version += 1
    registro.updated_by = usuario
    registro.save()

    depois = snapshot(registro)
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=registro,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        reason=motivo,
        actor=usuario,
    )
    return registro


@transaction.atomic
def excluir(
    registro: ReversibleModel,
    *,
    usuario,
    motivo: str,
    cascata: bool = False,
    raiz: uuid.UUID | None = None,
):
    """Desfaz os efeitos e marca `EXCLUIDA`. Nunca remove a linha do banco."""
    if not motivo or not motivo.strip():
        raise BusinessError("Motivo é obrigatório para excluir um registro confirmado.")

    registro = type(registro).objects.select_for_update().get(pk=registro.pk)

    if registro.status == Status.EXCLUIDA:
        raise BusinessError("Este registro já foi excluído.")

    bloqueios = registro.bloqueios()
    if bloqueios:
        raise BlockingDependencyError(_explicar_bloqueios(bloqueios))

    deps = registro.dependentes()
    if deps and not cascata:
        raise DependencyError(deps)

    cascade_root = raiz or uuid.uuid4()
    for dep in deps:
        excluir(dep, usuario=usuario, motivo=motivo, cascata=True, raiz=cascade_root)

    antes = snapshot(registro)
    if registro.status == Status.CONFIRMADA:
        # Registro cujos efeitos são outros registros (compra → movimento,
        # custos, lote) lê a raiz daqui, para a cascata inteira ser lida
        # como UM ato; `cascade_root_usado` avisa que ela foi usada.
        registro.cascade_root = cascade_root
        registro.cascade_root_usado = False
        registro.desfazer_efeitos(usuario=usuario)

    registro.status = Status.EXCLUIDA
    registro.deleted_at = antes.get("updated_at")
    registro.deleted_by = usuario
    registro.delete_reason = motivo
    registro.save()

    registrar_auditoria(
        action=AuditAction.DELETE,
        entity=registro,
        before=antes,
        after=snapshot(registro),
        reason=motivo,
        cascade_root=(
            cascade_root
            if (deps or raiz or getattr(registro, "cascade_root_usado", False))
            else None
        ),
        actor=usuario,
    )
    return registro


@transaction.atomic
def restaurar(registro: ReversibleModel, *, usuario):
    """Desfaz a exclusão e reaplica exatamente os efeitos originais."""
    registro = type(registro).objects.select_for_update().get(pk=registro.pk)
    if registro.status != Status.EXCLUIDA:
        raise BusinessError("Só é possível restaurar um registro excluído.")

    antes = snapshot(registro)
    registro.aplicar_efeitos(usuario=usuario)
    registro.status = Status.CONFIRMADA
    registro.deleted_at = None
    registro.deleted_by = None
    registro.delete_reason = ""
    registro.save()

    registrar_auditoria(
        action=AuditAction.RESTORE,
        entity=registro,
        before=antes,
        after=snapshot(registro),
        actor=usuario,
    )
    return registro
