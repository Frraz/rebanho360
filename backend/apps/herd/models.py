"""`HerdMovement` e `HerdLedgerEntry` — o par mais importante do sistema.

Ver docs/regras-negocio/01-rebanho-movimentacoes.md e
docs/arquitetura/adr/0002-rebanho-como-razao-de-movimentacoes.md.
"""

from django.db import models

from apps.core.managers import ScopedManager, ScopedQuerySet
from apps.core.reversible import ReversibleModel


class ImmutableScopedQuerySet(ScopedQuerySet):
    """`ScopedQuerySet` que também recusa `update()`/`delete()` em massa —
    o razão é append-only, igual ao `AuditEvent` (ADR 0006)."""

    def update(self, **kwargs):
        raise PermissionError(
            "HerdLedgerEntry é append-only: não existe UPDATE em massa."
        )

    def delete(self, *args, **kwargs):
        raise PermissionError(
            "HerdLedgerEntry é append-only: não existe DELETE em massa."
        )


class HerdLedgerEntryManager(models.Manager.from_queryset(ImmutableScopedQuerySet)):
    pass


class MovementType(models.TextChoices):
    SALDO_INICIAL = "SALDO_INICIAL", "Saldo inicial"
    COMPRA = "COMPRA", "Compra"
    NASCIMENTO = "NASCIMENTO", "Nascimento"
    TRANSFERENCIA = "TRANSFERENCIA", "Transferência"
    EVOLUCAO = "EVOLUCAO", "Evolução"
    RECLASSIFICACAO = "RECLASSIFICACAO", "Reclassificação"
    ABATE = "ABATE", "Abate"
    VENDA = "VENDA", "Venda"
    MORTE = "MORTE", "Morte"
    CONSUMO_DOACAO = "CONSUMO_DOACAO", "Consumo / doação"
    AJUSTE_INVENTARIO = "AJUSTE_INVENTARIO", "Ajuste de inventário"


#: Geram 2 linhas no razão — a origem e o destino, soma zero (ADR 0002).
TWO_LINE_TYPES = frozenset(
    {
        MovementType.TRANSFERENCIA,
        MovementType.EVOLUCAO,
        MovementType.RECLASSIFICACAO,
    }
)

#: Geram 1 linha positiva.
ENTRY_TYPES = frozenset(
    {MovementType.SALDO_INICIAL, MovementType.COMPRA, MovementType.NASCIMENTO}
)

#: Geram 1 linha negativa.
EXIT_TYPES = frozenset(
    {
        MovementType.ABATE,
        MovementType.VENDA,
        MovementType.MORTE,
        MovementType.CONSUMO_DOACAO,
    }
)

#: Motivo obrigatório — docs/regras-negocio/01#tipos-de-movimento.
TYPES_COM_MOTIVO_OBRIGATORIO = frozenset(
    {MovementType.MORTE, MovementType.AJUSTE_INVENTARIO}
)


