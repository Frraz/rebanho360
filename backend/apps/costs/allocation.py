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
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal, localcontext

from django.db.models import ExpressionWrapper, F, Func, IntegerField, Sum, Value
from django.db.models.functions import Greatest

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

    centavos = int((total / CENT).to_integral_value())
    if all(p == p.to_integral_value() for p in positivos.values()):
        return _ratear_inteiros(centavos, positivos, int(soma))

    with localcontext() as ctx:
        ctx.prec = 60
        exatos = {k: Decimal(centavos) * p / soma for k, p in positivos.items()}
        pisos = {
            k: int(v.to_integral_value(rounding=ROUND_FLOOR)) for k, v in exatos.items()
        }
        resto = centavos - sum(pisos.values())
        # Maior fração primeiro; empate resolvido pela ordem de entrada, que
        # é determinística — duas execuções dão o mesmo resultado.
        posicao = {k: i for i, k in enumerate(positivos)}
        ordem = sorted(
            positivos,
            key=lambda k: (-(exatos[k] - pisos[k]), posicao[k]),
        )
        for chave in ordem[:resto]:
            pisos[chave] += 1
    return {k: Decimal(v) * CENT for k, v in pisos.items()}


def _ratear_inteiros(centavos: int, pesos: dict, soma: int) -> dict:
    """Maior resto com aritmética inteira, quando os pesos são inteiros (cabeça-
    dia e cabeças são). O resultado é o mesmo da conta em `Decimal`: o resto da
    divisão por `soma` ordena as frações (todas têm o mesmo denominador), sem
    arredondar nada e sem o custo do contexto decimal de alta precisão."""
    pisos, restos = {}, {}
    for chave, peso in pesos.items():
        pisos[chave], restos[chave] = divmod(centavos * int(peso), soma)
    sobra = centavos - sum(pisos.values())
    if sobra:
        posicao = {k: i for i, k in enumerate(pesos)}
        # Maior fração primeiro; empate pela ordem de entrada (determinística).
        for chave in sorted(pesos, key=lambda k: (-restos[k], posicao[k]))[:sobra]:
            pisos[chave] += 1
    return {k: Decimal(v) * CENT for k, v in pisos.items()}


def cabecas_dia_por_lote(*, farm, start: datetime.date, end: datetime.date) -> dict:
    """`{lot_id: cabeça-dia}` no período `[start, end]`, a partir do razão.

    O movimento do dia vale a partir do próprio dia: um lote que entrou no
    dia 10 e foi consultado até o dia 10 tem 1 dia de cabeças.

    Cada linha do razão com `quantity` q, na data d ≤ `end`, vale
    `q × (end − max(d, start) + 1)` cabeça-dia — o saldo que ela deixa dura
    até o fim do período. A soma disso por lote é a cabeça-dia, calculada
    pelo banco num único `GROUP BY` (antes eram todas as linhas da fazenda
    trazidas para Python, a cada chamada).
    """
    dias_de_efeito = Func(
        Value(end),
        Greatest(F("date"), Value(start)),
        function="",
        arg_joiner=" - ",
        output_field=IntegerField(),
    )
    linhas = (
        HerdLedgerEntry.objects.filter(farm=farm, date__lte=end)
        .values("lot_id")
        .annotate(
            total=Sum(
                ExpressionWrapper(
                    F("quantity") * (dias_de_efeito + 1), output_field=IntegerField()
                )
            )
        )
        .order_by("lot_id")
    )
    return {
        linha["lot_id"]: Decimal(linha["total"])
        for linha in linhas
        if linha["total"] and linha["total"] > 0
    }


def cabecas_no_fim_por_lote(*, farm, end: datetime.date) -> dict:
    """`{lot_id: cabeças}` na data `end` — critério `POR_CABECA_SIMPLES`."""
    somas = (
        HerdLedgerEntry.objects.filter(farm=farm, date__lte=end)
        .values("lot_id")
        .annotate(total=Sum("quantity"))
        .order_by("lot_id")
    )
    return {
        linha["lot_id"]: Decimal(linha["total"])
        for linha in somas
        if linha["total"] and linha["total"] > 0
    }


