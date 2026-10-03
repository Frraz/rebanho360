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


class PaymentCondition(models.Model):
    """Condição de pagamento ou recebimento: à vista, 4 dias, 30 dias,
    parcelado… **Cadastro do usuário** (cliente, 2026-10-03, pendências #16 e
    #35): cada empresa cria as suas e escolhe na compra, no compromisso e na
    venda. O sistema não presume uma regra única.

    `days` guarda os dias após a data da operação, separados por vírgula: `0`
    (à vista), `30` (prazo único) ou `30,60,90` (parcelado em três vezes).
    """

    name = models.CharField("Nome", max_length=80, unique=True)
    days = models.CharField(
        "Dias",
        max_length=60,
        default="0",
        help_text="Dias depois da data da operação. Um número = à vista ou prazo "
        "único; vários separados por vírgula = parcelado (ex.: 30,60,90).",
    )
    is_active = models.BooleanField("Ativa", default=True)
    display_order = models.PositiveSmallIntegerField("Ordem", default=0)

    class Meta:
        verbose_name = "Condição de pagamento"
        verbose_name_plural = "Condições de pagamento"
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def prazos(self) -> list[int]:
        return parse_prazos(self.days)

    @property
    def parcelado(self) -> bool:
        return len(self.prazos) > 1

    @property
    def primeiro_prazo(self) -> int:
        return self.prazos[0]

    @property
    def resumo(self) -> str:
        prazos = self.prazos
        if prazos == [0]:
            return "à vista"
        if len(prazos) == 1:
            return f"{prazos[0]} dias"
        return f"{len(prazos)} parcelas: " + ", ".join(f"{d} dias" for d in prazos)


def parse_prazos(texto: str) -> list[int]:
    """`"30, 60,90"` → `[30, 60, 90]`. Levanta `ValueError` se não for número
    inteiro não negativo ou se estiver fora de ordem."""
    partes = [p.strip() for p in (texto or "").split(",") if p.strip()]
    if not partes:
        raise ValueError("Informe pelo menos um prazo.")
    prazos = []
    for parte in partes:
        if not parte.isdigit():
            raise ValueError(f"'{parte}' não é um número de dias.")
        prazos.append(int(parte))
    if prazos != sorted(prazos):
        raise ValueError("Os prazos devem estar em ordem crescente.")
    if len(set(prazos)) != len(prazos):
        raise ValueError("Há prazos repetidos.")
    return prazos


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
    # O que o valor faz no acerto. Vazio = o padrão da natureza (ver
    # `procurement.settlement.TRATAMENTO_POR_NATUREZA`). O cliente não quer que
    # o sistema presuma quem arca com cada item: aqui o usuário decide por tipo.
    effect = models.CharField(
        "Efeito no acerto",
        max_length=20,
        blank=True,
        choices=[
            ("CUSTO", "Soma ao custo de aquisição e gera título"),
            ("DESCONTO_NO_ANIMAL", "Reduz o valor dos animais"),
            ("ABATE_NO_LIQUIDO", "Reduz só o líquido a pagar ao vendedor"),
        ],
        help_text="Vazio = o padrão da natureza escolhida.",
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
    # Só na comissão da operação (não em regra): negociação que não segue
    # percentual — o valor é informado diretamente (cliente, 2026-10-03).
    VALOR = "VALOR", "Valor informado (R$)"


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
