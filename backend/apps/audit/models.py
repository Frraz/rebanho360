import uuid

from django.conf import settings
from django.db import models


class AuditAction(models.TextChoices):
    CREATE = "CREATE", "Criou"
    UPDATE = "UPDATE", "Alterou"
    DELETE = "DELETE", "Excluiu"
    RESTORE = "RESTORE", "Restaurou"
    CONFIRM = "CONFIRM", "Confirmou"
    APPROVE = "APPROVE", "Aprovou"
    LOGIN = "LOGIN", "Entrou"
    LOGIN_FAILED = "LOGIN_FAILED", "Falha de login"
    LOGOUT = "LOGOUT", "Saiu"
    EXPORT = "EXPORT", "Exportou"
    IMPORT = "IMPORT", "Importou"
    CANCEL = "CANCEL", "Cancelou"
    # Consulta a dado sensível (conta bancária): LGPD, seguranca/01#lgpd.
    VIEW = "VIEW", "Consultou"


class ImmutableQuerySet(models.QuerySet):
    """Bloqueia `update()`/`delete()` em massa — a trilha é append-only."""

    def update(self, **kwargs):
        raise PermissionError("AuditEvent é append-only: não existe UPDATE em massa.")

    def delete(self, *args, **kwargs):
        raise PermissionError("AuditEvent é append-only: não existe DELETE em massa.")


class AuditEventManager(models.Manager.from_queryset(ImmutableQuerySet)):
    pass


class AuditEvent(models.Model):
    """Trilha técnica append-only. Nem o `ADMIN` altera ou apaga um evento.

    Imutabilidade em quatro camadas (ver ADR 0006):
    1. Sem tela de edição/exclusão em lugar nenhum do sistema.
    2. Sem método de serviço que altere — `save()`/`delete()` recusam aqui.
    3. Trigger de banco (`0002_auditevent_immutable_trigger`) recusa
       UPDATE/DELETE de linha já gravada, mesmo via SQL direto.
    4. Testado em `tests/test_immutability.py`.
    """

    timestamp = models.DateTimeField("Quando", auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Quem",
        null=True,
        blank=True,
        related_name="audit_events",
        on_delete=models.PROTECT,
    )
    action = models.CharField("Ação", max_length=20, choices=AuditAction.choices)
    entity_type = models.CharField("Tipo de entidade", max_length=100)
    entity_id = models.CharField("ID da entidade", max_length=50, blank=True)

    before = models.JSONField("Estado anterior", null=True, blank=True)
    after = models.JSONField("Estado novo", null=True, blank=True)
    changed_fields = models.JSONField("Campos alterados", null=True, blank=True)

    reason = models.TextField("Motivo", blank=True)
    cascade_root = models.UUIDField(
        "Raiz da cascata", null=True, blank=True, db_index=True
    )

    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("User-Agent", max_length=400, blank=True)
    request_id = models.UUIDField(
        "ID da requisição", null=True, blank=True, db_index=True
    )

    objects = AuditEventManager()

    class Meta:
        verbose_name = "Evento de auditoria"
        verbose_name_plural = "Eventos de auditoria"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["actor", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.entity_type}#{self.entity_id} por {self.actor}"

    def save(self, *args, **kwargs):
        if self.pk is not None and AuditEvent.objects.filter(pk=self.pk).exists():
            raise PermissionError(
                "AuditEvent é append-only: não existe UPDATE de evento gravado."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("AuditEvent é append-only: não existe DELETE.")


class OperationEvent(models.Model):
    """Linha do tempo de negócio, para o usuário ler — não para auditoria técnica.

    Ex.: "Compra confirmada. 126 cabeças deram entrada no lote LT-SFR-014."
    """

    timestamp = models.DateTimeField("Quando", auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Quem",
        null=True,
        blank=True,
        related_name="operation_events",
        on_delete=models.PROTECT,
    )
    entity_type = models.CharField("Tipo de entidade", max_length=100)
    entity_id = models.CharField("ID da entidade", max_length=50, blank=True)
    title = models.CharField("Título", max_length=200)
    description = models.TextField("Descrição", blank=True)
    previous_status = models.CharField("Status anterior", max_length=30, blank=True)
    new_status = models.CharField("Status novo", max_length=30, blank=True)
    document = models.CharField("Documento", max_length=50, blank=True)

    class Meta:
        verbose_name = "Evento de operação"
        verbose_name_plural = "Eventos de operação"
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self) -> str:
        return self.title


def new_cascade_root() -> uuid.UUID:
    return uuid.uuid4()
