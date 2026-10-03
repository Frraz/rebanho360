"""Venda e abate — a saída de animais para um comprador ou frigorífico.

Ver docs/regras-negocio/04-venda-e-abate.md. `Sale` serve para abate **e**
para venda de animal vivo: a diferença está no campo `type`, não em duas
tabelas.
"""

from django.db import models
from django.db.models import F, Q

from apps.core.managers import ScopedManager
from apps.core.reversible import ReversibleModel, Status


class SaleType(models.TextChoices):
    ABATE = "ABATE", "Abate"
    VENDA = "VENDA", "Venda de animal vivo"


class SaleForm(models.TextChoices):
    PASTO = "PASTO", "Pasto"
    CONFINAMENTO = "CONFINAMENTO", "Confinamento"


class Sale(ReversibleModel):
    """A venda. Confirmar dá saída no rebanho, na mesma transação, e — com o
    lote a saldo zero — encerra o lote.

    Peso médio, carcaça média, rendimento, valor/cabeça e valor/@ **não são
    campos**: saem de `CarcassService` (regra 6 do CLAUDE.md). É o que a
    planilha errava, gravando sete derivados como valor.
    """

    code = models.CharField("Código", max_length=30, unique=True)
    date = models.DateField("Data")
    season = models.ForeignKey(
        "organizations.Season",
        verbose_name="Safra",
        related_name="sales",
        on_delete=models.PROTECT,
    )
    type = models.CharField("Tipo", max_length=10, choices=SaleType.choices)
    buyer = models.ForeignKey(
        "partners.Partner",
        verbose_name="Comprador",
        related_name="purchases_from_us",
        on_delete=models.PROTECT,
    )
    farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda",
        related_name="sales",
        on_delete=models.PROTECT,
    )
    lot = models.ForeignKey(
        "livestock.Lot",
        verbose_name="Lote",
        related_name="sales",
        on_delete=models.PROTECT,
    )
    category = models.ForeignKey(
        "livestock.AnimalCategory",
        verbose_name="Categoria",
        related_name="sales",
        on_delete=models.PROTECT,
    )
    head_count = models.PositiveIntegerField("Cabeças")
    total_weight_kg = models.DecimalField(
        "Peso vivo de saída (kg)", max_digits=12, decimal_places=3
    )
    # Só em ABATE, e só quando o romaneio do frigorífico chega: um abate pode
    # ser confirmado sem ela (as cabeças já saíram) e fica como pendência —
    # pendência #13.
    carcass_weight_kg = models.DecimalField(
        "Peso de carcaça (kg)", max_digits=12, decimal_places=3, null=True, blank=True
    )
    total_value = models.DecimalField(
        "Valor total (R$)", max_digits=14, decimal_places=2
    )
    sale_form = models.CharField(
        "Forma", max_length=15, choices=SaleForm.choices, default=SaleForm.PASTO
    )
    # Só dá o vencimento do título a receber que a confirmação gera (data +
    # prazo). Vazio = vence na data da venda. Pendência #16 (Fase 4).
    payment_days = models.PositiveSmallIntegerField(
        "Prazo de recebimento (dias)", null=True, blank=True
    )
    payment_condition = models.ForeignKey(
        "commercial.PaymentCondition",
        verbose_name="Condição de recebimento",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )
    # Rendimento **oficial**, o que o frigorífico informa no romaneio (cliente,
    # 2026-10-03, #7): prevalece sobre o calculado (carcaça ÷ peso vivo).
    reported_yield_percent = models.DecimalField(
        "Rendimento informado pelo frigorífico (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    # Texto livre, preservado e sem efeito em cálculo — pendência #3.
    partnership = models.CharField("Parceria", max_length=100, blank=True)
    notes = models.TextField("Observações", blank=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Venda"
        verbose_name_plural = "Vendas e abates"
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                check=Q(head_count__gt=0), name="sale_head_count_positive"
            ),
            models.CheckConstraint(
                check=Q(total_weight_kg__gt=0), name="sale_total_weight_positive"
            ),
            models.CheckConstraint(
                check=Q(total_value__gt=0), name="sale_total_value_positive"
            ),
            models.CheckConstraint(
                check=Q(carcass_weight_kg__isnull=True) | Q(carcass_weight_kg__gt=0),
                name="sale_carcass_positive",
            ),
            # Rendimento acima de 100% é erro de digitação (04#validações).
            models.CheckConstraint(
                check=Q(carcass_weight_kg__isnull=True)
                | Q(carcass_weight_kg__lt=F("total_weight_kg")),
                name="sale_carcass_below_live_weight",
            ),
            # Venda de animal vivo não tem carcaça.
            models.CheckConstraint(
                check=Q(type=SaleType.ABATE) | Q(carcass_weight_kg__isnull=True),
                name="sale_carcass_only_in_abate",
            ),
        ]
        indexes = [
            models.Index(fields=["farm", "season"]),
            models.Index(fields=["lot", "status"]),
        ]

    def __str__(self) -> str:
        return self.code

    @property
    def sem_carcaca(self) -> bool:
        """Abate cujo romaneio ainda não foi informado: pendência do painel."""
        return self.type == SaleType.ABATE and self.carcass_weight_kg is None

    # ---- contrato ReversibleModel -------------------------------------

    def bloqueios(self) -> list:
        from apps.finance.selectors import bloqueios_financeiros_da_venda
        from apps.organizations.models import SeasonStatus

        bloqueios = []
        if self.season.status == SeasonStatus.ENCERRADA:
            bloqueios.append(
                f"a safra {self.season.name} está encerrada. Peça a um "
                "administrador para reabrir a safra antes de editar ou excluir."
            )
        # Título desta venda com recebimento baixado também bloqueia:
        # "desfaça antes a baixa do pagamento" (docs/ux/01#editar-e-excluir).
        return [*bloqueios_financeiros_da_venda(self), *bloqueios]

    def dependentes(self) -> list:
        # Nada depende da venda além do pagamento (Fase 4). Devolver os
        # animais ao lote só *acrescenta* saldo na data original: não há
        # saldo posterior que possa ficar negativo por causa disso.
        return []

    def descrever_efeitos(self) -> list[str]:
        efeitos = [
            f"saída de {self.head_count} cabeças de {self.category} do lote "
            f"{self.lot.code} ({self.farm}) — elas voltam ao saldo na data original, "
            f"{self.date:%d/%m/%Y}"
        ]
        if self.lot.status == "ENCERRADO":
            efeitos.append(f"o lote {self.lot.code} volta a ficar aberto")
        from apps.finance.services import descrever_titulos_da_origem

        efeitos.extend(descrever_titulos_da_origem(self))
        return efeitos

    def aplicar_efeitos(self, *, usuario):
        from apps.sales.services import aplicar_efeitos_da_venda

        aplicar_efeitos_da_venda(self, usuario=usuario)

    def desfazer_efeitos(self, *, usuario):
        from apps.sales.services import desfazer_efeitos_da_venda

        desfazer_efeitos_da_venda(self, usuario=usuario)


__all__ = ["Sale", "SaleType", "SaleForm", "Status"]
