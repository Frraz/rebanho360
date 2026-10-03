"""Taxa de mortalidade — docs/regras-negocio/05#taxa-de-mortalidade.

    mortalidade % = cabeças MORTE no período ÷ saldo médio do período × 100

O saldo médio é a média **diária** do rebanho: cabeça-dia ÷ dias do período.
Fonte única: o painel de pendências e qualquer relatório chamam esta conta.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from apps.core.money import safe_div
from apps.core.reversible import Status
from apps.herd.models import HerdMovement, MovementType

CEM = Decimal("100")


@dataclass(frozen=True)
class TaxaDeMortalidade:
    mortes: int
    saldo_medio: Decimal | None
    taxa: Decimal | None  # % — `None` sem rebanho no período
    dias: int


def taxa_de_mortalidade(
    *, farm, start: datetime.date, end: datetime.date
) -> TaxaDeMortalidade:
    from apps.costs.allocation import cabecas_dia_por_lote

    dias = (end - start).days + 1
    mortes = (
        HerdMovement.objects.filter(
            status=Status.CONFIRMADA,
            type=MovementType.MORTE,
            origin_farm=farm,
            date__gte=start,
            date__lte=end,
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    cabecas_dia = sum(
        cabecas_dia_por_lote(farm=farm, start=start, end=end).values(),
        Decimal("0"),
    )
    # Sem nenhum animal no período não há saldo médio: é falta de dado, não
    # "saldo médio zero" — e daí não há taxa (regra 3).
    saldo_medio = safe_div(cabecas_dia, dias) if cabecas_dia else None
    taxa = safe_div(Decimal(mortes), saldo_medio)
    return TaxaDeMortalidade(
        mortes=mortes,
        saldo_medio=saldo_medio,
        taxa=taxa * CEM if taxa is not None else None,
        dias=dias,
    )
