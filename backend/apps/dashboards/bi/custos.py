"""Aba **Custos** — para onde foi o dinheiro de operar.

São os custos **avulsos** da safra (fora o que a compra gera, que já está no
investimento em compras): o mesmo critério do painel inicial. Cabeça-dia vem de
`cabecas_dia_por_lote`, o cálculo que o rateio usa.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse

from apps.core.money import safe_div

from . import rebanho, specs
from .escopo import Escopo
from .specs import Kpi, Painel, Secao, Tabela

ZERO = Decimal("0")
CENTROS_NO_CALOR = 8

#: Um centro com mais disto do custo da safra merece atenção (pendência #48).
CENTRO_DOMINANTE_PERCENTUAL = Decimal("35")


def _por_mes(escopo: Escopo, campo: str) -> dict:
    """`{(mes, rótulo): total}` — `campo` é o nome relacionado a agrupar."""
    saida = defaultdict(lambda: ZERO)
    for mes, rotulo, total in (
        escopo.custos()
        .annotate(mes=TruncMonth("date"))
        .values_list("mes", campo)
        .annotate(t=Sum("amount"))
        .order_by()
    ):
        saida[(mes, rotulo)] += total
    return saida


def total(escopo: Escopo) -> Decimal:
    return escopo.memo(
        "custos_total",
        lambda: escopo.custos().aggregate(t=Sum("amount"))["t"] or ZERO,
    )


def totais_por_mes(escopo: Escopo) -> list[Decimal]:
    por = escopo.memo("custos_por_mes", lambda: _por_mes(escopo, "farm_id"))
    return [
        sum((v for (m, _), v in por.items() if m == mes), ZERO) for mes in escopo.meses
    ]


def por_centro(e: Escopo) -> list[tuple[str, Decimal, int]]:
    def calcular():
        return [
            (nome, soma, n)
            for nome, soma, n in e.custos()
            .values_list("cost_center__name")
            .annotate(t=Sum("amount"), n=Count("id"))
            .order_by("-t")
        ]

    return e.memo("custos_por_centro", calcular)


def por_classe(e: Escopo) -> list[tuple[str, Decimal]]:
    def calcular():
        return [
            (nome, soma)
            for nome, soma in e.custos()
            .values_list("cost_class__name")
            .annotate(t=Sum("amount"))
            .order_by("-t")
        ]

    return e.memo("custos_por_classe", calcular)


def por_fazenda(e: Escopo) -> list[tuple]:
    def calcular():
        return [
            (farm_id, nome, soma)
            for farm_id, nome, soma in e.custos()
            .values_list("farm_id", "farm__name")
            .annotate(t=Sum("amount"))
            .order_by("-t")
        ]

    return e.memo("custos_por_fazenda", calcular)


def cabecas_dia_por_mes(e: Escopo) -> list[Decimal]:
    """Cabeça-dia de cada mês, somada nas fazendas do recorte — a base do custo
    por cabeça/dia. Um mês parcial (o corrente) conta só até a data de corte."""

    def calcular():
        saida = []
        fazendas = e.fazendas()
        for mes in e.meses:
            inicio = max(mes, e.inicio)
            fim = min(
                (mes + datetime.timedelta(days=32)).replace(day=1)
                - datetime.timedelta(days=1),
                e.fim,
            )
            soma = ZERO
            for f in fazendas:
                soma += sum(e.base_do_razao(f).cabecas_dia(inicio, fim).values(), ZERO)
            saida.append(soma)
        return saida

    return e.memo("cabecas_dia_por_mes", calcular)


def custo_por_cabeca_dia(e: Escopo) -> Decimal | None:
    return safe_div(total(e), sum(cabecas_dia_por_mes(e), ZERO) or None)


def custo_por_cabeca(e: Escopo) -> Decimal | None:
    """Custos da safra ÷ rebanho atual — a definição do painel inicial."""
    return safe_div(total(e), rebanho.total_de_cabecas(e) or None)


def custo_por_hectare(e: Escopo) -> Decimal | None:
    """Só das fazendas com área de pasto: custo e área da mesma base."""
    area = ZERO
    custo = ZERO
    por = {farm_id: soma for farm_id, _, soma in por_fazenda(e)}
    for f in e.fazendas():
        if f.pasture_area_ha:
            area += f.pasture_area_ha
            custo += por.get(f.pk, ZERO)
    return safe_div(custo, area)


def participacao_do_maior_centro(e: Escopo):
    centros = por_centro(e)
    if not centros:
        return None, None
    nome, valor, _ = centros[0]
    return nome, specs.pct(valor, total(e))


# --------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------


def kpis(e: Escopo) -> list[Kpi]:
    atual = total(e)
    anterior = total(e.anterior) if e.anterior else None
    nome, parte = participacao_do_maior_centro(e)
    classes = dict(por_classe(e))
    custeio = classes.get("CUSTEIO", ZERO)
    por_cdia = custo_por_cabeca_dia(e)
    anterior_cdia = custo_por_cabeca_dia(e.anterior) if e.anterior else None
    lancamentos = sum(n for _, _, n in por_centro(e))
    dominante = parte is not None and parte > CENTRO_DOMINANTE_PERCENTUAL
    return [
        Kpi(
            "Custos da safra",
            specs.brl_curto(atual) if lancamentos else specs.TRAVESSAO,
            nota="fora a compra de animais",
            delta=specs.variacao(
                atual if lancamentos else None, anterior, bom_quando="baixa"
            ),
            spark=specs.sparkline(totais_por_mes(e)),
            url=reverse("costs:lista"),
            ajuda="Lançamentos confirmados da safra, sem os custos que a compra gera (já estão no investimento).",
            destaque=True,
        ),
        Kpi(
            "Custo por cabeça",
            specs.formatar(custo_por_cabeca(e), "brl"),
            nota="custos ÷ rebanho atual",
            delta=specs.variacao(
                custo_por_cabeca(e),
                custo_por_cabeca(e.anterior) if e.anterior else None,
                bom_quando="baixa",
            ),
        ),
        Kpi(
            "Custo por cabeça/dia",
            specs.formatar(por_cdia, "brl"),
            nota="custos ÷ cabeças-dia no período",
            delta=specs.variacao(por_cdia, anterior_cdia, bom_quando="baixa"),
            ajuda=(
                "Custos ÷ soma das cabeças-dia (cabeças × dias no pasto, do razão). "
                "É o que tira o efeito do tamanho do rebanho: dá para comparar meses e safras."
            ),
        ),
        Kpi(
            "Maior centro de custo",
            nome or specs.TRAVESSAO,
            nota=(
                f"{specs.formatar(parte, 'pct')} do total" if parte is not None else ""
            ),
            estado="atencao" if dominante else "",
            estado_texto="Concentra o custo" if dominante else "",
        ),
        Kpi(
            "Custeio",
            specs.formatar(specs.pct(custeio, atual), "pct"),
            nota=f"{specs.brl_curto(custeio)} · o resto é investimento",
            ajuda="Custeio é o que se gasta para operar; investimento é o que se imobiliza.",
        ),
        Kpi(
            "Custo por hectare",
            specs.formatar(custo_por_hectare(e), "brl"),
            nota="fazendas com área de pasto",
        ),
        Kpi(
            "Lançamentos",
            specs.formatar(lancamentos),
            nota="confirmados na safra",
            url=reverse("costs:lista"),
        ),
    ]


# --------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------


def grafico_por_mes_e_classe(e: Escopo) -> specs.Grafico:
    por = _por_mes(e, "cost_class__name")
    classes = [n for n, _ in por_classe(e)]
    cores = {"CUSTEIO": specs.COR_CUSTOS, "INVESTIMENTO": specs.COR_COMPRAS}
    return specs.cartesiano(
        "custos-mes-classe",
        "Custos por mês: custeio e investimento",
        [specs.rotulo_do_mes(m) for m in e.meses],
        [
            specs.serie(
                nome.capitalize(),
                [por.get((m, nome), ZERO) for m in e.meses],
                pilha="custos",
                cor=cores.get(nome, 4),
            )
            for nome in classes
        ],
        formato="brl",
        titulo_y="R$",
        largura="dois-tercos",
        url=reverse("costs:lista"),
    )


def grafico_por_classe(e: Escopo) -> specs.Grafico:
    cores = {"CUSTEIO": specs.COR_CUSTOS, "INVESTIMENTO": specs.COR_COMPRAS}
    return specs.rosca(
        "custos-classe",
        "Custeio × investimento",
        [(n.capitalize(), v, cores.get(n)) for n, v in por_classe(e)],
        formato="brl",
        centro_rotulo="custos",
        largura="terco",
    )


def grafico_treemap(e: Escopo) -> specs.Grafico:
    soma = defaultdict(lambda: defaultdict(lambda: ZERO))
    for centro, classe, valor in (
        e.custos()
        .values_list("cost_center__name", "cost_class__name")
        .annotate(t=Sum("amount"))
        .order_by()
    ):
        soma[centro][classe.capitalize()] += valor
    nos = [
        {
            "nome": centro,
            "valor": sum(classes.values(), ZERO),
            "filhos": [{"nome": c, "valor": v} for c, v in classes.items()],
        }
        for centro, classes in sorted(
            soma.items(), key=lambda kv: -sum(kv[1].values(), ZERO)
        )
    ]
    return specs.treemap(
        "custos-treemap",
        "Centro de custo → classe",
        nos,
        formato="brl",
        nota="A área é proporcional ao valor.",
        largura="metade",
    )


def grafico_pareto_centros(e: Escopo) -> specs.Grafico:
    return specs.ranking(
        "custos-centros",
        "Centros de custo, do maior para o menor",
        [(n, v) for n, v, _ in por_centro(e)],
        formato="brl",
        nome_serie="Custo",
        limite=12,
        largura="metade",
        nota="A tabela traz a participação acumulada: quantos centros explicam 80% do custo.",
    )


def grafico_calor_centro_mes(e: Escopo) -> specs.Grafico:
    por = _por_mes(e, "cost_center__name")
    centros = [n for n, _, _ in por_centro(e)][:CENTROS_NO_CALOR]
    meses = e.meses
    valores = {
        (xi, yi): por[(m, c)]
        for yi, c in enumerate(centros)
        for xi, m in enumerate(meses)
        if (m, c) in por
    }
    return specs.calor(
        "custos-calor",
        "Quando cada centro pesou",
        [specs.rotulo_do_mes(m) for m in meses],
        centros,
        valores,
        formato="brl",
        titulo_x="Mês",
        titulo_y="Centro de custo",
        nota=f"Os {CENTROS_NO_CALOR} maiores centros. Mais escuro = mais caro no mês.",
        largura="cheia",
    )


def grafico_por_fazenda(e: Escopo) -> specs.Grafico:
    return specs.ranking(
        "custos-fazenda",
        "Custos por fazenda",
        [(nome, v) for _, nome, v in por_fazenda(e)],
        formato="brl",
        nome_serie="Custo",
        largura="terco",
    )


def grafico_custo_por_cabeca_fazenda(e: Escopo) -> specs.Grafico:
    saldos = rebanho.saldo_por_fazenda(e)
    itens = []
    for farm_id, nome, valor in por_fazenda(e):
        c = safe_div(valor, saldos.get(farm_id) or None)
        if c is not None:
            itens.append((nome, c))
    return specs.ranking(
        "custos-cabeca-fazenda",
        "Custo por cabeça, por fazenda",
        itens,
        formato="brl",
        nome_serie="Custo/cabeça",
        mostrar_participacao=False,
        largura="terco",
        nota="Custos da fazenda ÷ cabeças dela hoje. Fazenda sem animais não aparece.",
    )


def grafico_cabeca_dia_mensal(e: Escopo) -> specs.Grafico:
    custos = totais_por_mes(e)
    cabecas_dia = cabecas_dia_por_mes(e)
    return specs.cartesiano(
        "custos-cabeca-dia",
        "Custo por cabeça/dia, mês a mês",
        [specs.rotulo_do_mes(m) for m in e.meses],
        [
            specs.serie(
                "Custo por cabeça/dia",
                [
                    safe_div(c, cd or None)
                    for c, cd in zip(custos, cabecas_dia, strict=True)
                ],
                tipo="line",
                cor="marca",
            )
        ],
        formato="brl",
        titulo_y="R$ por cabeça por dia",
        nota="Custo do mês ÷ cabeças-dia do mês: tira o efeito do tamanho do rebanho.",
        largura="terco",
    )


def tabela_maiores_lancamentos(e: Escopo) -> Tabela:
    maiores = list(
        e.custos()
        .select_related("farm", "cost_center", "cost_class")
        .order_by("-amount")[:10]
    )
    linhas, links = [], []
    for c in maiores:
        linhas.append(
            [
                f"{c.date:%d/%m/%Y}",
                c.description,
                c.cost_center.name,
                c.cost_class.name.capitalize(),
                c.farm.name,
                specs.formatar(c.amount, "brl"),
            ]
        )
        links.append(reverse("costs:detalhe", args=[c.pk]))
    t = Tabela(
        ["Data", "Descrição", "Centro", "Classe", "Fazenda", "Valor"],
        linhas,
        numericas=[5],
        titulo="Dez maiores lançamentos",
        links=links,
        vazio="Nenhum custo lançado na safra.",
    )
    t.barra(5, [c.amount for c in maiores])
    return t


# --------------------------------------------------------------------------
# Aba
# --------------------------------------------------------------------------


def montar(e: Escopo) -> Painel:
    painel = Painel(kpis=kpis(e), kpis_titulo="Custos da safra")
    if not por_centro(e):
        painel.vazio = "Nenhum custo confirmado na safra e no recorte escolhidos."
    painel.secoes = [
        Secao("Ritmo", [grafico_por_mes_e_classe(e), grafico_por_classe(e)]),
        Secao(
            "Onde está o dinheiro",
            [
                grafico_treemap(e),
                grafico_pareto_centros(e),
                grafico_calor_centro_mes(e),
            ],
        ),
        Secao(
            "Eficiência",
            [
                grafico_cabeca_dia_mensal(e),
                grafico_por_fazenda(e),
                grafico_custo_por_cabeca_fazenda(e),
            ],
            tabelas=[tabela_maiores_lancamentos(e)],
        ),
    ]
    return painel
