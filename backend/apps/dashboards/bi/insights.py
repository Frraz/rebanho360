"""Leituras automáticas: o que um analista apontaria ao abrir o painel.

Cada regra olha **números que o sistema já calculou** (nunca recalcula) e
devolve uma frase específica, com o valor e o caminho para conferir — ou nada.
Os limiares são leitura, não regra de negócio (pendência #48): ficam todos aqui,
em constantes, e mudar um é mudar uma linha.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.urls import reverse

from apps.sales import carcass

from . import compras, custos, financeiro, lotes, specs, vendas
from .escopo import Escopo, somar_mes
from .specs import Insight

#: Preço de compra (custo/@) que subiu ou caiu mais que isto de um mês com
#: compra para o seguinte.
VARIACAO_DE_PRECO_PERCENTUAL = Decimal("10")
#: Vendedor com mais que isto do valor comprado.
CONCENTRACAO_PERCENTUAL = compras.CONCENTRACAO_ALERTA_PERCENTUAL
#: Custo por cabeça/dia que subiu mais que isto do mês anterior.
VARIACAO_DE_CUSTO_DIA_PERCENTUAL = Decimal("15")
#: Lote cujo GMD é menos que esta fração da média.
FRACAO_DO_GMD_MEDIO = Decimal("0.5")
#: Rendimento de carcaça que mudou mais que isto (p.p.) contra a safra anterior.
VARIACAO_DE_RENDIMENTO_PP = Decimal("1")

ORDEM = {"alerta": 0, "atencao": 1, "info": 2, "positivo": 3}


def _lotes_no_prejuizo(e: Escopo) -> Insight | None:
    if not e.ver_dinheiro:
        return None
    perdas = [
        r
        for r in vendas.resultados_dos_lotes(e)
        if r.resultado is not None and r.resultado < 0
    ]
    if not perdas:
        return None
    perdas.sort(key=lambda r: r.resultado)
    pior = perdas[0]
    return Insight(
        "alerta",
        f"{len(perdas)} lote(s) no prejuízo",
        f"O pior é {pior.lote.code}: {specs.formatar(pior.resultado, 'brl')}"
        + (
            f" (margem de {specs.formatar(pior.margem_por_arroba, 'brl')} por @)"
            if pior.margem_por_arroba is not None
            else ""
        )
        + ".",
        reverse("livestock:lote_detalhe", args=[pior.lote.pk]),
        "Abrir o lote",
    )


def _vencidos(e: Escopo) -> Insight | None:
    if not (e.ver_dinheiro and e.ver_titulos):
        return None
    n, valor = financeiro.vencido(e, "PAGAR")
    if not n:
        return None
    return Insight(
        "alerta",
        "Contas a pagar em atraso",
        f"{n} título(s) vencido(s), somando {specs.formatar(valor, 'brl')} em aberto.",
        reverse("finance:contas_a_pagar") + "?situacao=vencidos",
        "Ver títulos",
    )


def _concentracao_de_vendedor(e: Escopo) -> Insight | None:
    if not e.ver_dinheiro:
        return None
    ranking = compras.concentracao_de_vendedores(e)
    if len(ranking) < 2 or ranking[0][2] is None:
        return None
    nome, valor, parte = ranking[0]
    if parte <= CONCENTRACAO_PERCENTUAL:
        return None
    return Insight(
        "atencao",
        "Compras concentradas em um vendedor",
        f"{nome} responde por {specs.formatar(parte, 'pct')} do valor comprado "
        f"({specs.formatar(valor, 'brl')}). Mais de {specs.formatar(CONCENTRACAO_PERCENTUAL, 'pct')} "
        "num só fornecedor é risco de preço e de oferta.",
        reverse("purchases:lista"),
        "Ver compras",
    )


def _preco_de_compra(e: Escopo) -> Insight | None:
    if not e.ver_dinheiro:
        return None
    com_dado = [
        (m, a)
        for m, a in compras.por_mes(e).items()
        if a.cabecas_com_peso and a.custo_por_arroba
    ]
    if len(com_dado) < 2:
        return None
    (mes_a, a), (mes_b, b) = com_dado[-2], com_dado[-1]
    delta = specs.variacao(b.custo_por_arroba, a.custo_por_arroba, bom_quando=None)
    razao = (b.custo_por_arroba - a.custo_por_arroba) / a.custo_por_arroba * 100
    if abs(razao) < VARIACAO_DE_PRECO_PERCENTUAL:
        return None
    sobe = razao > 0
    return Insight(
        "atencao" if sobe else "info",
        "Preço de compra " + ("subiu" if sobe else "caiu"),
        f"O custo por @ de peso vivo foi de {specs.formatar(a.custo_por_arroba, 'brl')} em "
        f"{specs.rotulo_do_mes(mes_a)} para {specs.formatar(b.custo_por_arroba, 'brl')} em "
        f"{specs.rotulo_do_mes(mes_b)} ({delta.texto}). Confira se a mudança é preço ou "
        "mistura de categorias.",
        reverse("purchases:lista"),
        "Ver compras",
    )


def _custo_por_cabeca_dia(e: Escopo) -> Insight | None:
    if not e.ver_dinheiro:
        return None
    totais = custos.totais_por_mes(e)
    cabecas_dia = custos.cabecas_dia_por_mes(e)
    # O mês corrente está incompleto: lançamentos chegam depois, e o último
    # ponto parece queda. Só compara meses fechados.
    pares = [
        (m, c / cd)
        for m, c, cd in zip(e.meses, totais, cabecas_dia, strict=True)
        if cd and c and somar_mes(m) - datetime.timedelta(days=1) <= e.fim
    ]
    if len(pares) < 2:
        return None
    (ma, va), (mb, vb) = pares[-2], pares[-1]
    razao = (vb - va) / va * 100
    if razao < VARIACAO_DE_CUSTO_DIA_PERCENTUAL:
        return None
    return Insight(
        "atencao",
        "Custo por cabeça/dia subiu",
        f"De {specs.formatar(va, 'brl')} em {specs.rotulo_do_mes(ma)} para "
        f"{specs.formatar(vb, 'brl')} em {specs.rotulo_do_mes(mb)} "
        f"(+{specs.formatar(razao, 'pct')}). Veja o que pesou no mapa de centros de custo.",
        reverse("costs:lista"),
        "Ver custos",
    )


def _centro_dominante(e: Escopo) -> Insight | None:
    if not e.ver_dinheiro:
        return None
    nome, parte = custos.participacao_do_maior_centro(e)
    if parte is None or parte <= custos.CENTRO_DOMINANTE_PERCENTUAL:
        return None
    return Insight(
        "info",
        "Um centro concentra os custos",
        f"{nome} é {specs.formatar(parte, 'pct')} dos custos da safra "
        f"({specs.formatar(dict((n, v) for n, v, _ in custos.por_centro(e))[nome], 'brl')}).",
        reverse("costs:lista"),
        "Ver custos",
    )


def _gmd_baixo(e: Escopo) -> Insight | None:
    linhas = lotes.linhas_de_lotes(e)
    media = lotes.gmd_medio(linhas)
    if media is None:
        return None
    baixos = [
        lt
        for lt in linhas
        if lt.gmd is not None
        and not lt.encerrado
        and lt.gmd < media * FRACAO_DO_GMD_MEDIO
    ]
    if not baixos:
        return None
    baixos.sort(key=lambda lt: lt.gmd)
    pior = baixos[0]
    return Insight(
        "atencao",
        "Lote ganhando pouco peso",
        f"{pior.lote.code} ganha {specs.formatar(pior.gmd, 'kgdia')}, menos da metade da média "
        f"({specs.formatar(media, 'kgdia')})"
        + (
            f"; mais {len(baixos) - 1} lote(s) na mesma situação"
            if len(baixos) > 1
            else ""
        )
        + ".",
        reverse("livestock:lote_detalhe", args=[pior.lote.pk]),
        "Abrir o lote",
    )


def _rendimento(e: Escopo) -> Insight | None:
    if not (e.ver_dinheiro and e.anterior):
        return None
    atual = vendas.agregado(
        [v for v in vendas.abates(e) if v.carcass_weight_kg]
    ).indicadores.rendimento
    anterior_abates = [
        v for v in e.anterior.vendas().filter(type="ABATE") if v.carcass_weight_kg
    ]
    anterior = carcass.agregar(anterior_abates).indicadores.rendimento
    if atual is None or anterior is None:
        return None
    d = atual - anterior
    if abs(d) < VARIACAO_DE_RENDIMENTO_PP:
        return None
    melhorou = d > 0
    return Insight(
        "positivo" if melhorou else "atencao",
        "Rendimento de carcaça " + ("melhorou" if melhorou else "piorou"),
        f"{specs.formatar(atual, 'pct2')} nos abates da safra, contra "
        f"{specs.formatar(anterior, 'pct2')} na anterior no mesmo ponto "
        f"({'+' if melhorou else '−'}{specs.formatar(abs(d), 'num1')} p.p.).",
        reverse("sales:lista"),
        "Ver vendas",
    )


def _margem_positiva(e: Escopo) -> Insight | None:
    if not e.ver_dinheiro:
        return None
    r = vendas.resultado_da_safra(e)
    if not r.lotes_com_resultado or r.resultado <= 0:
        return None
    return Insight(
        "positivo",
        "Safra no lucro até aqui",
        f"Os {r.lotes_com_resultado} lote(s) com resultado somam {specs.formatar(r.resultado, 'brl')}"
        + (
            f", uma margem de {specs.formatar(r.margem_por_arroba, 'brl')} por @"
            if r.margem_por_arroba is not None
            else ""
        )
        + ".",
        reverse("sales:lista"),
        "Ver vendas",
    )


REGRAS = (
    _lotes_no_prejuizo,
    _vencidos,
    _concentracao_de_vendedor,
    _preco_de_compra,
    _custo_por_cabeca_dia,
    _gmd_baixo,
    _centro_dominante,
    _rendimento,
    _margem_positiva,
)


def gerar(e: Escopo, *, limite: int = 8) -> list[Insight]:
    """Do mais grave para o menos. Sem nada a dizer, devolve lista vazia — a tela
    diz que está tudo dentro do esperado em vez de inventar um aviso."""
    achados = [i for regra in REGRAS if (i := regra(e)) is not None]
    achados.sort(key=lambda i: ORDEM[i.nivel])
    return achados[:limite]
