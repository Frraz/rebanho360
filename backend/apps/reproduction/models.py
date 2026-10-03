"""Reprodução, **de forma resumida** (cliente, 2026-10-03, pendência #38).

Um registro por fazenda e safra de nascimento: quantas fêmeas entraram na
estação de monta, quantas ficaram prenhes (por categoria e por método) e
quantos bezerros foram desmamados. É o que a aba `DADOS REPRODUTIVOS` do
consultor pede — sem agenda de manejo, sem animal a animal.

Nada de índice é campo: fertilidade, % de inseminadas, desmama e os demais saem
de `indicators.py` (regra 6). Os **nascimentos** não são digitados aqui: vêm do
razão do rebanho (`NASCIMENTO`), que é o que move o saldo.
"""

from django.db import models
from django.db.models import F, Q

from apps.core.managers import ScopedManager
from apps.core.reversible import ReversibleModel, Status

#: (campo de expostas, campo de prenhes, rótulo) de cada grupo da estação.
GRUPOS = (
    ("heifers_exposed", "heifers_pregnant", "Novilhas"),
    ("challenge_heifers_exposed", "challenge_heifers_pregnant", "Novilhas desafio"),
    ("primiparous_exposed", "primiparous_pregnant", "Primíparas"),
    ("cows_exposed", "cows_pregnant", "Vacas"),
)


def _n(rotulo: str) -> models.PositiveIntegerField:
    return models.PositiveIntegerField(rotulo, default=0)


class BreedingCycle(ReversibleModel):
    """O ciclo reprodutivo de uma fazenda numa safra de nascimento."""

    SCOPE_FARM_FIELD = "farm"

    code = models.CharField("Código", max_length=30, unique=True)
    farm = models.ForeignKey(
        "properties.Farm",
        verbose_name="Fazenda",
        related_name="breeding_cycles",
        on_delete=models.PROTECT,
    )
    season = models.ForeignKey(
        "organizations.Season",
        verbose_name="Safra de nascimento",
        related_name="breeding_cycles",
        on_delete=models.PROTECT,
    )
    breeding_months = models.PositiveSmallIntegerField(
        "Tempo de estação (meses)", null=True, blank=True
    )
    females_total = _n("Total de fêmeas no rebanho")
    females_over_18m = _n("Fêmeas acima de 18 meses")

    heifers_exposed = _n("Novilhas em monta")
    heifers_pregnant = _n("Novilhas prenhes")
    challenge_heifers_exposed = _n("Novilhas desafio em monta")
    challenge_heifers_pregnant = _n("Novilhas desafio prenhes")
    primiparous_exposed = _n("Primíparas em monta")
    primiparous_pregnant = _n("Primíparas prenhes")
    cows_exposed = _n("Vacas em monta")
    cows_pregnant = _n("Vacas prenhes")

    inseminated = _n("Fêmeas inseminadas (IA/IATF)")
    pregnant_by_ai = _n("Prenhes por IA/IATF")
    pregnant_by_bull = _n("Prenhes por touro")

    weaned_calves = _n("Bezerros desmamados")
    notes = models.TextField("Observações", blank=True)

    objects = ScopedManager()

    class Meta:
        verbose_name = "Ciclo reprodutivo"
        verbose_name_plural = "Ciclos reprodutivos"
        ordering = ["-season__start_date", "farm__name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["farm", "season"],
                condition=~Q(status=Status.EXCLUIDA),
                name="uniq_breeding_cycle_farm_season",
            ),
            models.CheckConstraint(
                check=Q(heifers_pregnant__lte=F("heifers_exposed"))
                & Q(challenge_heifers_pregnant__lte=F("challenge_heifers_exposed"))
                & Q(primiparous_pregnant__lte=F("primiparous_exposed"))
                & Q(cows_pregnant__lte=F("cows_exposed")),
                name="breeding_pregnant_within_exposed",
            ),
            models.CheckConstraint(
                check=Q(pregnant_by_ai__lte=F("inseminated")),
                name="breeding_ai_pregnant_within_inseminated",
            ),
        ]

    def __str__(self) -> str:
        return self.code

    # ---- contrato ReversibleModel: o ciclo não mexe em saldo nem em custo ----

    def aplicar_efeitos(self, *, usuario):
        """Registro de apoio: não há efeito em rebanho, custo ou título."""

    def desfazer_efeitos(self, *, usuario):
        """Simétrico a `aplicar_efeitos`."""

    def dependentes(self) -> list:
        return []

    def bloqueios(self) -> list:
        return []
