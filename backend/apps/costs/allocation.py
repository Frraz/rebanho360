"""`CostAllocationService` — rateio de custo indireto entre os lotes.

Custo direto (com `lot`) vai inteiro ao lote. Custo indireto (sem `lot`)
é rateado pelo critério do centro de custo — por padrão, **cabeça-dia**:

    cota_lote = custo_indireto × peso_lote ÷ Σ(peso de todos os lotes da fazenda)

O critério aplicado sai **junto do resultado**, para o número ser
explicável meses depois (docs/regras-negocio/05#rateio-de-custo-indireto).

O que importa: a soma das cotas é exatamente igual ao custo original. Sem
centavo perdido — o resto do arredondamento vai, um centavo por vez, para
quem tem a maior fração (método do maior resto).
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal, localcontext

from django.db.models import Sum

from apps.core.exceptions import BusinessError
from apps.core.reversible import Status
from apps.costs.models import AllocationCriterion, CostEntry
from apps.herd.models import HerdLedgerEntry

CENT = Decimal("0.01")


def ratear_em_centavos(total: Decimal, pesos: dict) -> dict:
    """Divide `total` proporcionalmente a `pesos` sem perder centavo.

    Devolve `{chave: valor}` cuja soma é exatamente `total` (que deve estar
    em centavos). Pesos zero ou negativos ficam de fora. Sem nenhum peso
    positivo devolve `{}` — o chamador decide o que fazer com o valor sem
    base de rateio (ver `RateioCentro.sem_base`).
    """
    positivos = {chave: peso for chave, peso in pesos.items() if peso > 0}
    soma = sum(positivos.values(), Decimal("0"))
    if not positivos or soma <= 0:
        return {}

    with localcontext() as ctx:
        ctx.prec = 60
        centavos = int((total / CENT).to_integral_value())
        exatos = {k: Decimal(centavos) * p / soma for k, p in positivos.items()}
        pisos = {
            k: int(v.to_integral_value(rounding=ROUND_FLOOR)) for k, v in exatos.items()
        }
        resto = centavos - sum(pisos.values())
        # Maior fração primeiro; empate resolvido pela ordem de entrada, que
        # é determinística — duas execuções dão o mesmo resultado.
        ordem = sorted(
            positivos,
            key=lambda k: (-(exatos[k] - pisos[k]), list(positivos).index(k)),
        )
        for chave in ordem[:resto]:
            pisos[chave] += 1
    return {k: Decimal(v) * CENT for k, v in pisos.items()}


def cabecas_dia_por_lote(*, farm, start: datetime.date, end: datetime.date) -> dict:
    """`{lot_id: cabeça-dia}` no período `[start, end]`, a partir do razão.

    O movimento do dia vale a partir do próprio dia: um lote que entrou no
    dia 10 e foi consultado até o dia 10 tem 1 dia de cabeças.
    """
    linhas = (
        HerdLedgerEntry.objects.filter(farm=farm, date__lte=end)
        .order_by("date", "id")
        .values_list("lot_id", "date", "quantity")
    )
    saldo_antes: dict[int, int] = defaultdict(int)
    eventos: dict[int, list] = defaultdict(list)
    for lot_id, data, quantidade in linhas:
        if data < start:
            saldo_antes[lot_id] += quantidade
        else:
            eventos[lot_id].append((data, quantidade))

    resultado: dict[int, Decimal] = {}
    for lot_id in set(saldo_antes) | set(eventos):
        atual = saldo_antes[lot_id]
        cursor = start
        acumulado = 0
        for data, quantidade in eventos[lot_id]:
            acumulado += atual * (data - cursor).days
            atual += quantidade
            cursor = data
        acumulado += atual * ((end - cursor).days + 1)
        if acumulado > 0:
            resultado[lot_id] = Decimal(acumulado)
    return resultado


def cabecas_no_fim_por_lote(*, farm, end: datetime.date) -> dict:
    """`{lot_id: cabeças}` na data `end` — critério `POR_CABECA_SIMPLES`."""
    somas = (
        HerdLedgerEntry.objects.filter(farm=farm, date__lte=end)
        .values("lot_id")
        .annotate(total=Sum("quantity"))
    )
    return {
        linha["lot_id"]: Decimal(linha["total"])
        for linha in somas
        if linha["total"] and linha["total"] > 0
    }


@dataclass
class RateioCentro:
    """O rateio de um centro de custo: o critério fica gravado aqui."""

    centro: object
    criterio: str
    total: Decimal
    cotas: dict = field(default_factory=dict)  # {lot_id: valor}
    # Custo que não achou onde pousar (fazenda sem nenhum animal no período).
    # Aparece como pendência — nunca some, nunca vira cota de um lote qualquer.
    sem_base: Decimal = Decimal("0")

    @property
    def criterio_rotulo(self) -> str:
        return AllocationCriterion(self.criterio).label


@dataclass
class RateioResultado:
    farm: object
    start: datetime.date
    end: datetime.date
    centros: list = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((c.total for c in self.centros), Decimal("0"))

    @property
    def sem_base(self) -> Decimal:
        return sum((c.sem_base for c in self.centros), Decimal("0"))

    @property
    def cotas_por_lote(self) -> dict:
        soma: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        for centro in self.centros:
            for lot_id, valor in centro.cotas.items():
                soma[lot_id] += valor
        return dict(soma)


def _pesos_do_criterio(criterio, *, farm, start, end, centro, pesos_manuais):
    if criterio == AllocationCriterion.POR_CABECA_DIA:
        return cabecas_dia_por_lote(farm=farm, start=start, end=end)
    if criterio == AllocationCriterion.POR_CABECA_SIMPLES:
        return cabecas_no_fim_por_lote(farm=farm, end=end)
    if criterio == AllocationCriterion.MANUAL:
        pesos = (pesos_manuais or {}).get(centro.pk)
        if not pesos:
            raise BusinessError(
                f"O centro {centro} usa rateio manual: informe o peso de "
                "cada lote para ratear."
            )
        return pesos
    if criterio == AllocationCriterion.POR_ARROBA_PRODUZIDA:
        raise BusinessError(
            f"O centro {centro} usa rateio por arroba produzida, que depende "
            "do peso de carcaça das vendas (Fase 3). Até lá, escolha outro "
            "critério para este centro."
        )
    raise BusinessError(f"Critério de rateio desconhecido: {criterio}")


def ratear_custos_indiretos(
    *, farm, start, end, cost_center=None, pesos_manuais=None
) -> RateioResultado:
    """Rateia os custos indiretos confirmados da fazenda no período."""
    qs = CostEntry.objects.filter(
        farm=farm,
        status=Status.CONFIRMADA,
        lot__isnull=True,
        date__gte=start,
        date__lte=end,
    )
    if cost_center is not None:
        qs = qs.filter(cost_center=cost_center)

    totais = qs.values("cost_center_id").annotate(total=Sum("amount"))
    resultado = RateioResultado(farm=farm, start=start, end=end)

    from apps.costs.models import CostCenter

    for linha in sorted(totais, key=lambda x: x["cost_center_id"]):
        centro = CostCenter.objects.get(pk=linha["cost_center_id"])
        pesos = _pesos_do_criterio(
            centro.allocation_criterion,
            farm=farm,
            start=start,
            end=end,
            centro=centro,
            pesos_manuais=pesos_manuais,
        )
        cotas = ratear_em_centavos(linha["total"], pesos)
        resultado.centros.append(
            RateioCentro(
                centro=centro,
                criterio=centro.allocation_criterion,
                total=linha["total"],
                cotas=cotas,
                sem_base=linha["total"] if not cotas else Decimal("0"),
            )
        )
    return resultado


def custo_direto_do_lote(lot, *, start=None, end=None) -> Decimal:
    """Soma do que foi lançado direto no lote (compra, frete, vacina...)."""
    qs = CostEntry.objects.filter(lot=lot, status=Status.CONFIRMADA)
    if start is not None:
        qs = qs.filter(date__gte=start)
    if end is not None:
        qs = qs.filter(date__lte=end)
    return qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
