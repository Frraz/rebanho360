"""Classe, centro de custo e lançamento.

Ver docs/regras-negocio/02-custos-centro-de-custo.md.
"""

from django.db import models

from apps.core.managers import ScopedManager
from apps.core.reversible import ReversibleModel


class CostClass(models.Model):
    """Classe de custo — semeada com CUSTEIO e INVESTIMENTO."""

    name = models.CharField("Nome", max_length=40, unique=True)
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Classe de custo"
        verbose_name_plural = "Classes de custo"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class AllocationCriterion(models.TextChoices):
    """Como o custo indireto do centro é rateado entre os lotes
    (docs/regras-negocio/05#rateio-de-custo-indireto)."""

    POR_CABECA_DIA = "POR_CABECA_DIA", "Cabeça-dia"
    POR_CABECA_SIMPLES = "POR_CABECA_SIMPLES", "Cabeças no fim do período"
    POR_ARROBA_PRODUZIDA = "POR_ARROBA_PRODUZIDA", "Arroba produzida"
    MANUAL = "MANUAL", "Manual"


class CostCenter(models.Model):
    """Centro de custo. Auto-relacionamento para subcentro."""

    name = models.CharField("Nome", max_length=80, unique=True)
    parent = models.ForeignKey(
        "self",
        verbose_name="Centro pai",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.PROTECT,
    )
    allocation_criterion = models.CharField(
        "Critério de rateio",
        max_length=25,
        choices=AllocationCriterion.choices,
        default=AllocationCriterion.POR_CABECA_DIA,
    )
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Centro de custo"
        verbose_name_plural = "Centros de custo"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class CostEntry(ReversibleModel):
    """Lançamento de custo. Fazenda, centro e classe são obrigatórios —
    mudança consciente em relação à planilha, onde 39% do custo está sem
    centro. `MÊS` e `ANO` não existem: derivam de `date`.

    `source_purchase` preenchido = custo gerado por uma compra: só se
    corrige pela compra, nunca direto aqui.
    """

    SCOPE_FARM_FIELD = "farm"

    date = models.DateField("Data do fato", db_index=True)
    season = models.ForeignKey(
        "organizations.Season",
        verbose_name="Safra",
        related_name="cost_entries",
        on_delete=models.PROTECT,
    )
    farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda",
        related_name="cost_entries",
        on_delete=models.PROTECT,
    )
    cost_center = models.ForeignKey(
        CostCenter,
        verbose_name="Centro de custo",
        related_name="entries",
        on_delete=models.PROTECT,
    )
    cost_class = models.ForeignKey(
        CostClass,
        verbose_name="Classe",
        related_name="entries",
        on_delete=models.PROTECT,
    )
    amount = models.DecimalField("Valor (R$)", max_digits=14, decimal_places=2)
    description = models.CharField("Descrição", max_length=200)
    payer = models.ForeignKey(
        "partners.Partner",
        verbose_name="Pagador",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    lot = models.ForeignKey(
        "livestock.Lot",
        verbose_name="Lote",
        null=True,
        blank=True,
        related_name="cost_entries",
        on_delete=models.PROTECT,
    )
    source_purchase = models.ForeignKey(
        "purchases.Purchase",
        verbose_name="Compra de origem",
        null=True,
        blank=True,
        related_name="cost_entries",
        on_delete=models.PROTECT,
    )
    notes = models.TextField("Observações", blank=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Lançamento de custo"
        verbose_name_plural = "Lançamentos de custo"
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0), name="costentry_amount_positive"
            ),
        ]
        indexes = [
            models.Index(fields=["farm", "season"]),
            models.Index(fields=["cost_center", "season"]),
        ]

    def __str__(self) -> str:
        return f"{self.description} · R$ {self.amount}"

    @property
    def is_direct(self) -> bool:
        """Custo direto: vai inteiro ao lote. Indireto é rateado."""
        return self.lot_id is not None

    def bloqueios(self) -> list[str]:
        from apps.organizations.models import SeasonStatus

        if self.season.status == SeasonStatus.ENCERRADA:
            return [
                f"a safra {self.season.name} está encerrada. Peça a um "
                "administrador para reabrir a safra antes de editar ou excluir."
            ]
        return []

    def descrever_efeitos(self) -> list[str]:
        return [
            f"R$ {self.amount} em {self.cost_center} deixam de contar na safra "
            f"{self.season.name} ({self.farm})"
        ]

    def aplicar_efeitos(self, *, usuario):
        """Custo não tem efeito colateral: ele próprio é o dado. Ser
        `CONFIRMADA` é o que o faz entrar nos relatórios."""

    def desfazer_efeitos(self, *, usuario):
        """Simétrico: ficar `EXCLUIDA` é o que o tira dos relatórios."""
