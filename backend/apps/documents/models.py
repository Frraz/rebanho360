"""Documento gerado — o PDF que vira papel.

Todo PDF registra quem gerou, quando, com quais filtros, qual versão do
template e o hash do arquivo (docs/relatorios/01#documentos-gerados). O
arquivo em si fica guardado: é ele a reprodução exata, mesmo que o template
mude depois. Se alguém perguntar "o que a gente imprimiu naquele dia?", o
documento responde.
"""

import uuid

from django.conf import settings
from django.db import models


class DocumentType(models.TextChoices):
    RELATORIO = "RELATORIO", "Relatório"
    CONTRATO = "CONTRATO", "Contrato de compra"


class DocumentStatus(models.TextChoices):
    PENDENTE = "PENDENTE", "Gerando"
    PRONTO = "PRONTO", "Pronto"
    ERRO = "ERRO", "Com erro"


class GeneratedDocument(models.Model):
    document_id = models.UUIDField(
        "Documento", default=uuid.uuid4, unique=True, editable=False
    )
    doc_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=DocumentType.choices,
        default=DocumentType.RELATORIO,
    )
    # O que o documento descreve: `Relatorio` + o slug (`resultado-do-lote`).
    entity_type = models.CharField("Tipo de entidade", max_length=40)
    entity_id = models.CharField("Identificador da entidade", max_length=80)
    title = models.CharField("Título", max_length=200)
    template_version = models.CharField("Versão do template", max_length=40)
    status = models.CharField(
        "Situação",
        max_length=10,
        choices=DocumentStatus.choices,
        default=DocumentStatus.PENDENTE,
        db_index=True,
    )
    # Tudo o que é preciso para gerar de novo o mesmo relatório: safra,
    # fazenda e parâmetros. `filters` é o texto que foi impresso no cabeçalho.
    params = models.JSONField("Parâmetros", default=dict, blank=True)
    filters = models.JSONField("Filtros impressos", default=list, blank=True)

    file = models.FileField("Arquivo", upload_to="documents/%Y/%m/", blank=True)
    file_hash = models.CharField("SHA-256 do arquivo", max_length=64, blank=True)
    size_bytes = models.PositiveBigIntegerField("Tamanho (bytes)", default=0)
    error = models.TextField("Motivo da falha", blank=True)

    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Gerado por",
        related_name="+",
        on_delete=models.PROTECT,
    )
    generated_at = models.DateTimeField("Pedido em", auto_now_add=True)
    finished_at = models.DateTimeField("Concluído em", null=True, blank=True)

    class Meta:
        verbose_name = "Documento gerado"
        verbose_name_plural = "Documentos gerados"
        ordering = ["-generated_at", "-id"]

    def __str__(self) -> str:
        return f"{self.title} · {self.generated_at:%d/%m/%Y %H:%M}"
