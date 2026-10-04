"""Aba **Vendas e resultado** — o que entrou, a que preço e se o boi pagou o
que custou criar.

Preço, rendimento e @ vêm de `apps.sales.carcass` e o resultado de
`resultado_do_lote`: o mesmo número da tela da venda e da tela do lote.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.urls import reverse

from apps.core.money import safe_div
from apps.sales import carcass
from apps.sales.models import SaleType
from apps.sales.result import ResultadoDoLote
from apps.sales.result import resultados_dos_lotes as _resultados

from . import specs
from .escopo import Escopo
from .specs import Kpi, Painel, Secao, Tabela

ZERO = Decimal("0")
LOTES_NO_GRAFICO = 24


def lista_de_vendas(e: Escopo) -> list:
    return e.memo(
        "vendas",
        lambda: list(
            e.vendas()
            .select_related("buyer", "farm", "lot", "lot__farm", "category")
            .order_by("date", "id")
        ),
    )


def abates(e: Escopo) -> list:
    return [v for v in lista_de_vendas(e) if v.type == SaleType.ABATE]


def agregado(vendas) -> carcass.AgregadoDeVendas:
    return carcass.agregar(vendas)


def por_mes(e: Escopo) -> dict[datetime.date, list]:
    grupos = defaultdict(list)
    for v in lista_de_vendas(e):
        grupos[v.date.replace(day=1)].append(v)
    return {m: grupos.get(m, []) for m in e.meses}


def prazo_medio_de_recebimento(e: Escopo) -> Decimal | None:
    com_prazo = [v for v in lista_de_vendas(e) if v.payment_days is not None]
    base = sum((v.total_value for v in com_prazo), ZERO)
    return safe_div(
        sum((v.total_value * v.payment_days for v in com_prazo), ZERO), base
    )


# --------------------------------------------------------------------------
# Resultado por lote (compartilhado com a aba Lotes e a visão geral)
# --------------------------------------------------------------------------


def resultados_dos_lotes(e: Escopo) -> list[ResultadoDoLote]:
    """O resultado de cada lote **com venda na safra**, do serviço do sistema.
    Cada lote vale pelas vendas dele **inteiras** (resultado é do lote, não do
    mês): é o número que a tela do lote mostra."""

    def calcular():
        lotes = sorted(
            {v.lot_id: v.lot for v in lista_de_vendas(e)}.values(),
            key=lambda lt: lt.code,
        )
        resultados = _resultados(lotes, financeiros=e.financeiro_dos_lotes(lotes))
        return [resultados[lt.pk] for lt in lotes]

    return e.memo("resultados_dos_lotes", calcular)


@dataclass(frozen=True)
class ResultadoDaSafra:
    lotes_com_venda: int
    lotes_com_resultado: int
    receita: Decimal
    aquisicao: Decimal
    diretos: Decimal
    rateados: Decimal
    resultado: Decimal
    arrobas: Decimal
    receita_com_arroba: Decimal
    custo_com_arroba: Decimal

    @property
    def margem_por_arroba(self) -> Decimal | None:
        """(receita − custo) ÷ @ vendidas, só dos lotes com as duas pontas:
        a mesma definição `margem/@ = valor/@ − custo/@` do lote, somada."""
        return safe_div(self.receita_com_arroba - self.custo_com_arroba, self.arrobas)

    @property
    def custo(self) -> Decimal:
        return self.aquisicao + self.diretos + self.rateados


def resultado_da_safra(e: Escopo) -> ResultadoDaSafra:
    def calcular():
        lotes = resultados_dos_lotes(e)
        com = [r for r in lotes if r.resultado is not None]
        receita = aquis = dir_ = rat = resultado = arrobas = rec_a = cus_a = ZERO
        for r in com:
            f = r.fracao_vendida
            receita += r.receita
            aquis += (r.custo_aquisicao or ZERO) * f
            dir_ += (r.custos_diretos or ZERO) * f
            rat += (r.custos_rateados or ZERO) * f
            resultado += r.resultado
            if r.arrobas_vendidas:
                arrobas += r.arrobas_vendidas
                rec_a += r.receita
                cus_a += r.custo_considerado
        return ResultadoDaSafra(
            len(lotes),
            len(com),
            receita,
            aquis,
            dir_,
            rat,
            resultado,
            arrobas,
            rec_a,
            cus_a,
        )

    return e.memo("resultado_da_safra", calcular)


# --------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------


def kpis(e: Escopo) -> list[Kpi]:
    vendas = lista_de_vendas(e)
    atual = agregado(vendas)
    ab = agregado(abates(e))
    anterior_vendas = list(e.anterior.vendas()) if e.anterior else None
    ant = agregado(anterior_vendas) if anterior_vendas is not None else None
    ant_ab = (
        agregado([v for v in anterior_vendas if v.type == SaleType.ABATE])
        if anterior_vendas is not None
        else None
    )
    meses = por_mes(e)
    res = resultado_da_safra(e)
    url = reverse("sales:lista")
    ind, ind_ant = ab.indicadores, ant_ab.indicadores if ant_ab else None
    sem_carcaca = sum(1 for v in abates(e) if not v.carcass_weight_kg)
    cobertura = (
        f"{res.lotes_com_resultado} de {res.lotes_com_venda} lotes com resultado"
        if res.lotes_com_venda
        else "nenhum lote vendido"
    )
    return [
        Kpi(
            "Receita de vendas",
            specs.brl_curto(atual.valor_total) if atual.vendas else specs.TRAVESSAO,
            nota=f"{specs.formatar(atual.cabecas)} cabeças · {atual.vendas} venda(s)",
            delta=specs.variacao(atual.valor_total, ant.valor_total if ant else None),
            spark=specs.sparkline([agregado(v).valor_total for v in meses.values()]),
            url=url,
            destaque=True,
        ),
        Kpi(
            "Resultado dos lotes vendidos",
            (
                specs.brl_curto(res.resultado)
                if res.lotes_com_resultado
                else specs.TRAVESSAO
            ),
            nota=cobertura,
            estado=(
                ("bom" if res.resultado > 0 else "ruim")
                if res.lotes_com_resultado
                else ""
            ),
            estado_texto=(
                ("Lucro" if res.resultado > 0 else "Prejuízo")
                if res.lotes_com_resultado
                else ""
            ),
            ajuda=(
                "Soma do resultado dos lotes com venda na safra (receita − aquisição − custos "
                "diretos − custos rateados). Lote sem compra registrada não tem resultado e fica de fora."
            ),
        ),
        Kpi(
            "Margem por @",
            specs.formatar(res.margem_por_arroba, "brl"),
            nota="valor/@ − custo/@, dos lotes com carcaça",
            ajuda="(Receita − custo) ÷ @ de carcaça vendidas, só dos lotes que têm as duas pontas.",
        ),
        Kpi(
            "Valor por @ (abates)",
            specs.formatar(ind.valor_por_arroba, "brl"),
            nota=f"{ab.com_carcaca} abate(s) com carcaça",
            delta=specs.variacao(
                ind.valor_por_arroba, ind_ant.valor_por_arroba if ind_ant else None
            ),
            ajuda="Valor ÷ @ de carcaça (peso de carcaça ÷ 15) dos abates com peso de carcaça.",
        ),
        Kpi(
            "Rendimento de carcaça",
            specs.formatar(ind.rendimento, "pct2"),
            nota=f"faixa usual {carcass.FAIXA_DE_RENDIMENTO[0]:.0f}% a {carcass.FAIXA_DE_RENDIMENTO[1]:.0f}%",
            delta=specs.variacao_pp(
                ind.rendimento,
                ind_ant.rendimento if ind_ant else None,
                bom_quando="alta",
            ),
        ),
        Kpi(
            "Peso médio de venda",
            specs.formatar(atual.indicadores.peso_medio_vivo, "kg"),
            nota="peso vivo por cabeça",
        ),
        Kpi(
            "Valor por cabeça",
            specs.formatar(atual.indicadores.valor_por_cabeca, "brl"),
            delta=specs.variacao(
                atual.indicadores.valor_por_cabeca,
                ant.indicadores.valor_por_cabeca if ant else None,
            ),
        ),
        Kpi(
            "Prazo médio de recebimento",
            specs.formatar(prazo_medio_de_recebimento(e), "dias"),
            nota="ponderado pelo valor",
        ),
        Kpi(
            "Abates sem peso de carcaça",
            specs.formatar(sem_carcaca),
            nota="valor/@ e rendimento ficam em branco",
            estado="atencao" if sem_carcaca else "bom",
            estado_texto="Falta dado" if sem_carcaca else "Tudo preenchido",
            url=reverse("sales:lista") + "?sem_carcaca=1" if sem_carcaca else "",
        ),
    ]


# --------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------


def grafico_receita(e: Escopo) -> specs.Grafico:
    meses = por_mes(e)
    x = [specs.rotulo_do_mes(m) for m in meses]
    series = []
    for tipo, rotulo, cor in (
        (SaleType.ABATE, "Abate", specs.COR_VENDAS),
        (SaleType.VENDA, "Venda em pé", specs.COR_ALERTA),
    ):
        dados = [
            sum((v.total_value for v in vs if v.type == tipo), ZERO)
            for vs in meses.values()
        ]
        if any(dados):
            series.append(specs.serie(rotulo, dados, pilha="receita", cor=cor))
    return specs.cartesiano(
        "vendas-receita",
        "Receita por mês",
        x,
        series,
        formato="brl",
        titulo_y="R$",
        largura="dois-tercos",
        url=reverse("sales:lista"),
    )


def grafico_cabecas(e: Escopo) -> specs.Grafico:
    meses = por_mes(e)
    return specs.cartesiano(
        "vendas-cabecas",
        "Cabeças vendidas por mês",
        [specs.rotulo_do_mes(m) for m in meses],
        [
            specs.serie(
                "Cabeças",
                [sum(v.head_count for v in vs) for vs in meses.values()],
                cor=specs.COR_VENDAS,
            )
        ],
        formato="cb",
        largura="terco",
    )


def grafico_valor_arroba(e: Escopo) -> specs.Grafico:
    meses = por_mes(e)
    dados = []
    for vs in meses.values():
        ab = [v for v in vs if v.type == SaleType.ABATE]
        dados.append(agregado(ab).indicadores.valor_por_arroba if ab else None)
    return specs.cartesiano(
        "vendas-valor-arroba",
        "Valor por @ de carcaça, mês a mês",
        [specs.rotulo_do_mes(m) for m in meses],
        [specs.serie("Valor/@", dados, tipo="line", cor="marca")],
        formato="brl",
        titulo_y="R$ por @",
        nota="Só abates com peso de carcaça. Mês sem abate fica em branco.",
    )


def grafico_rendimento_mensal(e: Escopo) -> specs.Grafico:
    meses = por_mes(e)
    dados = []
    for vs in meses.values():
        ab = [v for v in vs if v.type == SaleType.ABATE and v.carcass_weight_kg]
        dados.append(agregado(ab).indicadores.rendimento if ab else None)
    minimo, maximo = carcass.FAIXA_DE_RENDIMENTO
    return specs.cartesiano(
        "vendas-rendimento",
        "Rendimento de carcaça, mês a mês",
        [specs.rotulo_do_mes(m) for m in meses],
        [specs.serie("Rendimento", dados, tipo="line", cor="marca")],
        formato="pct2",
        titulo_y="% do peso vivo",
        faixa={"de": float(minimo), "ate": float(maximo), "rotulo": "Faixa usual"},
        nota=f"A faixa sombreada ({minimo:.0f}% a {maximo:.0f}%) é a que o sistema considera usual.",
    )


def grafico_dispersao_rendimento(e: Escopo) -> specs.Grafico:
    dentro, fora = [], []
    for v in abates(e):
        if not v.carcass_weight_kg:
            continue
        ind = carcass.indicadores_da_venda(v)
        ponto = {
            "x": ind.peso_medio_vivo,
            "y": ind.rendimento,
            "r": v.head_count,
            "nome": f"{v.code} · {v.buyer.name}",
        }
        (fora if carcass.rendimento_fora_da_faixa(ind.rendimento) else dentro).append(
            ponto
        )
    minimo, maximo = carcass.FAIXA_DE_RENDIMENTO
    series = [{"nome": "Na faixa usual", "cor": "marca", "pontos": dentro}]
    if fora:
        series.append(
            {"nome": "Fora da faixa", "cor": specs.COR_ALERTA, "pontos": fora}
        )
    return specs.dispersao(
        "vendas-dispersao-rendimento",
        "Peso de venda × rendimento, abate a abate",
        series,
        formato_x="kg",
        formato_y="pct2",
        titulo_x="Peso médio vivo (kg)",
        titulo_y="Rendimento (%)",
        faixa={"de": float(minimo), "ate": float(maximo), "rotulo": "Faixa usual"},
        colunas_tabela="Cabeças",
        nota="Cada bolha é um abate; o tamanho é o número de cabeças. Fora da faixa: confira o peso.",
    )


def grafico_compradores(e: Escopo) -> specs.Grafico:
    soma = defaultdict(lambda: ZERO)
    for v in lista_de_vendas(e):
        soma[v.buyer.name] += v.total_value
    return specs.ranking(
        "vendas-compradores",
        "Quem comprou mais",
        list(soma.items()),
        formato="brl",
        nome_serie="Receita",
        largura="terco",
        url=reverse("partners:lista"),
    )


def grafico_por_fazenda(e: Escopo) -> specs.Grafico:
    soma = defaultdict(lambda: ZERO)
    for v in lista_de_vendas(e):
        soma[v.farm.name] += v.total_value
    return specs.ranking(
        "vendas-fazenda",
        "Receita por fazenda",
        list(soma.items()),
        formato="brl",
        nome_serie="Receita",
        largura="terco",
    )


def grafico_por_tipo(e: Escopo) -> specs.Grafico:
    soma = defaultdict(lambda: ZERO)
    for v in lista_de_vendas(e):
        soma[v.get_type_display()] += v.total_value
    cores = {"Abate": specs.COR_VENDAS, "Venda de animal vivo": specs.COR_ALERTA}
    return specs.rosca(
        "vendas-tipo",
        "Abate × animal vivo",
        [(n, v, cores.get(n)) for n, v in soma.items()],
        formato="brl",
        centro_rotulo="receita",
        largura="terco",
    )


def grafico_cascata(e: Escopo) -> specs.Grafico:
    r = resultado_da_safra(e)
    return specs.cascata(
        "vendas-cascata",
        "Do que se vendeu ao que sobrou",
        [
            ("Receita", r.receita, "total"),
            ("Aquisição", -r.aquisicao, "delta"),
            ("Custos diretos", -r.diretos, "delta"),
            ("Custos rateados", -r.rateados, "delta"),
            ("Resultado", r.resultado, "total"),
        ],
        formato="brl",
        nota=(
            "Dos lotes com venda na safra e resultado calculável. Custos pela fração já vendida "
            "de cada lote; custos rateados pelo critério de cada centro."
        ),
        largura="metade",
    )


def grafico_resultado_por_lote(e: Escopo) -> specs.Grafico:
    com = [r for r in resultados_dos_lotes(e) if r.resultado is not None]
    ordenados = sorted(com, key=lambda r: r.resultado)
    nota = "Lucro à direita, prejuízo à esquerda. Lote ainda com animais mostra o resultado parcial."
    if len(ordenados) > LOTES_NO_GRAFICO:
        metade = LOTES_NO_GRAFICO // 2
        nota += f" Mostra os {metade} piores e os {metade} melhores de {len(ordenados)}; a aba Lotes traz todos."
        ordenados = ordenados[:metade] + ordenados[-metade:]
    g = specs.cartesiano(
        "vendas-resultado-lote",
        "Resultado de cada lote",
        [r.lote.code for r in ordenados],
        [
            specs.serie(
                "Resultado",
                [r.resultado for r in ordenados],
                cor="positivo",
                rotulo=True,
                por_sinal=True,
            )
        ],
        formato="brl",
        horizontal=True,
        nota=nota,
        largura="cheia",
        altura=max(240, 60 + 24 * len(ordenados)),
        url=reverse("livestock:lote_lista"),
    )
    return g


def grafico_custo_x_valor_por_arroba(e: Escopo) -> specs.Grafico:
    lucro, prejuizo = [], []
    for r in resultados_dos_lotes(e):
        if r.custo_por_arroba is None or r.valor_por_arroba is None:
            continue
        ponto = {
            "x": r.custo_por_arroba,
            "y": r.valor_por_arroba,
            "r": r.cabecas_vendidas,
            "nome": r.lote.code,
        }
        (lucro if r.valor_por_arroba >= r.custo_por_arroba else prejuizo).append(ponto)
    series = [{"nome": "Lucro", "cor": "positivo", "pontos": lucro}]
    if prejuizo:
        series.append({"nome": "Prejuízo", "cor": "negativo", "pontos": prejuizo})
    return specs.dispersao(
        "vendas-custo-valor-arroba",
        "Custo por @ × valor por @, lote a lote",
        series,
        formato_x="brl",
        formato_y="brl",
        titulo_x="Custo por @ (R$)",
        titulo_y="Valor por @ (R$)",
        linhas_ref=[{"tipo": "diagonal", "rotulo": "Empata (custo = valor)"}],
        colunas_tabela="Cabeças vendidas",
        nota="Acima da diagonal o lote deu lucro; abaixo, prejuízo. O tamanho da bolha é o número de cabeças vendidas.",
    )


def tabela_ultimas_vendas(e: Escopo) -> Tabela:
    recentes = sorted(lista_de_vendas(e), key=lambda v: (v.date, v.pk), reverse=True)[
        :10
    ]
    linhas, links, totais, marcas = [], [], [], {}
    for i, v in enumerate(recentes):
        ind = carcass.indicadores_da_venda(v)
        linhas.append(
            [
                v.code,
                f"{v.date:%d/%m/%Y}",
                v.buyer.name,
                v.get_type_display(),
                specs.formatar(v.head_count),
                specs.formatar(ind.rendimento, "pct2"),
                specs.formatar(ind.valor_por_arroba, "brl"),
                specs.formatar(v.total_value, "brl"),
            ]
        )
        links.append(reverse("sales:detalhe", args=[v.pk]))
        totais.append(v.total_value)
        if v.type == SaleType.ABATE:
            if ind.rendimento is None:
                marcas[(i, 5)] = ("atencao", "sem carcaça")
            elif carcass.rendimento_fora_da_faixa(ind.rendimento):
                marcas[(i, 5)] = ("ruim", "fora da faixa")
    t = Tabela(
        [
            "Venda",
            "Data",
            "Comprador",
            "Tipo",
            "Cabeças",
            "Rendimento",
            "Valor/@",
            "Valor",
        ],
        linhas,
        numericas=[4, 5, 6, 7],
        titulo="Dez vendas mais recentes",
        links=links,
        codigo=0,
        marcas=marcas,
        vazio="Nenhuma venda confirmada na safra.",
    )
    t.barra(7, totais)
    return t


# --------------------------------------------------------------------------
# Aba
# --------------------------------------------------------------------------


def montar(e: Escopo) -> Painel:
    painel = Painel(kpis=kpis(e), kpis_titulo="Vendas da safra")
    if not lista_de_vendas(e):
        painel.vazio = "Nenhuma venda confirmada na safra e no recorte escolhidos."
    res = resultado_da_safra(e)
    if res.lotes_com_venda and res.lotes_com_resultado < res.lotes_com_venda:
        painel.avisos.append(
            f"{res.lotes_com_venda - res.lotes_com_resultado} lote(s) vendido(s) sem resultado: "
            "falta compra registrada (custo de aquisição) ou o rateio de custos não fecha. "
            "Nunca se mostra um lucro inventado."
        )
    painel.secoes = [
        Secao("Receita", [grafico_receita(e), grafico_cabecas(e)]),
        Secao(
            "Preço e carcaça",
            [
                grafico_valor_arroba(e),
                grafico_rendimento_mensal(e),
                grafico_dispersao_rendimento(e),
            ],
        ),
        Secao(
            "Resultado",
            [
                grafico_cascata(e),
                grafico_custo_x_valor_por_arroba(e),
                grafico_resultado_por_lote(e),
            ],
            "O boi pagou o que custou criar?",
        ),
        Secao(
            "Para quem e onde",
            [grafico_compradores(e), grafico_por_fazenda(e), grafico_por_tipo(e)],
            tabelas=[tabela_ultimas_vendas(e)],
        ),
    ]
    return painel