class HerdMovement(ReversibleModel):
    """O documento do evento — o que o usuário preenche e enxerga.

    `origin_purchase` / `origin_sale` preenchidos = movimento gerado por uma
    compra ou venda: só se corrige pelo documento de origem.
    """

    code = models.CharField("Código", max_length=30, unique=True)
    date = models.DateField("Data do fato")
    type = models.CharField("Tipo", max_length=20, choices=MovementType.choices)
    season = models.ForeignKey(
        "organizations.Season",
        verbose_name="Safra",
        related_name="movements",
        on_delete=models.PROTECT,
    )
    quantity = models.PositiveIntegerField("Quantidade")
    total_weight_kg = models.DecimalField(
        "Peso total (kg)", max_digits=12, decimal_places=3, null=True, blank=True
    )

    origin_farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda de origem",
        null=True,
        blank=True,
        related_name="movements_out",
        on_delete=models.PROTECT,
    )
    origin_lot = models.ForeignKey(
        "livestock.Lot",
        verbose_name="Lote de origem",
        null=True,
        blank=True,
        related_name="movements_out",
        on_delete=models.PROTECT,
    )
    origin_category = models.ForeignKey(
        "livestock.AnimalCategory",
        verbose_name="Categoria de origem",
        null=True,
        blank=True,
        related_name="movements_out",
        on_delete=models.PROTECT,
    )

    destination_farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda de destino",
        null=True,
        blank=True,
        related_name="movements_in",
        on_delete=models.PROTECT,
    )
    destination_lot = models.ForeignKey(
        "livestock.Lot",
        verbose_name="Lote de destino",
        null=True,
        blank=True,
        related_name="movements_in",
        on_delete=models.PROTECT,
    )
    destination_category = models.ForeignKey(
        "livestock.AnimalCategory",
        verbose_name="Categoria de destino",
        null=True,
        blank=True,
        related_name="movements_in",
        on_delete=models.PROTECT,
    )

    partner = models.ForeignKey(
        "partners.Partner",
        verbose_name="Parceiro",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    origin_purchase = models.ForeignKey(
        "purchases.Purchase",
        verbose_name="Compra de origem",
        null=True,
        blank=True,
        related_name="movements",
        on_delete=models.PROTECT,
    )
    origin_sale = models.ForeignKey(
        "sales.Sale",
        verbose_name="Venda de origem",
        null=True,
        blank=True,
        related_name="movements",
        on_delete=models.PROTECT,
    )
    reason = models.TextField("Motivo", blank=True)
    notes = models.TextField("Observação", blank=True)

    class Meta:
        verbose_name = "Movimentação"
        verbose_name_plural = "Movimentações"
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gt=0), name="herdmovement_quantity_positive"
            ),
        ]

    def __str__(self) -> str:
        return self.code

    def dependentes(self) -> list:
        return []

    def bloqueios(self) -> list[str]:
        return []

    def aplicar_efeitos(self, *, usuario):
        from apps.herd.services import gerar_linhas_do_razao

        gerar_linhas_do_razao(self)

    def desfazer_efeitos(self, *, usuario):
        from apps.herd.services import desfazer_linhas_do_razao

        desfazer_linhas_do_razao(self)


