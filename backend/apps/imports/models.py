"""Importação das planilhas: staging → validação → prévia → confirmação.

Nunca direto para as tabelas finais. `ImportBatch` guarda o arquivo e o
`file_hash`; `ImportRow` guarda cada linha crua em JSON com seu status, e
depois o objeto que ela criou — meses depois é possível saber de qual linha
de qual planilha veio cada registro. Ver docs/migracao/01-planilhas-e-importacao.md.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ImportKind(models.TextChoices):
    CUSTOS = "CUSTOS", "Custos (aba CUSTOS)"
    COMPRAS = "COMPRAS", "Compras de gado (aba COMPRA DE GADO)"
    MOVIMENTACOES = "MOVIMENTACOES", "Movimentações das fazendas (abas de fazenda)"
    VENDAS = "VENDAS", "Vendas e abates (aba VENDAS)"
    PESAGENS = "PESAGENS", "Pesagens (aba PESAGENS E CONFERENCIA)"


class BatchStatus(models.TextChoices):
    PREVIA = "PREVIA", "Em prévia"
    IMPORTADO = "IMPORTADO", "Importada"
    CANCELADO = "CANCELADO", "Cancelada"


class ImportBatch(models.Model):
    kind = models.CharField("Tipo", max_length=20, choices=ImportKind.choices)
    original_name = models.CharField("Arquivo", max_length=255)
    file = models.FileField("Arquivo guardado", upload_to="imports/%Y/%m/")
    file_hash = models.CharField("SHA-256 do arquivo", max_length=64, db_index=True)
    status = models.CharField(
        "Situação",
        max_length=12,
        choices=BatchStatus.choices,
        default=BatchStatus.PREVIA,
    )
    # Escolhas do usuário que a planilha não traz: fazenda, classe padrão,
    # mapeamento de categorias e de destinos. Ficam gravadas com o lote —
    # a importação é explicável depois.
    options = models.JSONField("Opções", default=dict, blank=True)
    # Contagens da leitura (linhas lidas, em branco...), para a prévia.
    read_stats = models.JSONField("Leitura", default=dict, blank=True)
    duplicate_confirmed = models.BooleanField("Reimportação confirmada", default=False)
    # Última tentativa que falhou. O lote continua em prévia — nada entrou, e
    # dá para corrigir a linha apontada e tentar de novo sem reenviar o arquivo.
    failure_message = models.TextField("Motivo da última falha", blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Enviado por",
        related_name="+",
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField("Enviado em", auto_now_add=True)
    finished_at = models.DateTimeField("Concluída em", null=True, blank=True)
    finished_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Concluída por",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )

    class Meta:
        verbose_name = "Importação"
        verbose_name_plural = "Importações"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.original_name}"


class RowStatus(models.TextChoices):
    VALIDA = "VALIDA", "Pronta"
    PENDENTE = "PENDENTE", "Pendente"
    ERRO = "ERRO", "Com erro"
    IGNORADA = "IGNORADA", "Ignorada"
    IMPORTADA = "IMPORTADA", "Importada"


class ImportRow(models.Model):
    batch = models.ForeignKey(
        ImportBatch,
        verbose_name="Importação",
        related_name="rows",
        on_delete=models.CASCADE,
    )
    sheet = models.CharField("Aba", max_length=60)
    row_number = models.PositiveIntegerField("Linha")
    raw = models.JSONField("Linha crua", default=dict)
    status = models.CharField(
        "Situação",
        max_length=10,
        choices=RowStatus.choices,
        default=RowStatus.PENDENTE,
        db_index=True,
    )
    # [{"nivel": "erro|pendencia|aviso", "campo": "...", "texto": "...",
    #   "sugestao": {...}}]
    messages = models.JSONField("Mensagens", default=list, blank=True)
    # O que o USUÁRIO decidiu para completar a linha (centro, classe,
    # contrapartida de transferência...). Nunca preenchido pelo sistema.
    resolution = models.JSONField("Decisão do usuário", default=dict, blank=True)
    # O que o SISTEMA deduziu (pareamento de transferências, por exemplo).
    meta = models.JSONField("Dados derivados", default=dict, blank=True)

    target_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    target = GenericForeignKey("target_type", "target_id")

    class Meta:
        verbose_name = "Linha importada"
        verbose_name_plural = "Linhas importadas"
        ordering = ["sheet", "row_number", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "sheet", "row_number"],
                name="uniq_importrow_batch_sheet_row",
            )
        ]

    def __str__(self) -> str:
        return f"{self.sheet} · linha {self.row_number}"

    @property
    def erros(self) -> list[dict]:
        return [m for m in self.messages if m.get("nivel") == "erro"]

    @property
    def pendencias(self) -> list[dict]:
        return [m for m in self.messages if m.get("nivel") == "pendencia"]

    @property
    def avisos(self) -> list[dict]:
        return [m for m in self.messages if m.get("nivel") == "aviso"]
