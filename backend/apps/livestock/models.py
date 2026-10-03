from django.db import models

from apps.core.managers import ScopedManager


class Sex(models.TextChoices):
    MACHO = "M", "Macho"
    FEMEA = "F", "Fêmea"
    INDEFINIDO = "-", "—"


class AnimalCategory(models.Model):
    """Categoria animal: sexo + faixa etária. `age_order` alimenta a
    sugestão de evolução — ver docs/modelo-dados/02-vocabulario.md."""

    name = models.CharField("Nome", max_length=60, unique=True)
    sex = models.CharField(
        "Sexo", max_length=1, choices=Sex.choices, default=Sex.INDEFINIDO
    )
    age_order = models.PositiveSmallIntegerField("Ordem etária", null=True, blank=True)
    display_order = models.PositiveSmallIntegerField("Ordem de exibição", default=0)
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Categoria animal"
        verbose_name_plural = "Categorias animais"
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return self.name


class Breed(models.Model):
    """Raça — semear com Nelore, predominante na operação."""

    name = models.CharField("Nome", max_length=60, unique=True)
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Raça"
        verbose_name_plural = "Raças"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class LotStatus(models.TextChoices):
    ABERTO = "ABERTO", "Aberto"
    ENCERRADO = "ENCERRADO", "Encerrado"
    # Exclusão lógica: o lote criado por uma compra sai da operação junto
    # com ela (docs/regras-negocio/06#o-que-é-desfazer-os-efeitos).
    EXCLUIDO = "EXCLUIDO", "Excluído"


class LotRegime(models.TextChoices):
    """Onde o lote é criado. O confinamento é controlado **de forma resumida**
    (cliente, 2026-10-03): o lote é marcado, e o relatório de confinamento sai
    das pesagens, do razão e dos custos que o sistema já tem."""

    PASTO = "PASTO", "Pasto"
    CONFINAMENTO = "CONFINAMENTO", "Confinamento"


class Lot(models.Model):
    """Lote: unidade de custeio e de desempenho. Quantidade, peso e
    categoria **não são campos** — saem do razão (`HerdLedgerEntry`),
    ver docs/regras-negocio/01-rebanho-movimentacoes.md#relação-com-lote.

    `origin_purchase` preenchido = lote criado por uma compra; desfazer a
    compra leva o lote junto, se ele não tiver mais nada.
    """

    SCOPE_FARM_FIELD = "farm"

    code = models.CharField("Código", max_length=30, unique=True)
    farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda",
        related_name="lots",
        on_delete=models.PROTECT,
    )
    origin_partner = models.ForeignKey(
        "partners.Partner",
        verbose_name="Parceiro de origem",
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
        related_name="created_lots",
        on_delete=models.PROTECT,
    )
    entry_date = models.DateField("Data de entrada")
    exit_date = models.DateField("Data de saída", null=True, blank=True)
    breed = models.ForeignKey(
        Breed, verbose_name="Raça", null=True, blank=True, on_delete=models.PROTECT
    )
    cost_center = models.ForeignKey(
        "costs.CostCenter",
        verbose_name="Centro de custo",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    season = models.ForeignKey(
        "organizations.Season",
        verbose_name="Safra",
        related_name="lots",
        on_delete=models.PROTECT,
    )
    notes = models.TextField("Observações", blank=True)
    regime = models.CharField(
        "Regime", max_length=14, choices=LotRegime.choices, default=LotRegime.PASTO
    )
    status = models.CharField(
        "Situação", max_length=10, choices=LotStatus.choices, default=LotStatus.ABERTO
    )

    objects = ScopedManager()

    class Meta:
        verbose_name = "Lote"
        verbose_name_plural = "Lotes"
        ordering = ["-entry_date", "code"]
        indexes = [models.Index(fields=["farm", "status"])]

    def __str__(self) -> str:
        return self.code
