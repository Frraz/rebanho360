"""Aba **Mortes** — quantas, quando, de quê e onde.

Tudo sai do razão do rebanho (`HerdLedgerEntry`, movimentos de MORTE): somar a
linha com sinal já respeita o desfazer, porque a compensação vale na data do
fato original. Mortalidade é a de sempre, `herd.mortality` (mortes ÷ saldo médio):
a aba só a abre por mês e por faixa.

Decisões de cliente (docs/regras-negocio/12): **sem alerta** de mortalidade — o
sistema mostra, não julga —, e causa é opcional ("Não informada" é uma fatia
como outra).
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse

from apps.core.money import safe_div
from apps.herd.models import DeathCause, MovementType
from apps.livestock.models import AnimalCategory, Lot

from . import custos, rebanho, specs
from .escopo import Escopo
from .specs import Kpi, Painel, Secao, Tabela

ZERO = Decimal("0")
CEM = Decimal("100")

#: Fronteira entre jovem e adulto, por `AnimalCategory.age_order` (1 e 2: bezerros
#: e desmama; 3: 13 a 24 meses). A planilha separa "jovens" de "adultos" sem
#: definir a linha: esta é a escolha reversível (pendência em 99-pendencias.md).
#: Categoria sem ordem etária (tropa) conta como adulto.
ULTIMA_ORDEM_JOVEM = 3

SEM_CAUSA = "Não informada"
COR_JOVENS = 4
COR_ADULTOS = 5

NOTA_SEM_JULGAMENTO = 'O sistema não julga o que é "acima do normal": a leitura é sua.'


def eh_jovem(age_order: int | None) -> bool:
    return age_order is not None and age_order <= ULTIMA_ORDEM_JOVEM


# --------------------------------------------------------------------------
# Dados (cada função é calculada uma vez por requisição: `Escopo.memo`)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Morte:
    """Mortes líquidas de um mês, fazenda, lote, categoria e causa."""

    mes: datetime.date
    farm_id: int
    lot_id: int
    category_id: int
    causa: str  # código de `DeathCause`; vazio = não informada
    cabecas: int
    peso_kg: Decimal | None


def mortes(e: Escopo) -> list[Morte]:
    """Todas as mortes do recorte, numa consulta. Linha desfeita soma zero e some."""

    def calcular():
        linhas = (
            e.razao()
            .filter(movement__type=MovementType.MORTE, date__gte=e.inicio)
            .annotate(mes=TruncMonth("date"))
            .values_list(
                "mes",
                "farm_id",
                "lot_id",
                "category_id",
                "movement__death_cause",
            )
            .annotate(q=Sum("quantity"), p=Sum("weight_kg"))
            .order_by()
        )
        return [
            Morte(
                mes,
                farm_id,
                lot_id,
                category_id,
                causa or "",
                -(q or 0),
                -p if p is not None else None,
            )
            for mes, farm_id, lot_id, category_id, causa, q, p in linhas
            if q
        ]

    return e.memo("mortes_linhas", calcular)


def _categorias(e: Escopo) -> dict[int, AnimalCategory]:
    return e.memo(
        "mortes_categorias", lambda: {c.pk: c for c in AnimalCategory.objects.all()}
    )


def total(e: Escopo) -> int:
    return sum(m.cabecas for m in mortes(e))


def _por_mes_e_faixa(e: Escopo) -> tuple[list[int], list[int]]:
    """Mortes de cada mês: `(jovens, adultos)`."""

    def calcular():
        categorias = _categorias(e)
        indice = {m: i for i, m in enumerate(e.meses)}
        jovens, adultos = [0] * len(indice), [0] * len(indice)
        for m in mortes(e):
            if m.mes not in indice:
                continue
            alvo = jovens if eh_jovem(categorias[m.category_id].age_order) else adultos
            alvo[indice[m.mes]] += m.cabecas
        return jovens, adultos

    return e.memo("mortes_mes_faixa", calcular)


def _estoque_por_faixa(e: Escopo) -> tuple[list[int], list[int]]:
    """Cabeças no fim de cada mês: `(jovens, adultos)` — a abertura mais o fluxo
    acumulado do razão, por faixa etária."""

    def calcular():
        meses = e.meses
        indice = {m: i for i, m in enumerate(meses)}
        acumulado = {True: 0, False: 0}
        for ordem, soma in (
            e.razao(ate=e.inicio - datetime.timedelta(days=1))
            .values_list("category__age_order")
            .annotate(t=Sum("quantity"))
            .order_by()
        ):
            acumulado[eh_jovem(ordem)] += soma or 0
        fluxo = {True: [0] * len(meses), False: [0] * len(meses)}
        for mes, ordem, soma in (
            e.razao()
            .filter(date__gte=e.inicio)
            .annotate(mes=TruncMonth("date"))
            .values_list("mes", "category__age_order")
            .annotate(t=Sum("quantity"))
            .order_by()
        ):
            if mes in indice:
                fluxo[eh_jovem(ordem)][indice[mes]] += soma or 0
        series = {}
        for faixa in (True, False):
            corrente, serie = acumulado[faixa], []
            for passo in fluxo[faixa]:
                corrente += passo
                serie.append(corrente)
            series[faixa] = serie
        return series[True], series[False]

    return e.memo("mortes_estoque_faixa", calcular)


def _dias_do_mes(e: Escopo, mes: datetime.date) -> int:
    """Dias do mês dentro do recorte (o mês corrente conta só até o corte): a
    mesma janela de `custos.cabecas_dia_por_mes`."""
    inicio = max(mes, e.inicio)
    fim = min(
        (mes + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1),
        e.fim,
    )
    return (fim - inicio).days + 1


def mortalidade_por_mes(e: Escopo) -> list[Decimal | None]:
    """Mortes do mês ÷ saldo médio do mês × 100 (cabeça-dia ÷ dias). É a conta de
    `herd.mortality`, aberta por mês: `None` em mês sem rebanho, nunca 0."""
    jovens, adultos = _por_mes_e_faixa(e)
    cabecas_dia = custos.cabecas_dia_por_mes(e)
    saida = []
    for i, mes in enumerate(e.meses):
        saldo_medio = safe_div(cabecas_dia[i], _dias_do_mes(e, mes))
        taxa = safe_div(Decimal(jovens[i] + adultos[i]), saldo_medio)
        saida.append(taxa * CEM if taxa is not None else None)
    return saida


def mortalidade_por_faixa(e: Escopo) -> tuple[list, list]:
    """Mortes do mês ÷ estoque no fim do mês × 100, por faixa — como a planilha
    (`#DIV/0!` lá, "—" aqui)."""
    mortes_j, mortes_a = _por_mes_e_faixa(e)
    estoque_j, estoque_a = _estoque_por_faixa(e)

    def taxas(mortes_, estoque):
        saida = []
        for m, s in zip(mortes_, estoque, strict=True):
            t = safe_div(Decimal(m), Decimal(s)) if s > 0 else None
            saida.append(t * CEM if t is not None else None)
        return saida

    return taxas(mortes_j, estoque_j), taxas(mortes_a, estoque_a)


def _agrupar(e: Escopo, chave) -> dict:
    soma = defaultdict(int)
    for m in mortes(e):
        soma[chave(m)] += m.cabecas
    return soma


def por_causa(e: Escopo) -> list[tuple[str, int]]:
    rotulos = dict(DeathCause.choices)

    def rotulo(m):
        return rotulos.get(m.causa, SEM_CAUSA) if m.causa else SEM_CAUSA

    return sorted(_agrupar(e, rotulo).items(), key=lambda kv: -kv[1])


def sem_causa(e: Escopo) -> int:
    return sum(m.cabecas for m in mortes(e) if not m.causa)


def por_categoria(e: Escopo) -> list[tuple[str, int]]:
    categorias = _categorias(e)
    return sorted(
        _agrupar(e, lambda m: categorias[m.category_id].name).items(),
        key=lambda kv: -kv[1],
    )


def por_fazenda(e: Escopo) -> list[tuple[str, int]]:
    nomes = {f.pk: f.name for f in e.fazendas()}
    return sorted(
        _agrupar(e, lambda m: nomes.get(m.farm_id, f"Fazenda {m.farm_id}")).items(),
        key=lambda kv: -kv[1],
    )


def _peso_morto(e: Escopo) -> Decimal | None:
    pesos = [m.peso_kg for m in mortes(e) if m.peso_kg is not None]
    return sum(pesos, ZERO) if pesos else None


# --------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------


def kpis(e: Escopo) -> list[Kpi]:
    atual = total(e)
    anterior = total(e.anterior) if e.anterior else None
    jovens, adultos = _por_mes_e_faixa(e)
    sem = sem_causa(e)
    causas = [c for c in por_causa(e) if c[0] != SEM_CAUSA]
    url = reverse("herd:movimento_lista")
    return [
        Kpi(
            "Mortes na safra",
            specs.formatar(atual),
            "cabeças",
            nota=f"{sum(jovens)} jovens · {sum(adultos)} adultos",
            delta=specs.variacao(atual, anterior, bom_quando="baixa"),
            spark=specs.sparkline(
                [a + b for a, b in zip(jovens, adultos, strict=True)]
            ),
            url=url,
            destaque=True,
            ajuda=(
                "Cabeças de movimentações de morte da safra. Jovem é a categoria até "
                "13 a 24 meses; as demais contam como adulto."
            ),
        ),
        rebanho.kpi_mortalidade(e),
        Kpi(
            "Principal causa",
            causas[0][0] if causas else specs.TRAVESSAO,
            nota=(
                f"{causas[0][1]} cabeça(s) · "
                f"{specs.formatar(specs.pct(causas[0][1], atual), 'pct')} das mortes"
                if causas
                else "nenhuma morte com causa informada"
            ),
        ),
        Kpi(
            "Mortes sem causa informada",
            specs.formatar(sem),
            "cabeças",
            nota=(
                f"{specs.formatar(specs.pct(sem, atual), 'pct')} das mortes"
                if atual
                else ""
            ),
            estado="atencao" if sem else "bom",
            estado_texto="Falta dado" if sem else "Tudo informado",
            url=url,
            ajuda="A causa é opcional no lançamento; sem ela, a morte entra em 'Não informada'.",
        ),
        Kpi(
            "Peso das cabeças mortas",
            specs.formatar(_peso_morto(e), "kg"),
            nota="só mortes lançadas com peso",
        ),
    ]


# --------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------


def _x(e: Escopo) -> list[str]:
    return [specs.rotulo_do_mes(m) for m in e.meses]


def grafico_mortes_por_mes(e: Escopo) -> specs.Grafico:
    jovens, adultos = _por_mes_e_faixa(e)
    return specs.cartesiano(
        "mortes-aba-mes",
        "Mortes por mês",
        _x(e),
        [
            specs.serie("Jovens", jovens, pilha="mortes", cor=COR_JOVENS),
            specs.serie("Adultos", adultos, pilha="mortes", cor=COR_ADULTOS),
        ],
        formato="cb",
        titulo_y="Cabeças",
        largura="dois-tercos",
        url=reverse("herd:movimento_lista"),
        nota=f"Jovem = categoria até a ordem etária {ULTIMA_ORDEM_JOVEM} (13 a 24 meses).",
    )


def grafico_por_causa(e: Escopo) -> specs.Grafico:
    return specs.ranking(
        "mortes-aba-causa",
        "Mortes por causa",
        por_causa(e),
        formato="cb",
        nome_serie="Mortes",
        limite=10,
        largura="terco",
        nota='"Não informada" é a morte lançada sem causa: a causa é opcional.',
    )


def grafico_mortalidade_por_mes(e: Escopo) -> specs.Grafico:
    return specs.cartesiano(
        "mortes-aba-taxa-mes",
        "Mortalidade por mês",
        _x(e),
        [
            specs.serie(
                "Mortalidade", mortalidade_por_mes(e), tipo="line", cor=specs.COR_ALERTA
            )
        ],
        formato="pct2",
        titulo_y="% do rebanho",
        largura="metade",
        nota="Mortes do mês ÷ saldo médio do mês — a conta do painel inicial, mês a mês. "
        f"Mês sem rebanho fica em branco. {NOTA_SEM_JULGAMENTO}",
    )


def grafico_mortalidade_por_faixa(e: Escopo) -> specs.Grafico:
    jovens, adultos = mortalidade_por_faixa(e)
    return specs.cartesiano(
        "mortes-aba-taxa-faixa",
        "Mortalidade de jovens e de adultos",
        _x(e),
        [
            specs.serie("Jovens", jovens, tipo="line", cor=COR_JOVENS),
            specs.serie("Adultos", adultos, tipo="line", cor=COR_ADULTOS),
        ],
        formato="pct2",
        titulo_y="% do estoque",
        largura="metade",
        nota="Mortes do mês ÷ cabeças no fim do mês, como na planilha. "
        "Faixa sem estoque no mês fica em branco (a planilha mostrava #DIV/0!).",
    )


def grafico_estoque_por_faixa(e: Escopo) -> specs.Grafico:
    jovens, adultos = _estoque_por_faixa(e)
    return specs.cartesiano(
        "mortes-aba-estoque",
        "Rebanho no fim de cada mês",
        _x(e),
        [
            specs.serie("Jovens", jovens, tipo="line", cor=COR_JOVENS),
            specs.serie("Adultos", adultos, tipo="line", cor=COR_ADULTOS),
        ],
        formato="cb",
        titulo_y="Cabeças",
        largura="metade",
        url=reverse("herd:posicao"),
        nota="É o denominador da mortalidade por faixa.",
    )


def grafico_por_categoria(e: Escopo) -> specs.Grafico:
    return specs.ranking(
        "mortes-aba-categoria",
        "Mortes por categoria",
        por_categoria(e),
        formato="cb",
        nome_serie="Mortes",
        limite=10,
        largura="metade",
    )


def grafico_por_fazenda(e: Escopo) -> specs.Grafico:
    return specs.ranking(
        "mortes-aba-fazenda",
        "Mortes por fazenda",
        por_fazenda(e),
        formato="cb",
        nome_serie="Mortes",
        limite=10,
        largura="metade",
    )


def tabela_de_lotes(e: Escopo, limite: int = 15) -> Tabela:
    por_lote = _agrupar(e, lambda m: m.lot_id)
    lotes = {
        lt.pk: lt
        for lt in Lot.objects.filter(pk__in=list(por_lote)).select_related("farm")
    }
    # Empate no número de mortes: pelo código do lote, para a ordem não variar.
    maiores = sorted(por_lote.items(), key=lambda kv: (-kv[1], lotes[kv[0]].code))[
        :limite
    ]
    todas = total(e)
    linhas, links, valores = [], [], []
    for pk, cabecas in maiores:
        lote = lotes[pk]
        linhas.append(
            [
                lote.code,
                lote.farm.name,
                specs.formatar(cabecas),
                specs.formatar(specs.pct(cabecas, todas), "pct"),
            ]
        )
        links.append(reverse("livestock:lote_detalhe", args=[pk]))
        valores.append(cabecas)
    t = Tabela(
        ["Lote", "Fazenda", "Mortes", "% das mortes"],
        linhas,
        numericas=[2, 3],
        titulo="Lotes com mais mortes",
        links=links,
        codigo=0,
        legenda="Quantidade de mortes, não taxa: um lote grande morre mais em número.",
    )
    t.barra(2, valores)
    t.vazio = "Nenhuma morte registrada."
    return t


# --------------------------------------------------------------------------
# Aba
# --------------------------------------------------------------------------


def montar(e: Escopo) -> Painel:
    painel = Painel(kpis=kpis(e), kpis_titulo="Mortes da safra")
    if not total(e):
        painel.vazio = (
            "Nenhuma morte registrada na safra e no recorte escolhidos. "
            "Quando houver, esta aba mostra quando, de quê e onde."
        )
        return painel
    painel.secoes = [
        Secao(
            "Quando e de quê",
            [grafico_mortes_por_mes(e), grafico_por_causa(e)],
            "Quantas morreram a cada mês e a causa informada no lançamento.",
        ),
        Secao(
            "Mortalidade",
            [grafico_mortalidade_por_mes(e), grafico_mortalidade_por_faixa(e)],
            "A taxa mês a mês, no total e por faixa etária.",
        ),
        Secao(
            "Onde",
            [
                grafico_estoque_por_faixa(e),
                grafico_por_categoria(e),
                grafico_por_fazenda(e),
            ],
            tabelas=[tabela_de_lotes(e)],
        ),
    ]
    if sem_causa(e):
        painel.avisos.append(
            f"{sem_causa(e)} cabeça(s) morreram sem causa informada e aparecem como "
            f'"{SEM_CAUSA}". Corrija a movimentação para completar a análise.'
        )
    return painel
