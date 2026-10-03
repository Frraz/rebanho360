"""Infraestrutura e parque de máquinas, **de forma resumida** (cliente,
2026-10-03): o que as abas `RESUMO DE INFRAESTRUTURA` e `PARQUE DE MÁQUINAS` do
consultor controlam, sem virar um módulo de manutenção.

- `FarmStructure`: curral, cocho, bebedouro… com as medidas que importam; as
  razões (m² por animal, cm de cocho por cabeça) são **calculadas**.
- `Machine` e `MachineLog`: o cadastro da máquina e o que ela trabalhou, gastou
  de combustível e custou de manutenção; o **custo por hora** é calculado.

Valor, custo por hora e razões não são campos (regra 6). Divisor zero devolve
`None`, nunca `0` (regra 3).
"""

from decimal import Decimal

from django.db import models
from django.db.models import Q

from apps.core.managers import ScopedManager
from apps.core.money import safe_div
from apps.core.reversible import ReversibleModel


class StructureKind(models.TextChoices):
    CURRAL = "CURRAL", "Curral"
    COCHO = "COCHO", "Cocho"
    BEBEDOURO = "BEBEDOURO", "Bebedouro"
    CERCA = "CERCA", "Cerca"
    BARRACAO = "BARRACAO", "Barracão / galpão"
    OUTRO = "OUTRO", "Outro"


class FarmStructure(models.Model):
    """Uma estrutura da fazenda. Cadastro: se muda, corrige-se; sai da
    operação por `is_active`, nunca do banco."""

    SCOPE_FARM_FIELD = "farm"

    farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda",
        related_name="structures",
        on_delete=models.PROTECT,
    )
    kind = models.CharField("Tipo", max_length=12, choices=StructureKind.choices)
    name = models.CharField("Identificação", max_length=80)
    area_m2 = models.DecimalField(
        "Área (m²)", max_digits=12, decimal_places=2, null=True, blank=True
    )
    trough_m = models.DecimalField(
        "Cocho (m)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    waterers = models.PositiveSmallIntegerField("Bebedouros", null=True, blank=True)
    animals = models.PositiveIntegerField(
        "Animais atendidos",
        null=True,
        blank=True,
        help_text="Quantos animais usam esta estrutura — base das razões abaixo.",
    )
    notes = models.TextField("Observações", blank=True)
    is_active = models.BooleanField("Ativa", default=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Estrutura da fazenda"
        verbose_name_plural = "Estruturas da fazenda"
        ordering = ["farm__name", "kind", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["farm", "kind", "name"], name="uniq_structure_farm_kind_name"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.name}"

    @property
    def area_por_animal(self) -> Decimal | None:
        return safe_div(self.area_m2, self.animals) if self.area_m2 else None

    @property
    def cocho_cm_por_cabeca(self) -> Decimal | None:
        if not self.trough_m:
            return None
        razao = safe_div(self.trough_m * 100, self.animals)
        return razao

    @property
    def animais_por_bebedouro(self) -> Decimal | None:
        return (
            safe_div(Decimal(self.animals), Decimal(self.waterers))
            if (self.animals and self.waterers)
            else None
        )


class MachineKind(models.TextChoices):
    TRATOR = "TRATOR", "Trator"
    IMPLEMENTO = "IMPLEMENTO", "Implemento"
    CAMINHAO = "CAMINHAO", "Caminhão"
    UTILITARIO = "UTILITARIO", "Utilitário / caminhonete"
    OUTRO = "OUTRO", "Outro"


class Machine(models.Model):
    SCOPE_FARM_FIELD = "farm"

    farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda",
        related_name="machines",
        on_delete=models.PROTECT,
    )
    name = models.CharField("Máquina", max_length=80)
    kind = models.CharField("Tipo", max_length=12, choices=MachineKind.choices)
    new_value = models.DecimalField(
        "Valor da máquina nova (R$)",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    notes = models.TextField("Observações", blank=True)
    is_active = models.BooleanField("Ativa", default=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Máquina"
        verbose_name_plural = "Máquinas"
        ordering = ["farm__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["farm", "name"], name="uniq_machine_farm_name"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class MachineLog(ReversibleModel):
    """O que a máquina trabalhou e gastou num período. Lançamento editável e
    excluível, com motivo e auditoria (regra 5). Não gera custo: o custo do
    parque de máquinas segue sendo lançado em Custos (centro PARQUE DE MÁQUINAS)."""

    SCOPE_FARM_FIELD = "machine__farm"

    code = models.CharField("Código", max_length=30, unique=True)
    machine = models.ForeignKey(
        Machine, verbose_name="Máquina", related_name="logs", on_delete=models.PROTECT
    )
    date = models.DateField("Data")
    hours = models.DecimalField("Horas trabalhadas", max_digits=9, decimal_places=2)
    fuel_liters = models.DecimalField(
        "Combustível (litros)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    fuel_cost = models.DecimalField(
        "Combustível (R$)", max_digits=12, decimal_places=2, null=True, blank=True
    )
    maintenance_cost = models.DecimalField(
        "Manutenção (R$)", max_digits=12, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField("Observações", blank=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Uso da máquina"
        verbose_name_plural = "Usos das máquinas"
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                check=Q(hours__gt=0), name="machinelog_hours_positive"
            ),
            models.CheckConstraint(
                check=(Q(fuel_liters__isnull=True) | Q(fuel_liters__gte=0))
                & (Q(fuel_cost__isnull=True) | Q(fuel_cost__gte=0))
                & (Q(maintenance_cost__isnull=True) | Q(maintenance_cost__gte=0)),
                name="machinelog_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return self.code

    def aplicar_efeitos(self, *, usuario):
        """Registro de apoio: não mexe em rebanho, custo nem título."""

    def desfazer_efeitos(self, *, usuario):
        """Simétrico a `aplicar_efeitos`."""
