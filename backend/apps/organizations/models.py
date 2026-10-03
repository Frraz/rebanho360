from django.db import models


class Company(models.Model):
    """Empresa. Ver docs/modelo-dados/01-entidades.md#espinha-organizacional."""

    name = models.CharField("Nome", max_length=150)
    legal_name = models.CharField("Razão social", max_length=200, blank=True)
    tax_id = models.CharField("CNPJ", max_length=18, blank=True)
    address = models.CharField("Endereço", max_length=200, blank=True)
    city = models.CharField("Cidade", max_length=100, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    phone = models.CharField("Telefone", max_length=20, blank=True)
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class BusinessUnit(models.Model):
    """Unidade. Agrupa fazendas por região ou operação — pode haver só uma."""

    company = models.ForeignKey(
        Company, verbose_name="Empresa", related_name="units", on_delete=models.PROTECT
    )
    name = models.CharField("Nome", max_length=150)
    code = models.CharField("Código", max_length=20)
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Unidade"
        verbose_name_plural = "Unidades"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"], name="uniq_businessunit_company_code"
            )
        ]

    def __str__(self) -> str:
        return self.name


class SeasonStatus(models.TextChoices):
    ABERTA = "ABERTA", "Aberta"
    ENCERRADA = "ENCERRADA", "Encerrada"


class Season(models.Model):
    """Safra. Eixo de comparação de todo o negócio — toda transação carrega
    uma safra."""

    company = models.ForeignKey(
        Company,
        verbose_name="Empresa",
        related_name="seasons",
        on_delete=models.PROTECT,
    )
    name = models.CharField("Nome", max_length=20, help_text="Ex.: 2025/2026")
    start_date = models.DateField("Início")
    end_date = models.DateField("Fim")
    status = models.CharField(
        "Situação",
        max_length=10,
        choices=SeasonStatus.choices,
        default=SeasonStatus.ABERTA,
    )
    is_current = models.BooleanField("Safra corrente", default=False)

    class Meta:
        verbose_name = "Safra"
        verbose_name_plural = "Safras"
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_date__gt=models.F("start_date")),
                name="season_end_after_start",
            ),
            models.UniqueConstraint(
                fields=["company"],
                condition=models.Q(is_current=True),
                name="uniq_current_season_per_company",
            ),
        ]

    def __str__(self) -> str:
        return self.name
