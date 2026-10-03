"""Aba **Rebanho** — onde estão os animais, de onde vieram e para onde foram.

Tudo sai do razão (`HerdLedgerEntry`): saldo é `SUM` com sinal, nunca campo
(regra 1). Mortalidade usa o mesmo serviço do painel inicial.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse

from apps.core.money import kg_to_arroba, safe_div
from apps.herd.models import ENTRY_TYPES, EXIT_TYPES, MovementType
from apps.herd.mortality import taxa_de_mortalidade
from apps.livestock.models import Sex

from . import specs
from .escopo import Escopo
from .specs import Kpi, Painel, Secao, Tabela

ZERO = Decimal("0")

#: Tempo no pasto, em dias — faixas **ordenadas** (uma matiz, clara → escura).
FAIXAS_DE_PERMANENCIA = (
    (0, 30, "até 30"),
    (31, 60, "31–60"),
    (61, 90, "61–90"),
    (91, 120, "91–120"),
    (121, 180, "121–180"),
    (181, None, "mais de 180"),
)

ROTULO_ENTRADA = {
    MovementType.SALDO_INICIAL: "Saldo inicial",
    MovementType.COMPRA: "Compra",
    MovementType.NASCIMENTO: "Nascimento",
}
ROTULO_SAIDA = {
    MovementType.ABATE: "Abate",
    MovementType.VENDA: "Venda em pé",
    MovementType.MORTE: "Morte",
    MovementType.CONSUMO_DOACAO: "Consumo / doação",
}


# --------------------------------------------------------------------------
# Dados (cada função é calculada uma vez por requisição: `Escopo.memo`)
# --------------------------------------------------------------------------


def saldo_por_fazenda(e: Escopo) -> dict[int, int]:
    """Cabeças por fazenda na data de corte."""

    def calcular():
        return {
            farm_id: total
            for farm_id, total in e.razao()
            .values_list("farm_id")
            .annotate(t=Sum("quantity"))
            .order_by()
            if total
        }

    return e.memo("saldo_por_fazenda", calcular)


def total_de_cabecas(e: Escopo) -> int:
    return sum(saldo_por_fazenda(e).values())


@dataclass(frozen=True)
class SerieMensal:
    meses: list
    por_fazenda: dict  # {farm_id: [saldo no fim de cada mês]}
    total: list
    entradas: dict  # {tipo: [cabeças por mês]}
    saidas: dict
    mortes_por_fazenda: dict  # {farm_id: [mortes por mês]}


def serie_mensal(e: Escopo) -> SerieMensal:
    """Saldo no fim de cada mês (abertura + fluxo acumulado) e os fluxos do mês
    por tipo de movimento."""

    def calcular():
        meses = e.meses
        indice = {m: i for i, m in enumerate(meses)}
        fazendas = [f.pk for f in e.fazendas()]
        abertura = {
            farm_id: total or 0
            for farm_id, total in e.razao(ate=e.inicio - datetime.timedelta(days=1))
            .values_list("farm_id")
            .annotate(t=Sum("quantity"))
            .order_by()
        }
        fluxo = defaultdict(lambda: [0] * len(meses))
        base = e.razao().filter(date__gte=e.inicio)
        for mes, farm_id, total in (
            base.annotate(mes=TruncMonth("date"))
            .values_list("mes", "farm_id")
            .annotate(t=Sum("quantity"))
            .order_by()
        ):
            if mes in indice:
                fluxo[farm_id][indice[mes]] += total or 0

        por_fazenda = {}
        for farm_id in set(fazendas) | set(abertura) | set(fluxo):
            acumulado = abertura.get(farm_id, 0)
            serie = []
            for passo in fluxo[farm_id]:
                acumulado += passo
                serie.append(acumulado)
            por_fazenda[farm_id] = serie
        total = [sum(s[i] for s in por_fazenda.values()) for i in range(len(meses))]

        entradas = defaultdict(lambda: [0] * len(meses))
        saidas = defaultdict(lambda: [0] * len(meses))
        mortes = defaultdict(lambda: [0] * len(meses))
        for mes, tipo, farm_id, soma in (
            base.filter(movement__type__in=[*ENTRY_TYPES, *EXIT_TYPES])
            .annotate(mes=TruncMonth("date"))
            .values_list("mes", "movement__type", "farm_id")
            .annotate(t=Sum("quantity"))
            .order_by()
        ):
            if mes not in indice:
                continue
            i = indice[mes]
            if tipo in ENTRY_TYPES:
                entradas[tipo][i] += soma or 0
            else:
                saidas[tipo][i] += -(soma or 0)
                if tipo == MovementType.MORTE:
                    mortes[farm_id][i] += -(soma or 0)
        return SerieMensal(
            meses, por_fazenda, total, dict(entradas), dict(saidas), dict(mortes)
        )

    return e.memo("serie_mensal", calcular)


def composicao(e: Escopo) -> list[tuple]:
    """`[(farm_id, categoria, ordem, sexo, cabeças)]`, só saldo positivo."""

    def calcular():
        return [
            (farm_id, nome, ordem, sexo, total)
            for farm_id, nome, ordem, sexo, total in e.razao()
            .values_list(
                "farm_id", "category__name", "category__display_order", "category__sex"
            )
            .annotate(t=Sum("quantity"))
            .order_by()
            if total and total > 0
        ]

    return e.memo("composicao", calcular)


@dataclass(frozen=True)
class LoteComSaldo:
    lote: object
    cabecas: int
    dias: int


def lotes_com_saldo(e: Escopo) -> list[LoteComSaldo]:
    def calcular():
        saldos = {
            lot_id: total
            for lot_id, total in e.razao()
            .values_list("lot_id")
            .annotate(t=Sum("quantity"))
            .order_by()
            if total and total > 0
        }
        lotes = e.lotes().filter(pk__in=saldos).select_related("farm", "breed")
        return sorted(
            (
                LoteComSaldo(lt, saldos[lt.pk], max((e.fim - lt.entry_date).days, 0))
                for lt in lotes
            ),
            key=lambda x: (x.lote.farm.name, x.lote.code),
        )

    return e.memo("lotes_com_saldo", calcular)


def ultimo_peso_por_lote(e: Escopo, lote_ids) -> dict[int, tuple]:
    """`{lot_id: (peso médio kg, data)}` da última pesagem até o corte."""

    def calcular():
        saida = {}
        pesagens = (
            e.pesagens()
            .filter(lot_id__in=list(lote_ids), date__lte=e.fim)
            .order_by("lot_id", "-date", "-id")
            .distinct("lot_id")
        )
        for p in pesagens:
            medio = p.average_weight_kg
            if medio is not None:
                saida[p.lot_id] = (medio, p.date)
        return saida

    return e.memo(f"ultimo_peso:{sorted(lote_ids)}", calcular)


@dataclass(frozen=True)
class Mortalidade:
    mortes: int
    taxa: Decimal | None  # % na safra, consolidada
    por_fazenda: dict  # {farm: TaxaDeMortalidade}


def mortalidade(e: Escopo) -> Mortalidade:
    """Consolidada = mortes ÷ soma dos saldos médios das fazendas — a média
    ponderada, não a média das taxas (uma fazenda pequena não pesa igual)."""

    def calcular():
        por_fazenda = {
            f: taxa_de_mortalidade(farm=f, start=e.inicio, end=e.fim)
            for f in e.fazendas()
        }
        mortes = sum(t.mortes for t in por_fazenda.values())
        saldo_medio = sum(
            (t.saldo_medio for t in por_fazenda.values() if t.saldo_medio), ZERO
        )
        return Mortalidade(
            mortes, safe_div(Decimal(mortes) * 100, saldo_medio), por_fazenda
        )

    return e.memo("mortalidade", calcular)


def lotacao_por_fazenda(e: Escopo) -> dict:
    """`{farm: cabeças/ha}` — só fazenda com área de pasto cadastrada: sem a
    área não há lotação, e "—" é mais honesto que 0."""
    saldos = saldo_por_fazenda(e)
    saida = {}
    for f in e.fazendas():
        area = f.pasture_area_ha
        saida[f] = (
            safe_div(Decimal(saldos.get(f.pk, 0)), area) if area else None,
            area,
            saldos.get(f.pk, 0),
        )
    return saida


def lotacao_consolidada(e: Escopo) -> Decimal | None:
    """Cabeças das fazendas **com área** ÷ a área delas."""
    area = ZERO
    cabecas = 0
    for _, (taxa, a, cb) in lotacao_por_fazenda(e).items():
        if a:
            area += a
            cabecas += cb
    return safe_div(Decimal(cabecas), area)


def permanencia_media(e: Escopo) -> Decimal | None:
    """Dias médios dos animais no lote, ponderados pelas cabeças."""
    lotes = lotes_com_saldo(e)
    cabecas = sum(lt.cabecas for lt in lotes)
    return safe_div(Decimal(sum(lt.dias * lt.cabecas for lt in lotes)), cabecas)


def peso_medio_do_rebanho(e: Escopo) -> tuple[Decimal | None, int, int]:
    """`(kg/cabeça, lotes pesados, lotes com animais)` — média das últimas
    pesagens ponderada pelas cabeças de hoje. Lote nunca pesado não entra, e a
    cobertura aparece ao lado: média de 3 lotes em 40 não é o rebanho."""
    lotes = lotes_com_saldo(e)
    pesos = ultimo_peso_por_lote(e, [lt.lote.pk for lt in lotes])
    ponderado = ZERO
    cabecas = 0
    for lt in lotes:
        if lt.lote.pk in pesos:
            ponderado += pesos[lt.lote.pk][0] * lt.cabecas
            cabecas += lt.cabecas
    return safe_div(ponderado, cabecas), len(pesos), len(lotes)


# --------------------------------------------------------------------------
# KPIs (a visão geral reaproveita estes)
# --------------------------------------------------------------------------


def kpi_cabecas(e: Escopo) -> Kpi:
    serie = serie_mensal(e)
    atual = total_de_cabecas(e)
    anterior = total_de_cabecas(e.anterior) if e.anterior else None
    return Kpi(
        "Rebanho atual",
        specs.formatar(atual),
        "cabeças",
        nota=f"{len(saldo_por_fazenda(e))} fazenda(s) com animais",
        delta=specs.variacao(atual, anterior),
        spark=specs.sparkline(serie.total),
        url=reverse("herd:posicao"),
        ajuda="Saldo do razão do rebanho na data de corte, somando o escopo escolhido.",
        destaque=True,
    )


def kpi_mortalidade(e: Escopo) -> Kpi:
    m = mortalidade(e)
    anterior = mortalidade(e.anterior).taxa if e.anterior else None
    return Kpi(
        "Mortalidade na safra",
        specs.formatar(m.taxa, "pct"),
        nota=f"{m.mortes} morte(s)",
        delta=specs.variacao_pp(m.taxa, anterior, bom_quando="baixa"),
        url=reverse("herd:movimento_lista"),
        ajuda=(
            "Mortes ÷ saldo médio do período × 100, por fazenda e depois "
            "ponderado pelo saldo médio — o mesmo cálculo do painel inicial."
        ),
    )


def kpis_do_rebanho(e: Escopo) -> list[Kpi]:
    serie = serie_mensal(e)
    entradas = sum(
        sum(v) for k, v in serie.entradas.items() if k != MovementType.SALDO_INICIAL
    )
    saidas = sum(sum(v) for v in serie.saidas.values())
    peso, pesados, com_animais = peso_medio_do_rebanho(e)
    lotes = lotes_com_saldo(e)
    arrobas = None
    if peso is not None:
        cabecas_pesadas = sum(
            lt.cabecas
            for lt in lotes
            if lt.lote.pk in ultimo_peso_por_lote(e, [x.lote.pk for x in lotes])
        )
        arrobas = kg_to_arroba(peso * cabecas_pesadas)
    lotacao = lotacao_consolidada(e)
    anterior_lot = lotacao_consolidada(e.anterior) if e.anterior else None
    kpis = [
        kpi_cabecas(e),
        Kpi(
            "Lotes com animais",
            specs.formatar(len(lotes)),
            nota=f"{pesados} com pesagem registrada",
            url=reverse("livestock:lote_lista"),
            ajuda="Lotes com saldo maior que zero na data de corte.",
        ),
        Kpi(
            "Peso médio",
            specs.formatar(peso, "kg"),
            nota=f"{pesados} de {com_animais} lotes pesados" if com_animais else "",
            ajuda=(
                "Última pesagem de cada lote, ponderada pelas cabeças de hoje. "
                "Lote nunca pesado fica fora da média."
            ),
        ),
        Kpi(
            "@ vivas estimadas",
            specs.formatar(arrobas, "arroba"),
            nota="só dos lotes pesados",
            ajuda="Peso médio × cabeças pesadas ÷ 15. Arroba de peso vivo: serve de conferência, não de preço.",
        ),
        Kpi(
            "Lotação",
            specs.formatar(lotacao, "ha"),
            nota="fazendas com área de pasto",
            delta=specs.variacao(lotacao, anterior_lot, bom_quando=None),
            ajuda="Cabeças ÷ área de pasto cadastrada, só das fazendas que têm a área informada.",
        ),
        Kpi(
            "Entradas na safra",
            specs.formatar(entradas),
            "cabeças",
            nota="compra e nascimento",
            url=reverse("herd:movimento_lista"),
        ),
        Kpi(
            "Saídas na safra",
            specs.formatar(saidas),
            "cabeças",
            nota="abate, venda, morte e consumo",
            url=reverse("herd:movimento_lista"),
        ),
        kpi_mortalidade(e),
        Kpi(
            "Permanência média",
            specs.formatar(permanencia_media(e), "dias"),
            nota="no lote atual, ponderada",
            ajuda="Dias desde a entrada do lote até a data de corte, ponderados pelas cabeças.",
        ),
    ]
    return kpis


# --------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------


def _nome_da_fazenda(e: Escopo) -> dict[int, str]:
    return {f.pk: f.name for f in e.fazendas()}


def _cor_fazenda(e: Escopo, farm_id: int) -> int:
    return e.cor_da_fazenda(farm_id)


def grafico_saldo_por_fazenda(e: Escopo) -> specs.Grafico:
    serie = serie_mensal(e)
    nomes = _nome_da_fazenda(e)
    x = [specs.rotulo_do_mes(m) for m in serie.meses]
    series = [
        specs.serie(
            nomes.get(farm_id, f"Fazenda {farm_id}"),
            dados,
            tipo="area",
            pilha="rebanho",
            cor=_cor_fazenda(e, farm_id),
        )
        for farm_id, dados in sorted(
            serie.por_fazenda.items(), key=lambda kv: nomes.get(kv[0], "")
        )
        if any(dados)
    ]
    return specs.cartesiano(
        "saldo-fazenda",
        "Rebanho no fim de cada mês, por fazenda",
        x,
        series,
        formato="cb",
        titulo_y="Cabeças",
        nota="Saldo do razão acumulado até o último dia de cada mês.",
        largura="dois-tercos",
        url=reverse("herd:posicao"),
    )


def grafico_fluxo_por_tipo(e: Escopo) -> specs.Grafico:
    serie = serie_mensal(e)
    x = [specs.rotulo_do_mes(m) for m in serie.meses]
    ordem_entrada = [t for t in ROTULO_ENTRADA if t in serie.entradas]
    ordem_saida = [t for t in ROTULO_SAIDA if t in serie.saidas]
    cores = {
        MovementType.SALDO_INICIAL: 6,
        MovementType.COMPRA: specs.COR_COMPRAS,
        MovementType.NASCIMENTO: specs.COR_VENDAS,
        MovementType.ABATE: specs.COR_CUSTOS,
        MovementType.VENDA: specs.COR_ALERTA,
        MovementType.MORTE: 7,
        MovementType.CONSUMO_DOACAO: 4,
    }
    series = [
        specs.serie(
            ROTULO_ENTRADA[t], serie.entradas[t], pilha="entradas", cor=cores[t]
        )
        for t in ordem_entrada
    ] + [
        specs.serie(
            ROTULO_SAIDA[t],
            [-v for v in serie.saidas[t]],
            pilha="saidas",
            cor=cores[t],
        )
        for t in ordem_saida
    ]
    return specs.cartesiano(
        "fluxo-tipo",
        "Entradas e saídas por mês",
        x,
        series,
        formato="cb",
        titulo_y="Cabeças",
        nota="Entradas para cima, saídas para baixo. Transferência entre fazendas não aparece: soma zero.",
        largura="terco",
        url=reverse("herd:movimento_lista"),
    )


def grafico_calor_fazenda_categoria(e: Escopo) -> specs.Grafico:
    linhas = composicao(e)
    nomes = _nome_da_fazenda(e)
    fazendas = sorted({nomes.get(lt[0], str(lt[0])) for lt in linhas})
    categorias = [
        c
        for c, _ in sorted(
            {(lt[1], lt[2]) for lt in linhas}, key=lambda t: (t[1], t[0])
        )
    ]
    valores = defaultdict(int)
    for farm_id, nome, _, _, total in linhas:
        valores[
            (categorias.index(nome), fazendas.index(nomes.get(farm_id, str(farm_id))))
        ] += total
    return specs.calor(
        "calor-fazenda-categoria",
        "Onde está cada categoria",
        categorias,
        fazendas,
        dict(valores),
        formato="cb",
        titulo_x="Categoria",
        titulo_y="Fazenda",
        largura="metade",
        url=reverse("herd:posicao"),
    )


def grafico_treemap(e: Escopo) -> specs.Grafico:
    nomes = _nome_da_fazenda(e)
    por_fazenda = defaultdict(lambda: defaultdict(int))
    for farm_id, categoria, _, _, total in composicao(e):
        por_fazenda[nomes.get(farm_id, str(farm_id))][categoria] += total
    nos = [
        {
            "nome": f,
            "valor": sum(cats.values()),
            "filhos": [
                {"nome": c, "valor": v}
                for c, v in sorted(cats.items(), key=lambda kv: -kv[1])
            ],
        }
        for f, cats in sorted(por_fazenda.items(), key=lambda kv: -sum(kv[1].values()))
    ]
    return specs.treemap(
        "treemap-rebanho",
        "Fazenda → categoria",
        nos,
        formato="cb",
        nota="A área é proporcional às cabeças.",
        largura="metade",
        url=reverse("herd:posicao"),
    )


def grafico_por_sexo(e: Escopo) -> specs.Grafico:
    soma = defaultdict(int)
    for _, _, _, sexo, total in composicao(e):
        soma[sexo] += total
    rotulos = dict(Sex.choices)
    cores = {Sex.MACHO: 0, Sex.FEMEA: 4, Sex.INDEFINIDO: "neutro"}
    itens = [
        (rotulos.get(s, s), soma[s], cores.get(s, "neutro"))
        for s in (Sex.MACHO, Sex.FEMEA, Sex.INDEFINIDO)
        if soma.get(s)
    ]
    return specs.rosca(
        "rebanho-sexo",
        "Machos e fêmeas",
        itens,
        formato="cb",
        centro_rotulo="cabeças",
        largura="terco",
    )


def grafico_categorias(e: Escopo) -> specs.Grafico:
    soma = defaultdict(int)
    for _, nome, _, _, total in composicao(e):
        soma[nome] += total
    return specs.ranking(
        "rebanho-categorias",
        "Por categoria",
        list(soma.items()),
        formato="cb",
        nome_serie="Cabeças",
        limite=12,
        largura="terco",
        url=reverse("herd:posicao"),
    )


def grafico_permanencia(e: Escopo) -> specs.Grafico:
    lotes = lotes_com_saldo(e)
    contagem = [0] * len(FAIXAS_DE_PERMANENCIA)
    for lt in lotes:
        for i, (de, ate, _) in enumerate(FAIXAS_DE_PERMANENCIA):
            if lt.dias >= de and (ate is None or lt.dias <= ate):
                contagem[i] += lt.cabecas
                break
    return specs.cartesiano(
        "permanencia",
        "Tempo no pasto",
        [r for _, _, r in FAIXAS_DE_PERMANENCIA],
        [specs.serie("Cabeças", contagem, cor="marca", rotulo=True, ordinal=True)],
        formato="cb",
        titulo_x="Dias desde a entrada do lote",
        titulo_y="Cabeças",
        nota="Cada lote entra pela data de entrada; a barra soma as cabeças dele.",
        largura="terco",
    )


def grafico_sankey(e: Escopo) -> specs.Grafico:
    """Conservação visível: abertura + entradas = saídas + saldo final."""
    abertura = sum(
        (total or 0)
        for total in e.razao(ate=e.inicio - datetime.timedelta(days=1))
        .values_list("farm_id")
        .annotate(t=Sum("quantity"))
        .order_by()
        .values_list("t", flat=True)
    )
    serie = serie_mensal(e)
    entradas = {t: sum(v) for t, v in serie.entradas.items()}
    saidas = {t: sum(v) for t, v in serie.saidas.items()}
    final = total_de_cabecas(e)

    nos = [("Rebanho", "marca")]
    ligacoes = []
    if abertura > 0:
        nos.append(("Saldo de abertura", "neutro"))
        ligacoes.append(("Saldo de abertura", "Rebanho", abertura))
    for t, v in entradas.items():
        if v:
            rotulo = ROTULO_ENTRADA[t]
            nos.append((f"{rotulo}", specs.COR_VENDAS))
            ligacoes.append((rotulo, "Rebanho", v))
    for t, v in saidas.items():
        if v:
            rotulo = ROTULO_SAIDA[t]
            nos.append((f"{rotulo} ", specs.COR_CUSTOS))
            ligacoes.append(("Rebanho", f"{rotulo} ", v))
    if final > 0:
        nos.append((f"Rebanho em {e.fim:%d/%m/%Y}", "neutro"))
        ligacoes.append(("Rebanho", f"Rebanho em {e.fim:%d/%m/%Y}", final))
    return specs.sankey(
        "sankey-rebanho",
        "De onde vieram e para onde foram os animais na safra",
        nos,
        ligacoes,
        formato="cb",
        nota="Abertura + entradas = saídas + saldo final. O que sobra na saída é o rebanho de hoje.",
        url=reverse("herd:movimento_lista"),
    )


def grafico_mortes_por_mes(e: Escopo) -> specs.Grafico:
    serie = serie_mensal(e)
    nomes = _nome_da_fazenda(e)
    x = [specs.rotulo_do_mes(m) for m in serie.meses]
    series = [
        specs.serie(
            nomes.get(fid, str(fid)), dados, pilha="mortes", cor=_cor_fazenda(e, fid)
        )
        for fid, dados in sorted(
            serie.mortes_por_fazenda.items(), key=lambda kv: nomes.get(kv[0], "")
        )
        if any(dados)
    ]
    return specs.cartesiano(
        "mortes-mes",
        "Mortes por mês",
        x,
        series,
        formato="cb",
        titulo_y="Cabeças",
        largura="terco",
        url=reverse("herd:movimento_lista"),
    )


def grafico_mortalidade_por_fazenda(e: Escopo) -> specs.Grafico:
    m = mortalidade(e)
    itens = [(f.name, t.taxa) for f, t in m.por_fazenda.items() if t.taxa is not None]
    g = specs.ranking(
        "mortalidade-fazenda",
        "Mortalidade na safra, por fazenda",
        itens,
        formato="pct2",
        nome_serie="Mortalidade",
        mostrar_participacao=False,
        aditivo=False,
        largura="terco",
        nota="Mortes ÷ saldo médio da fazenda. O sistema não julga o que é "
        '"acima do normal": a leitura é sua.',
    )
    return g


def grafico_lotacao(e: Escopo) -> specs.Grafico:
    itens = [
        (f.name, taxa)
        for f, (taxa, area, cb) in lotacao_por_fazenda(e).items()
        if taxa is not None
    ]
    return specs.ranking(
        "lotacao-fazenda",
        "Lotação por fazenda",
        itens,
        formato="num2",
        nome_serie="Cabeças por hectare",
        mostrar_participacao=False,
        aditivo=False,
        largura="terco",
        nota="Cabeças ÷ área de pasto cadastrada. Fazenda sem área informada não aparece.",
    )


def tabela_de_fazendas(e: Escopo) -> Tabela:
    saldos = saldo_por_fazenda(e)
    lotes = lotes_com_saldo(e)
    m = mortalidade(e)
    colunas = [
        "Fazenda",
        "Cabeças",
        "Lotes",
        "Área de pasto",
        "Lotação",
        "Mortes",
        "Mortalidade",
    ]
    linhas = []
    valores = []
    for f in e.fazendas():
        taxa_lot, area, cb = lotacao_por_fazenda(e)[f]
        mort = m.por_fazenda[f]
        linhas.append(
            [
                f.name,
                specs.formatar(saldos.get(f.pk, 0)),
                specs.formatar(sum(1 for lt in lotes if lt.lote.farm_id == f.pk)),
                specs.formatar(area, "num1") + " ha" if area else specs.TRAVESSAO,
                specs.formatar(taxa_lot, "num2"),
                specs.formatar(mort.mortes),
                specs.formatar(mort.taxa, "pct"),
            ]
        )
        valores.append(saldos.get(f.pk, 0))
    t = Tabela(
        colunas, linhas, numericas=[1, 2, 3, 4, 5, 6], titulo="Posição por fazenda"
    )
    t.barra(1, valores)
    t.vazio = "Nenhuma fazenda com animais no recorte."
    return t


# --------------------------------------------------------------------------
# Aba
# --------------------------------------------------------------------------


def montar(e: Escopo) -> Painel:
    painel = Painel(kpis=kpis_do_rebanho(e), kpis_titulo="Posição do rebanho")
    if not saldo_por_fazenda(e) and not serie_mensal(e).entradas:
        painel.vazio = (
            "Ainda não há animais no razão do rebanho para este recorte. "
            "Lance uma compra ou um saldo inicial para começar."
        )
    painel.secoes = [
        Secao(
            "Evolução",
            [grafico_saldo_por_fazenda(e), grafico_fluxo_por_tipo(e)],
            "Como o rebanho cresceu e o que o moveu.",
        ),
        Secao(
            "Composição",
            [
                grafico_calor_fazenda_categoria(e),
                grafico_treemap(e),
                grafico_por_sexo(e),
                grafico_categorias(e),
                grafico_permanencia(e),
            ],
            "O que há em cada fazenda hoje.",
        ),
        Secao("Fluxo de animais", [grafico_sankey(e)]),
        Secao(
            "Sanidade e lotação",
            [
                grafico_mortes_por_mes(e),
                grafico_mortalidade_por_fazenda(e),
                grafico_lotacao(e),
            ],
            tabelas=[tabela_de_fazendas(e)],
        ),
    ]
    _, pesados, com_animais = peso_medio_do_rebanho(e)
    if com_animais and pesados < com_animais:
        painel.avisos.append(
            f"{com_animais - pesados} lote(s) com animais nunca foram pesados e ficam fora do peso médio."
        )
    sem_area = [f.name for f in e.fazendas() if not f.pasture_area_ha]
    if sem_area:
        painel.avisos.append(
            "Sem área de pasto cadastrada, e portanto sem lotação: "
            + ", ".join(sem_area)
            + "."
        )
    return painel
