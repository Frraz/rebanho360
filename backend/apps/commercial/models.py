"""Cadastros comerciais da Fase 5: o que o ciclo de compra consulta e nunca
fixa no código — classificação de carcaça, tipos de tributo/taxa/desconto e
regras de comissão (docs/regras-negocio/08-ciclo-de-compra.md)."""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class CarcassClass(models.Model):
    """Classificação de carcaça (magro, gordura escassa, mediana…).

    **Cadastro parametrizável, nunca fixo no código** — o legado classifica
    de um jeito e outro frigorífico, de outro. As seis do relatório
    `04_Conferencia_do_Acerto` vêm semeadas, e só pelo seed.
    """

    code = models.CharField("Código", max_length=20, unique=True)
    name = models.CharField("Nome", max_length=80)
    display_order = models.PositiveSmallIntegerField("Ordem", default=0)
    # Só **sugere** a faixa na tela do romaneio; nunca decide (pendência #20).
    default_band = models.PositiveSmallIntegerField(
        "Faixa sugerida",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Opcional. Só sugere a faixa no romaneio; quem escolhe é você.",
    )
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Classificação de carcaça"
        verbose_name_plural = "Classificações de carcaça"
        ordering = ["display_order", "name"]
        constraints = [
            models.CheckConstraint(
                check=Q(default_band__isnull=True)
                | (Q(default_band__gte=1) & Q(default_band__lte=5)),
                name="carcassclass_band_1_to_5",
            )
        ]

    def __str__(self) -> str:
        return self.name


class TaxNature(models.TextChoices):
    TRIBUTO = "TRIBUTO", "Tributo"
    TAXA = "TAXA", "Taxa"
    DESCONTO = "DESCONTO", "Desconto"
    ADIANTAMENTO = "ADIANTAMENTO", "Adiantamento"
    CREDITO = "CREDITO", "Crédito"


class TaxType(models.Model):
    """Tipo de tributo, taxa, desconto, adiantamento ou crédito do acerto.

    **Sem alíquota, sem base de cálculo, sem fórmula.** A regra tributária não
    foi confirmada com o contador (pendência #21) e implementá-la por dedução
    gera passivo: o valor é digitado no acerto. O que a `nature` decide é só o
    efeito do valor — ver `procurement.settlement.TRATAMENTO_POR_NATUREZA`.
    """

    name = models.CharField("Nome", max_length=80, unique=True)
    nature = models.CharField(
        "Natureza", max_length=14, choices=TaxNature.choices, default=TaxNature.TAXA
    )
    display_order = models.PositiveSmallIntegerField("Ordem", default=0)
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Tipo de tributo, taxa ou desconto"
        verbose_name_plural = "Tipos de tributo, taxa e desconto"
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return self.name


class CommissionType(models.TextChoices):
    PERCENTUAL = "PERCENTUAL", "Percentual"
    POR_CABECA = "POR_CABECA", "Valor por cabeça"


class CommissionBase(models.TextChoices):
    BRUTO = "BRUTO", "Valor bruto dos animais"
    LIQUIDO = "LIQUIDO", "Valor líquido (sem frete e tributos)"


class CommissionRule(models.Model):
    """Regra de comissão, por comprador, categoria e vigência.

    O cadastro **muda**; a operação não. Quando o compromisso é aprovado, a
    regra aplicada é copiada para `procurement.Commission` (snapshot) — mudar
    esta tabela em março não toca a operação de janeiro.

    Pendência #4: base bruta ou líquida? Cada regra escolhe; o padrão é `BRUTO`.
    """

    commissioned = models.ForeignKey(
        "partners.Partner",
        verbose_name="Comissionado",
        null=True,
        blank=True,
        related_name="commission_rules",
        on_delete=models.PROTECT,
        help_text="Vazio = vale para qualquer comprador.",
    )
    category = models.ForeignKey(
        "livestock.AnimalCategory",
        verbose_name="Categoria",
        null=True,
        blank=True,
        related_name="commission_rules",
        on_delete=models.PROTECT,
        help_text="Vazio = vale para qualquer categoria.",
    )
    type = models.CharField(
        "Tipo",
        max_length=12,
        choices=CommissionType.choices,
        default=CommissionType.PERCENTUAL,
    )
    base = models.CharField(
        "Base do percentual",
        max_length=8,
        choices=CommissionBase.choices,
        default=CommissionBase.BRUTO,
    )
    # Percentual (1,5 = 1,5%) ou R$ por cabeça, conforme o tipo.
    value = models.DecimalField(
        "Valor (% ou R$ por cabeça)", max_digits=12, decimal_places=4
    )
    valid_from = models.DateField("Vale desde")
    valid_to = models.DateField("Vale até", null=True, blank=True)
    is_active = models.BooleanField("Ativa", default=True)
    notes = models.TextField("Observações", blank=True)

    class Meta:
        verbose_name = "Regra de comissão"
        verbose_name_plural = "Regras de comissão"
        ordering = ["-valid_from", "-id"]
        constraints = [
            models.CheckConstraint(
                check=Q(value__gt=0), name="commissionrule_value_positive"
            ),
            models.CheckConstraint(
                check=Q(valid_to__isnull=True)
                | Q(valid_to__gte=models.F("valid_from")),
                name="commissionrule_valid_range",
            ),
        ]

    def __str__(self) -> str:
        quem = self.commissioned or "qualquer comprador"
        return f"{quem} · {self.get_type_display()} {self.value}"
