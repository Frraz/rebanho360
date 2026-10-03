from django.db import models

from apps.core.managers import ScopedManager


class Farm(models.Model):
    """Fazenda. Aberta na F0-06 com campos mínimos (FK preguiçosa de
    `UserFarmAccess`); ganha os demais campos aqui, na F0-15, para que o
    `seed_demo` povoe o cadastro real — ver
    docs/modelo-dados/01-entidades.md#espinha-organizacional.
    """

    business_unit = models.ForeignKey(
        "organizations.BusinessUnit",
        verbose_name="Unidade",
        related_name="farms",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    name = models.CharField("Nome", max_length=120)
    code = models.CharField("Código", max_length=20, unique=True)
    city = models.CharField("Cidade", max_length=100, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    total_area_ha = models.DecimalField(
        "Área total (ha)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    pasture_area_ha = models.DecimalField(
        "Área de pastagem (ha)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Fazenda"
        verbose_name_plural = "Fazendas"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class PaddockType(models.TextChoices):
    PASTAGEM = "PASTAGEM", "Pastagem"
    SILAGEM = "SILAGEM", "Silagem"
    BENFEITORIA = "BENFEITORIA", "Benfeitoria"
    RESERVA_APP = "RESERVA_APP", "Reserva / APP"
    ARRENDAMENTO = "ARRENDAMENTO", "Arrendamento"


class Paddock(models.Model):
    """Área / Pasto (sinônimo regional: Retiro)."""

    SCOPE_FARM_FIELD = "farm"

    farm = models.ForeignKey(
        Farm, verbose_name="Fazenda", related_name="paddocks", on_delete=models.CASCADE
    )
    name = models.CharField("Nome", max_length=100)
    area_ha = models.DecimalField(
        "Área (ha)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    type = models.CharField("Tipo", max_length=20, choices=PaddockType.choices)
    capacity_ua = models.DecimalField(
        "Capacidade (UA)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    is_active = models.BooleanField("Ativa", default=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Área / Pasto"
        verbose_name_plural = "Áreas / Pastos"
        ordering = ["farm__name", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.farm})"
