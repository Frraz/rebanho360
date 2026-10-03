"""Exportação de dados — o pedido, o andamento e o arquivo pronto.

O pedido grava **tudo o que é preciso para repetir a exportação**: quais
conjuntos, quais formatos, quais filtros. O arquivo expira (30 dias,
decisão de Warley em 2026-10-03); o registro do pedido nunca sai do banco, como
qualquer outro registro do sistema (regra 5).

O andamento é para o usuário ler: a tela pergunta de tempos em tempos
(`heartbeat_at` diz se o processador ainda está vivo) e mostra, conjunto por
conjunto, o que já foi lido. Ver docs/regras-negocio/10-exportacao-de-dados.md.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.money import safe_div

#: Sem sinal de vida do processador por tanto tempo, o pedido está parado.
SEM_SINAL_MINUTOS = 10
#: Na fila há tanto tempo sem ninguém pegar: o processador provavelmente está desligado.
FILA_PARADA_SEGUNDOS = 90


class ExportStatus(models.TextChoices):
    PENDENTE = "PENDENTE", "Na fila"
    PROCESSANDO = "PROCESSANDO", "Processando"
    PRONTO = "PRONTO", "Pronta"
    ERRO = "ERRO", "Com erro"
    CANCELADO = "CANCELADO", "Cancelada"
    EXPIRADO = "EXPIRADO", "Arquivo removido"


STATUS_EM_ANDAMENTO = (ExportStatus.PENDENTE, ExportStatus.PROCESSANDO)


class ExportJob(models.Model):
    job_id = models.UUIDField(
        "Exportação", default=uuid.uuid4, unique=True, editable=False
    )
    status = models.CharField(
        "Situação",
        max_length=12,
        choices=ExportStatus.choices,
        default=ExportStatus.PENDENTE,
        db_index=True,
    )
    # {"conjuntos": [...], "relatorios": [...], "formatos": [...],
    #  "filtros": {...}, "opcoes": {...}} — só JSON puro (ids, texto, datas ISO).
    params = models.JSONField("Pedido", default=dict, blank=True)
    # O que o usuário viu escolhido, em frases ("Fazenda: Baixão").
    filters = models.JSONField("Filtros", default=list, blank=True)
    # [{"id", "tipo", "rotulo", "estado", "linhas", "arquivos", "aviso"}]
    items = models.JSONField("Itens", default=list, blank=True)

    stage = models.CharField("Etapa", max_length=200, blank=True)
    # Unidades de trabalho, não só linhas: cada registro lido conta 1; um
    # relatório ou um anexo contam um bloco maior (ver `services`). A barra de
    # progresso é `work_done / work_total`.
    work_total = models.PositiveBigIntegerField("Trabalho a fazer", default=0)
    work_done = models.PositiveBigIntegerField("Trabalho feito", default=0)
    cancel_requested = models.BooleanField("Cancelamento pedido", default=False)

    file = models.FileField("Arquivo", upload_to="exports/%Y/%m/", blank=True)
    file_name = models.CharField("Nome para baixar", max_length=120, blank=True)
    content_type = models.CharField("Tipo do arquivo", max_length=100, blank=True)
    file_hash = models.CharField("SHA-256 do arquivo", max_length=64, blank=True)
    size_bytes = models.PositiveBigIntegerField("Tamanho (bytes)", default=0)
    warnings = models.JSONField("Avisos", default=list, blank=True)
    error = models.TextField("Motivo da falha", blank=True)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Pedida por",
        related_name="+",
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField("Pedida em", auto_now_add=True)
    started_at = models.DateTimeField("Começou em", null=True, blank=True)
    heartbeat_at = models.DateTimeField("Último sinal", null=True, blank=True)
    finished_at = models.DateTimeField("Concluída em", null=True, blank=True)
    expires_at = models.DateTimeField("Arquivo disponível até", null=True, blank=True)
    file_removed_at = models.DateTimeField("Arquivo removido em", null=True, blank=True)

    class Meta:
        verbose_name = "Exportação"
        verbose_name_plural = "Exportações"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["requested_by", "-created_at"])]

    # Para a tela dizer o mesmo número que a regra usa.
    SEM_SINAL_MINUTOS = SEM_SINAL_MINUTOS

    def __str__(self) -> str:
        return f"Exportação {self.created_at:%d/%m/%Y %H:%M}"

    # --- leitura do andamento (derivado, nunca gravado) ---

    @property
    def em_andamento(self) -> bool:
        return self.status in STATUS_EM_ANDAMENTO

    @property
    def percentual(self) -> int:
        """0 a 100. Sem total (ainda contando, ou conjunto vazio) é 0 enquanto
        roda e 100 quando termina."""
        if self.status == ExportStatus.PRONTO:
            return 100
        razao = safe_div(self.work_done, self.work_total)
        if razao is None:
            return 0
        return min(99, int(razao * 100)) if self.em_andamento else int(razao * 100)

    @property
    def baixavel(self) -> bool:
        return self.status == ExportStatus.PRONTO and bool(self.file)

    @property
    def parece_parado(self) -> bool:
        """Em andamento, mas sem sinal do processador: ele pode ter sido
        reiniciado no meio do caminho (ou nem estar ligado)."""
        agora = timezone.now()
        if self.status == ExportStatus.PROCESSANDO and self.heartbeat_at:
            return agora - self.heartbeat_at > timedelta(minutes=SEM_SINAL_MINUTOS)
        if self.status == ExportStatus.PENDENTE:
            return agora - self.created_at > timedelta(seconds=FILA_PARADA_SEGUNDOS)
        return False

    @property
    def itens_com_erro(self) -> list[dict]:
        return [i for i in self.items if i.get("estado") == "erro"]