class _Acumulado:
    """Soma acumulada por data, consultável em O(log n): quanto havia até `t`."""

    __slots__ = ("datas", "somas")

    def __init__(self, pares):
        self.datas, self.somas, total = [], [], 0
        for data, valor in pares:
            total += valor
            self.datas.append(data)
            self.somas.append(total)

    def ate(self, data):
        """Soma de tudo com data ≤ `data`."""
        i = bisect_right(self.datas, data)
        return self.somas[i - 1] if i else 0

    def antes(self, data):
        """Soma de tudo com data < `data`."""
        i = bisect_left(self.datas, data)
        return self.somas[i - 1] if i else 0


class BaseDeRateio:
    """Tudo que o rateio de uma fazenda precisa, lido **uma vez**.

    Ratear um lote é uma pergunta sobre uma janela `[entrada do lote, hoje]`;
    ratear 300 lotes são 300 janelas sobre o mesmo razão e os mesmos custos.
    Antes, cada janela relia a fazenda inteira (razão e centros de custo) em
    Python, e a tela de lotes fazia isso milhares de vezes. Aqui o razão
    (agrupado por lote e dia) e os custos indiretos (agrupados por centro e
    dia) entram em memória uma vez e viram somas acumuladas; cada janela
    custa uma busca binária por lote.

    O número é o mesmo da fórmula do rateio — `ratear_em_centavos` (maior
    resto) continua sendo quem reparte. Só a leitura mudou.

    `ate`: a maior data que será consultada; evita trazer o futuro.
    """

    def __init__(self, farm, *, ate: datetime.date | None = None):
        self.farm = farm
        self.ate = ate
        razao = HerdLedgerEntry.objects.filter(farm=farm)
        if ate is not None:
            razao = razao.filter(date__lte=ate)

        # Lote → (cabeças acumuladas, cabeças × dia-ordinal acumuladas). Com
        # Q(t) = Σ q e D(t) = Σ q·ord, a cabeça-dia até t é (t+1)·Q − D.
        por_lote_q: dict[int, list] = defaultdict(list)
        por_lote_d: dict[int, list] = defaultdict(list)
        for lot_id, data, q in (
            razao.values_list("lot_id", "date")
            .annotate(q=Sum("quantity"))
            .order_by("lot_id", "date")
        ):
            por_lote_q[lot_id].append((data, q))
            por_lote_d[lot_id].append((data, q * data.toordinal()))
        self._cabecas = {k: _Acumulado(v) for k, v in por_lote_q.items()}
        self._ponderado = {k: _Acumulado(v) for k, v in por_lote_d.items()}
        self._pesos: dict[tuple, dict] = {}
        self._custos = None  # lidos na primeira vez que se ratear

    def _ler_custos(self):
        """Custos indiretos confirmados, por centro e dia. Só o rateio os usa:
        quem quer apenas cabeça-dia (mortalidade, custo por cabeça-dia) não
        paga esta leitura."""
        custos = CostEntry.objects.filter(
            farm=self.farm, status=Status.CONFIRMADA, lot__isnull=True
        )
        if self.ate is not None:
            custos = custos.filter(date__lte=self.ate)
        por_centro: dict[int, list] = defaultdict(list)
        for centro_id, data, total in (
            custos.values_list("cost_center_id", "date")
            .annotate(t=Sum("amount"))
            .order_by("cost_center_id", "date")
        ):
            por_centro[centro_id].append((data, total))
        self._custos = {k: _Acumulado(v) for k, v in por_centro.items()}
        self._pedidos_de_custo = {
            k: _Acumulado((d, 1) for d, _ in v) for k, v in por_centro.items()
        }
        from apps.costs.models import CostCenter

        self._centros = CostCenter.objects.in_bulk(self._custos)

    # -- pesos ---------------------------------------------------------

    def _conferir(self, end):
        if self.ate is not None and end > self.ate:
            raise ValueError(
                f"A base de rateio foi lida até {self.ate}; não responde por {end}."
            )

    def cabecas_dia(self, start, end) -> dict:
        """Mesmo resultado de `cabecas_dia_por_lote`, sem nova consulta."""
        self._conferir(end)
        chave = ("dia", start, end)
        if chave not in self._pesos:
            # F(t) = (t+1)·Q(t) − D(t); a janela é F(fim) − F(início − 1), e
            # com t = início − 1 o fator (t+1) é o próprio ordinal do início.
            fim, inicio = end.toordinal(), start.toordinal()
            pesos = {}
            for lot_id in sorted(self._cabecas):
                q, d = self._cabecas[lot_id], self._ponderado[lot_id]
                total = ((fim + 1) * q.ate(end) - d.ate(end)) - (
                    inicio * q.antes(start) - d.antes(start)
                )
                if total > 0:
                    pesos[lot_id] = Decimal(total)
            self._pesos[chave] = pesos
        return self._pesos[chave]

    def cabecas_no_fim(self, end) -> dict:
        self._conferir(end)
        chave = ("fim", end)
        if chave not in self._pesos:
            self._pesos[chave] = {
                lot_id: Decimal(q.ate(end))
                for lot_id, q in sorted(self._cabecas.items())
                if q.ate(end) > 0
            }
        return self._pesos[chave]

    # -- rateio --------------------------------------------------------

    def ratear(
        self, *, start, end, cost_center=None, pesos_manuais=None
    ) -> "RateioResultado":
        """O que `ratear_custos_indiretos` devolve, para esta janela."""
        self._conferir(end)
        if self._custos is None:
            self._ler_custos()
        resultado = RateioResultado(farm=self.farm, start=start, end=end)
        for centro_id in sorted(self._custos):
            if cost_center is not None and centro_id != cost_center.pk:
                continue
            quantos = self._pedidos_de_custo[centro_id]
            if quantos.ate(end) - quantos.antes(start) <= 0:
                continue  # nenhum custo deste centro na janela
            total = self._custos[centro_id].ate(end) - self._custos[centro_id].antes(
                start
            )
            centro = self._centros[centro_id]
            pesos = self._pesos_do_criterio(
                centro.allocation_criterion,
                start=start,
                end=end,
                centro=centro,
                pesos_manuais=pesos_manuais,
            )
            cotas = ratear_em_centavos(total, pesos)
            resultado.centros.append(
                RateioCentro(
                    centro=centro,
                    criterio=centro.allocation_criterion,
                    total=total,
                    cotas=cotas,
                    sem_base=total if not cotas else Decimal("0"),
                )
            )
        return resultado

    def _pesos_do_criterio(self, criterio, *, start, end, centro, pesos_manuais):
        if criterio == AllocationCriterion.POR_CABECA_DIA:
            return self.cabecas_dia(start, end)
        if criterio == AllocationCriterion.POR_CABECA_SIMPLES:
            return self.cabecas_no_fim(end)
        return _pesos_sem_razao(criterio, centro=centro, pesos_manuais=pesos_manuais)


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


def _pesos_sem_razao(criterio, *, centro, pesos_manuais):
    """Critérios que não dependem do razão: manual, ou ainda não disponíveis."""
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
    *, farm, start, end, cost_center=None, pesos_manuais=None, base=None
) -> RateioResultado:
    """Rateia os custos indiretos confirmados da fazenda no período.

    `base`: uma `BaseDeRateio` já lida (quem ratear muitos lotes da mesma
    fazenda cria uma só). Sem ela, lê o que precisa para esta janela.
    """
    if base is None:
        base = BaseDeRateio(farm, ate=end)
    return base.ratear(
        start=start, end=end, cost_center=cost_center, pesos_manuais=pesos_manuais
    )


def custo_direto_do_lote(lot, *, start=None, end=None) -> Decimal:
    """Soma do que foi lançado direto no lote (compra, frete, vacina...)."""
    qs = CostEntry.objects.filter(lot=lot, status=Status.CONFIRMADA)
    if start is not None:
        qs = qs.filter(date__gte=start)
    if end is not None:
        qs = qs.filter(date__lte=end)
    return qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
