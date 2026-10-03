"""Indicadores reprodutivos — **calculados**, nunca gravados (regra 6).

Divisor zero ou dado ausente devolve `None` ("—"), nunca `0` (regra 3). O
sistema **não diz** o que é um índice bom ou ruim: a leitura é do produtor e do
consultor.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from apps.core.money import safe_div
from apps.core.reversible import Status
from apps.herd.models import HerdMovement, MovementType
from apps.reproduction.models import GRUPOS, BreedingCycle

CEM = Decimal("100")


def _pct(parte, todo) -> Decimal | None:
    razao = safe_div(Decimal(parte), Decimal(todo)) if todo else None
    return razao * CEM if razao is not None else None


@dataclass(frozen=True)
class IndicadoresReprodutivos:
    expostas: int
    prenhes: int
    vazias: int
    em_reproducao_pct: Decimal | None  # fêmeas em monta ÷ fêmeas do rebanho
    aproveitamento_pct: Decimal | None  # fêmeas em monta ÷ fêmeas acima de 18 meses
    fertilidade_geral_pct: Decimal | None
    fertilidade_por_grupo: dict  # {rótulo: %}
    inseminadas_pct: Decimal | None
    fertilidade_ia_pct: Decimal | None
    fertilidade_touro_pct: Decimal | None
    nascidos: int
    nascidos_machos: int
    nascidos_femeas: int
    desmama_pct: Decimal | None  # desmamados ÷ nascidos


def nascimentos_do_ciclo(ciclo: BreedingCycle) -> dict:
    """Nascimentos **do razão do rebanho** na fazenda e na safra do ciclo."""
    qs = HerdMovement.objects.filter(
        status=Status.CONFIRMADA,
        type=MovementType.NASCIMENTO,
        destination_farm=ciclo.farm,
        date__gte=ciclo.season.start_date,
        date__lte=ciclo.season.end_date,
    )
    total = qs.aggregate(s=Sum("quantity"))["s"] or 0
    machos = (
        qs.filter(destination_category__sex="M").aggregate(s=Sum("quantity"))["s"] or 0
    )
    femeas = (
        qs.filter(destination_category__sex="F").aggregate(s=Sum("quantity"))["s"] or 0
    )
    return {"total": total, "machos": machos, "femeas": femeas}


def indicadores_do_ciclo(ciclo: BreedingCycle) -> IndicadoresReprodutivos:
    expostas = sum(getattr(ciclo, exp) for exp, _, _ in GRUPOS)
    prenhes = sum(getattr(ciclo, pre) for _, pre, _ in GRUPOS)
    por_grupo = {
        rotulo: _pct(getattr(ciclo, pre), getattr(ciclo, exp))
        for exp, pre, rotulo in GRUPOS
    }
    sem_inseminar = expostas - ciclo.inseminated
    nasc = nascimentos_do_ciclo(ciclo)
    return IndicadoresReprodutivos(
        expostas=expostas,
        prenhes=prenhes,
        vazias=expostas - prenhes,
        em_reproducao_pct=_pct(expostas, ciclo.females_total),
        aproveitamento_pct=_pct(expostas, ciclo.females_over_18m),
        fertilidade_geral_pct=_pct(prenhes, expostas),
        fertilidade_por_grupo=por_grupo,
        inseminadas_pct=_pct(ciclo.inseminated, expostas),
        fertilidade_ia_pct=_pct(ciclo.pregnant_by_ai, ciclo.inseminated),
        fertilidade_touro_pct=(
            _pct(ciclo.pregnant_by_bull, sem_inseminar) if sem_inseminar > 0 else None
        ),
        nascidos=nasc["total"],
        nascidos_machos=nasc["machos"],
        nascidos_femeas=nasc["femeas"],
        desmama_pct=_pct(ciclo.weaned_calves, nasc["total"]),
    )