class HerdLedgerEntry(models.Model):
    """As linhas do razão. Geradas pelo sistema, nunca editáveis
    diretamente — append-only, igual ao `AuditEvent` (ver ADR 0006).

    Dois tempos: `date` (o fato — usado para o saldo) e `created_at`
    (o registro — usado para auditoria). `reverses_entry` rastreia a
    linha de compensação até a original.
    """

    SCOPE_FARM_FIELD = "farm"

    movement = models.ForeignKey(
        HerdMovement,
        verbose_name="Movimentação",
        related_name="entries",
        on_delete=models.PROTECT,
    )
    date = models.DateField("Data do fato", db_index=True)
    farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda",
        related_name="ledger_entries",
        on_delete=models.PROTECT,
    )
    lot = models.ForeignKey(
        "livestock.Lot",
        verbose_name="Lote",
        related_name="ledger_entries",
        on_delete=models.PROTECT,
    )
    category = models.ForeignKey(
        "livestock.AnimalCategory",
        verbose_name="Categoria",
        related_name="ledger_entries",
        on_delete=models.PROTECT,
    )
    quantity = models.IntegerField("Quantidade (com sinal)")
    weight_kg = models.DecimalField(
        "Peso (kg, com sinal)", max_digits=12, decimal_places=3, null=True, blank=True
    )
    season = models.ForeignKey(
        "organizations.Season",
        verbose_name="Safra",
        related_name="ledger_entries",
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField("Registrado em", auto_now_add=True)
    reverses_entry = models.ForeignKey(
        "self",
        verbose_name="Reverte a linha",
        null=True,
        blank=True,
        related_name="reversed_by",
        on_delete=models.PROTECT,
    )

    objects = HerdLedgerEntryManager()

    class Meta:
        verbose_name = "Linha do razão do rebanho"
        verbose_name_plural = "Linhas do razão do rebanho"
        ordering = ["date", "id"]
        indexes = [
            models.Index(fields=["farm", "category", "date"]),
            models.Index(fields=["lot", "date"]),
            models.Index(fields=["season"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=~models.Q(quantity=0), name="herdledgerentry_quantity_not_zero"
            ),
        ]

    def __str__(self) -> str:
        sinal = "+" if self.quantity > 0 else ""
        return f"{self.movement.code} · {self.farm} · {self.category} · {sinal}{self.quantity}"

    def save(self, *args, **kwargs):
        if self.pk is not None and HerdLedgerEntry.objects.filter(pk=self.pk).exists():
            raise PermissionError(
                "HerdLedgerEntry é append-only: não existe UPDATE de linha gravada."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("HerdLedgerEntry é append-only: não existe DELETE.")


class WeighingReason(models.TextChoices):
    CONFERENCIA = "CONFERENCIA", "Conferência"
    COMPRA = "COMPRA", "Compra"
    ABATE = "ABATE", "Abate"
    VACINA = "VACINA", "Vacina"
    VENDA = "VENDA", "Venda"


class Weighing(ReversibleModel):
    """Pesagem — evento separado que **não** altera saldo, só peso. Peso
    médio é calculado, nunca digitado (docs/regras-negocio/01#pesagem)."""

    SCOPE_FARM_FIELD = "farm"

    date = models.DateField("Data")
    farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda",
        related_name="weighings",
        on_delete=models.PROTECT,
    )
    lot = models.ForeignKey(
        "livestock.Lot",
        verbose_name="Lote",
        related_name="weighings",
        on_delete=models.PROTECT,
    )
    reason = models.CharField("Motivo", max_length=20, choices=WeighingReason.choices)
    head_count = models.PositiveIntegerField("Cabeças pesadas")
    total_weight_kg = models.DecimalField(
        "Peso total (kg)", max_digits=12, decimal_places=3
    )

    objects = ScopedManager()

    class Meta:
        verbose_name = "Pesagem"
        verbose_name_plural = "Pesagens"
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(head_count__gt=0), name="weighing_head_count_positive"
            ),
            models.CheckConstraint(
                check=models.Q(total_weight_kg__gt=0),
                name="weighing_total_weight_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Pesagem {self.lot} · {self.date:%d/%m/%Y}"

    @property
    def average_weight_kg(self):
        from apps.core.money import safe_div

        return safe_div(self.total_weight_kg, self.head_count)

    def dependentes(self) -> list:
        return []

    def bloqueios(self) -> list[str]:
        return []

    def aplicar_efeitos(self, *, usuario):
        """Pesagem não altera saldo — não há efeito no razão do rebanho."""

    def desfazer_efeitos(self, *, usuario):
        """Simétrico a `aplicar_efeitos`: nada a desfazer no razão."""


class WeighingAnimal(models.Model):
    """Linha opcional de pesagem individual — preserva os dados de brinco
    da planilha, sem que exista ainda uma entidade `Animal` (ADR 0004)."""

    weighing = models.ForeignKey(
        Weighing,
        verbose_name="Pesagem",
        related_name="animals",
        on_delete=models.CASCADE,
    )
    ear_tag = models.CharField("Brinco", max_length=30, blank=True)
    weight_kg = models.DecimalField("Peso (kg)", max_digits=8, decimal_places=3)

    class Meta:
        verbose_name = "Pesagem individual"
        verbose_name_plural = "Pesagens individuais"
        constraints = [
            models.CheckConstraint(
                check=models.Q(weight_kg__gt=0), name="weighinganimal_weight_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.ear_tag or '—'} · {self.weight_kg} kg"
