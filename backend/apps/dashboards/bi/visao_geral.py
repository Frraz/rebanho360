"""Aba **Visão geral** — a página que um gestor abre de manhã.

Junta, sem recalcular, os indicadores que as outras abas detalham: o mesmo
número, o mesmo serviço (regra 6). Quem não vê dinheiro (campo) recebe só o
rebanho e o desempenho dos lotes.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from django.urls import reverse

from apps.dashboards import selectors as painel_selectors

from . import (
    ciclo,
    compras,
    custos,
    financeiro,
    insights,
    lotes,
    rebanho,
    specs,
    vendas,
)
from .escopo import Escopo
from .specs import Kpi, Painel, Secao, Tabela

ZERO = Decimal("0")


def kpi_custo_por_arroba(e: Escopo) -> Kpi:
    """O mesmo número do painel inicial ("Custo/@ — lotes encerrados"), do
    mesmo seletor — não uma segunda definição."""
    cartao = painel_selectors.cartao_da_safra(
        e.user,
        season=e.season,
        farm=e.farm,
        cabecas_atuais=rebanho.total_de_cabecas(e),
        financeiro_de=e.financeiro_dos_lotes,
    )
    return Kpi(
        "Custo/@ (lotes encerrados)",
        specs.formatar(cartao.custo_por_arroba if cartao else None, "brl"),
        nota=(
            f"{cartao.lotes_encerrados} lote(s) encerrado(s)"
            if cartao and cartao.custo_por_arroba is not None
            else (f"indisponível: {cartao.motivo_custo_por_arroba}" if cartao else "")
        ),
        ajuda="Custo do lote ÷ @ de carcaça vendida, dos lotes que encerraram na safra.",
    )


def kpis(e: Escopo) -> list[Kpi]:
    saida = [rebanho.kpi_cabecas(e)]
    if e.ver_dinheiro:
        # Por rótulo, não por posição: a aba de vendas ganha cartões sem quebrar a
        # visão geral.
        v = {k.rotulo: k for k in vendas.kpis(e)}
        saida += [
            compras.kpis(e)[0],
            v["Receita de vendas"],
            v["Resultado dos lotes vendidos"],
            custos.kpis(e)[0],
        ]
        saida.append(kpi_custo_por_arroba(e))
    saida.append(rebanho.kpi_mortalidade(e))
    linhas = lotes.linhas_de_lotes(e)
    media = lotes.gmd_medio(linhas)
    saida.append(
        Kpi(
            "GMD médio",
            specs.formatar(media, "kgdia"),
            nota=f"{sum(1 for lt in linhas if lt.gmd is not None)} lote(s) com duas pesagens",
        )
    )
    if e.ver_dinheiro and e.ver_titulos:
        n, valor = financeiro.total_em_aberto(e, "PAGAR")
        nv, vv = financeiro.vencido(e, "PAGAR")
        saida.append(
            Kpi(
                "A pagar em aberto",
                specs.brl_curto(valor) if n else specs.TRAVESSAO,
                nota=(
                    f"{nv} vencido(s) · {specs.brl_curto(vv)}" if nv else "nada vencido"
                ),
                estado="ruim" if nv else "",
                estado_texto="Em atraso" if nv else "",
                url=reverse("finance:contas_a_pagar"),
            )
        )
        saldo = financeiro.fluxo(e).total.saldo_acumulado
        saida.append(
            Kpi(
                "Saldo projetado da safra",
                specs.brl_curto(saldo),
                nota="entradas − saídas, realizado e previsto",
                estado="ruim" if saldo < 0 else "",
                estado_texto="Negativo" if saldo < 0 else "",
            )
        )
    return saida


# --------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------


def grafico_rebanho_total(e: Escopo) -> specs.Grafico:
    serie = rebanho.serie_mensal(e)
    return specs.cartesiano(
        "geral-rebanho",
        "Rebanho no fim de cada mês",
        [specs.rotulo_do_mes(m) for m in serie.meses],
        [specs.serie("Cabeças", serie.total, tipo="area", cor="marca")],
        formato="cb",
        titulo_y="Cabeças",
        largura="dois-tercos",
        url=reverse("herd:posicao"),
    )


def grafico_dinheiro_por_mes(e: Escopo) -> specs.Grafico:
    compra, venda, custo = _fluxos_mensais(e)
    return specs.cartesiano(
        "geral-dinheiro",
        "Compras, vendas e custos por mês",
        [specs.rotulo_do_mes(m) for m in e.meses],
        [
            specs.serie("Compras", compra, cor=specs.COR_COMPRAS),
            specs.serie("Vendas", venda, cor=specs.COR_VENDAS),
            specs.serie("Custos", custo, cor=specs.COR_CUSTOS),
        ],
        formato="brl",
        titulo_y="R$",
        nota="Competência (a data do fato), não caixa: o caixa está na aba Financeiro.",
        largura="dois-tercos",
        altura=320,
    )


def grafico_resultado_acumulado(e: Escopo) -> specs.Grafico:
    compra, venda, custo = _fluxos_mensais(e)
    acumulado, total = [], ZERO
    for c, v, k in zip(compra, venda, custo, strict=True):
        total += v - c - k
        acumulado.append(total)
    return specs.cartesiano(
        "geral-acumulado",
        "Vendas − compras − custos, acumulado",
        [specs.rotulo_do_mes(m) for m in e.meses],
        [specs.serie("Acumulado", acumulado, tipo="line", cor="marca")],
        formato="brl",
        titulo_y="R$",
        nota="O quanto sobrou (ou faltou) mês a mês depois de comprar e custear. Ficar negativo na formação do rebanho é esperado.",
        largura="terco",
        altura=320,
    )


def _fluxos_mensais(e: Escopo):
    compra = [a.custo for a in compras.por_mes(e).values()]
    venda = [
        sum((v.total_value for v in vs), ZERO) for vs in vendas.por_mes(e).values()
    ]
    return compra, venda, custos.totais_por_mes(e)


def tabela_por_fazenda(e: Escopo) -> Tabela:
    saldos = rebanho.saldo_por_fazenda(e)
    lotes_ = rebanho.lotes_com_saldo(e)
    m = rebanho.mortalidade(e)
    dinheiro = e.ver_dinheiro
    comprado, vendido, custo = {}, {}, {}
    if dinheiro:
        for c in compras.lista_de_compras(e):
            comprado[c.destination_farm_id] = (
                comprado.get(c.destination_farm_id, ZERO) + c.animal_value
            )
        for v in vendas.lista_de_vendas(e):
            vendido[v.farm_id] = vendido.get(v.farm_id, ZERO) + v.total_value
        custo = {farm_id: valor for farm_id, _, valor in custos.por_fazenda(e)}
    colunas = ["Fazenda", "Cabeças", "Lotes"]
    if dinheiro:
        colunas += ["Comprado", "Vendido", "Custos", "Custo/cabeça"]
    colunas += ["Mortalidade"]
    linhas, marcas, cabecas = [], {}, []
    fazendas = e.fazendas()
    lotes_por_fazenda = Counter(lt.lote.farm_id for lt in lotes_)
    for i, f in enumerate(fazendas):
        cb = saldos.get(f.pk, 0)
        linha = [
            f.name,
            specs.formatar(cb),
            specs.formatar(lotes_por_fazenda[f.pk]),
        ]
        if dinheiro:
            linha += [
                specs.formatar(comprado.get(f.pk, ZERO), "brl"),
                specs.formatar(vendido.get(f.pk, ZERO), "brl"),
                specs.formatar(custo.get(f.pk, ZERO), "brl"),
                specs.formatar((custo.get(f.pk, ZERO) / cb) if cb else None, "brl"),
            ]
        taxa = m.por_fazenda[f].taxa
        linha.append(specs.formatar(taxa, "pct"))
        linhas.append(linha)
        cabecas.append(cb)
    t = Tabela(
        colunas,
        linhas,
        numericas=list(range(1, len(colunas))),
        titulo="Fazenda a fazenda",
        marcas=marcas,
        vazio="Nenhuma fazenda no recorte.",
    )
    t.barra(1, cabecas)
    return t


# --------------------------------------------------------------------------
# Aba
# --------------------------------------------------------------------------


def pendencias(e: Escopo):
    return painel_selectors.pendencias_do_painel(
        e.user, farm=e.farm, season=e.season, hoje=e.hoje
    )


def montar(e: Escopo) -> Painel:
    painel = Painel(kpis=kpis(e), kpis_titulo=f"Safra {e.season.name} em números")
    painel.insights = insights.gerar(e)
    if not rebanho.saldo_por_fazenda(e) and not (
        e.ver_dinheiro and compras.lista_de_compras(e)
    ):
        painel.vazio = (
            "Ainda não há lançamentos neste recorte. Quando houver compras, "
            "movimentações e vendas, o painel se preenche sozinho."
        )
    graficos_dinheiro = (
        [grafico_dinheiro_por_mes(e), grafico_resultado_acumulado(e)]
        if e.ver_dinheiro
        else []
    )
    secoes = [
        Secao(
            "Rebanho",
            [grafico_rebanho_total(e), rebanho.grafico_fluxo_por_tipo(e)],
        )
    ]
    if graficos_dinheiro:
        secoes.append(Secao("Dinheiro da safra", graficos_dinheiro))
        resultado = [vendas.grafico_cascata(e)]
        if e.ver_titulos:
            resultado.append(financeiro.grafico_fluxo(e))
            resultado[-1].largura = "metade"
        secoes.append(Secao("Resultado e caixa", resultado))
    if e.ver_ciclo and e.ver_dinheiro:
        secoes.append(
            Secao("Ciclo de compra", [ciclo.grafico_funil(e), ciclo.grafico_quebra(e)])
        )
    secoes.append(Secao("Por fazenda", [], tabelas=[tabela_por_fazenda(e)]))
    painel.secoes = secoes
    return painel
