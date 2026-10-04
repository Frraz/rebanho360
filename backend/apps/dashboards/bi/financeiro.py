"""Aba **Financeiro** — o que se deve, o que se tem a receber e quando.

Posição de contas = títulos em aberto de **todas as safras** (dívida não tem
safra); fluxo de caixa = o serviço `fluxo_de_caixa` da safra escolhida. Só quem
pode ver títulos chega aqui (`pode_ver_titulos`).
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal

from django.urls import reverse

from apps.finance import selectors as financeiro
from apps.finance.models import (
    SITUACOES_EM_ABERTO,
    Component,
    Direction,
    PaymentMethod,
    PaymentStatus,
)

from . import custos, specs
from .escopo import Escopo
from .specs import Kpi, Painel, Secao, Tabela

ZERO = Decimal("0")

#: Faixas de vencimento, em ordem de tempo (ordinal: matiz única). Cada uma é
#: `(rótulo, dias mínimo, dias máximo)` contados do vencimento até hoje; negativo
#: = ainda não venceu.
FAIXAS = (
    ("Vencido há mais de 30 dias", None, -31),
    ("Vencido há até 30 dias", -30, -1),
    ("Vence hoje", 0, 0),
    ("Vence em 1 a 7 dias", 1, 7),
    ("Vence em 8 a 30 dias", 8, 30),
    ("Vence em 31 a 60 dias", 31, 60),
    ("Vence em mais de 60 dias", 61, None),
)


def _abertos(e: Escopo, direcao: str, *, so_com_saldo: bool = True):
    return financeiro.titulos_em_aberto_com_saldo(
        e.user, farm=e.farm, direction=direcao, so_com_saldo=so_com_saldo
    )


def por_vencimento(e: Escopo, direcao: str) -> list[tuple]:
    """`[(vencimento, quantidade, saldo)]` dos títulos com saldo a pagar/receber,
    no escopo do usuário. A soma é do banco, um grupo por dia de vencimento: o
    painel não carrega cada título para somar, então não depende de quantos há."""

    def calcular():
        return [
            (g["due_date"], g["quantidade"], g["total"])
            for g in financeiro.saldo_agrupado(_abertos(e, direcao), "due_date")
        ]

    return e.memo(f"abertos:{direcao}", calcular)


def faixa_do_titulo(vencimento: datetime.date, hoje: datetime.date) -> int:
    dias = (vencimento - hoje).days
    for i, (_, de, ate) in enumerate(FAIXAS):
        if (de is None or dias >= de) and (ate is None or dias <= ate):
            return i
    return len(FAIXAS) - 1


def por_faixa(e: Escopo, direcao: str) -> list[Decimal]:
    saldos = [ZERO] * len(FAIXAS)
    for vencimento, _, saldo in por_vencimento(e, direcao):
        saldos[faixa_do_titulo(vencimento, e.hoje)] += saldo
    return saldos


def _soma(grupos) -> tuple[int, Decimal]:
    grupos = list(grupos)
    return sum(q for _, q, _ in grupos), sum((v for _, _, v in grupos), ZERO)


def vencido(e: Escopo, direcao: str) -> tuple[int, Decimal]:
    return _soma(g for g in por_vencimento(e, direcao) if g[0] < e.hoje)


def total_em_aberto(e: Escopo, direcao: str) -> tuple[int, Decimal]:
    return _soma(por_vencimento(e, direcao))


def proximos_7_dias(e: Escopo, direcao: str) -> tuple[int, Decimal]:
    fim = e.hoje + datetime.timedelta(days=6)
    return _soma(g for g in por_vencimento(e, direcao) if e.hoje <= g[0] <= fim)


def fluxo(e: Escopo):
    return e.memo(
        "fluxo_de_caixa",
        lambda: financeiro.fluxo_de_caixa(
            e.user, season=e.season, farm=e.farm, hoje=e.hoje
        ),
    )


# --------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------


def kpis(e: Escopo) -> list[Kpi]:
    n_pagar, v_pagar = total_em_aberto(e, Direction.PAGAR)
    n_venc, v_venc = vencido(e, Direction.PAGAR)
    n_7, v_7 = proximos_7_dias(e, Direction.PAGAR)
    n_rec, v_rec = total_em_aberto(e, Direction.RECEBER)
    n_vrec, v_vrec = vencido(e, Direction.RECEBER)
    f = fluxo(e)
    pago = f.total.saidas_realizadas
    recebido = f.total.entradas_realizadas
    return [
        Kpi(
            "A pagar em aberto",
            specs.brl_curto(v_pagar) if n_pagar else specs.TRAVESSAO,
            nota=f"{n_pagar} título(s) · todas as safras",
            url=reverse("finance:contas_a_pagar"),
            destaque=True,
        ),
        Kpi(
            "Vencido a pagar",
            specs.brl_curto(v_venc) if n_venc else specs.formatar(ZERO, "brl"),
            nota=f"{n_venc} título(s) vencido(s)",
            estado="ruim" if n_venc else "bom",
            estado_texto="Em atraso" if n_venc else "Nada em atraso",
            url=(
                reverse("finance:contas_a_pagar") + "?situacao=vencidos"
                if n_venc
                else ""
            ),
        ),
        Kpi(
            "Vence nos próximos 7 dias",
            specs.brl_curto(v_7) if n_7 else specs.formatar(ZERO, "brl"),
            nota=f"{n_7} título(s)",
        ),
        Kpi(
            "A receber em aberto",
            specs.brl_curto(v_rec) if n_rec else specs.TRAVESSAO,
            nota=f"{n_rec} título(s)",
            url=reverse("finance:contas_a_receber"),
        ),
        Kpi(
            "Vencido a receber",
            specs.brl_curto(v_vrec) if n_vrec else specs.formatar(ZERO, "brl"),
            nota=f"{n_vrec} título(s)",
            estado="atencao" if n_vrec else "bom",
            estado_texto="Cobrar" if n_vrec else "Nada em atraso",
        ),
        Kpi(
            "Pago na safra",
            specs.brl_curto(pago),
            nota="baixas de títulos a pagar",
            url=reverse("finance:pagamento_lista"),
        ),
        Kpi(
            "Recebido na safra",
            specs.brl_curto(recebido),
            nota="baixas de títulos a receber",
        ),
        Kpi(
            "Saldo projetado da safra",
            specs.brl_curto(f.total.saldo_acumulado),
            nota="entradas − saídas, realizado e previsto",
            estado="ruim" if f.total.saldo_acumulado < 0 else "",
            estado_texto="Negativo" if f.total.saldo_acumulado < 0 else "",
            ajuda="O sistema não tem saldo bancário inicial: o acumulado parte de zero.",
        ),
    ]


# --------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------


def grafico_aging(e: Escopo) -> specs.Grafico:
    return specs.cartesiano(
        "fin-aging",
        "Quando vence o que está em aberto",
        [r for r, _, _ in FAIXAS],
        [
            specs.serie("A pagar", por_faixa(e, Direction.PAGAR), cor=specs.COR_CUSTOS),
            specs.serie(
                "A receber", por_faixa(e, Direction.RECEBER), cor=specs.COR_VENDAS
            ),
        ],
        formato="brl",
        titulo_y="R$ em aberto",
        nota="Saldo (valor − baixas) de cada título pela distância entre o vencimento e hoje. As duas primeiras faixas já venceram.",
        largura="metade",
        url=reverse("finance:contas_a_pagar"),
    )


def grafico_fluxo(e: Escopo) -> specs.Grafico:
    f = fluxo(e)
    linhas = f.linhas
    x = [specs.rotulo_do_mes(lt.mes) if lt.mes else lt.rotulo for lt in linhas]
    return specs.cartesiano(
        "fin-fluxo",
        "Fluxo de caixa da safra",
        x,
        [
            specs.serie(
                "Entradas realizadas",
                [lt.entradas_realizadas for lt in linhas],
                pilha="e",
                cor=specs.COR_VENDAS,
            ),
            specs.serie(
                "Entradas previstas",
                [lt.entradas_previstas for lt in linhas],
                pilha="e",
                cor=specs.COR_VENDAS,
                previsto=True,
            ),
            specs.serie(
                "Saídas realizadas",
                [-lt.saidas_realizadas for lt in linhas],
                pilha="s",
                cor=specs.COR_CUSTOS,
            ),
            specs.serie(
                "Saídas previstas",
                [-lt.saidas_previstas for lt in linhas],
                pilha="s",
                cor=specs.COR_CUSTOS,
                previsto=True,
            ),
            specs.serie(
                "Saldo acumulado",
                [lt.saldo_acumulado for lt in linhas],
                tipo="line",
                cor="marca",
            ),
        ],
        formato="brl",
        titulo_y="R$",
        nota=(
            "Entradas para cima, saídas para baixo; hachurado = previsto (o que falta dos títulos em aberto, "
            "no mês do vencimento). O saldo acumulado parte de zero: não há saldo bancário no sistema."
        ),
        largura="cheia",
        altura=340,
        url=reverse("finance:contas_a_pagar"),
    )


def grafico_pipeline(e: Escopo) -> specs.Grafico:
    grupos = {
        g["payment_status"]: g
        for g in financeiro.saldo_agrupado(
            _abertos(e, Direction.PAGAR, so_com_saldo=False), "payment_status"
        )
    }
    etapas = []
    for situacao in SITUACOES_EM_ABERTO:
        g = grupos.get(situacao, {"total": ZERO, "quantidade": 0})
        etapas.append(
            (
                PaymentStatus(situacao).label,
                g["total"],
                f"{g['quantidade']} título(s)",
            )
        )
    return specs.funil(
        "fin-pipeline",
        "A pagar: em que etapa está cada real",
        etapas,
        formato="brl",
        nota="Do título lançado ao pago em parte: o que ainda precisa de programação ou aprovação.",
        largura="metade",
    )


def grafico_por_tipo(e: Escopo) -> specs.Grafico:
    soma = defaultdict(lambda: ZERO)
    for g in financeiro.saldo_agrupado(_abertos(e, Direction.PAGAR), "component"):
        soma[Component(g["component"]).label] += g["total"]
    cores = {
        Component.ANIMAIS.label: specs.COR_COMPRAS,
        Component.FRETE.label: specs.COR_CUSTOS,
        Component.COMISSAO.label: specs.COR_ALERTA,
        Component.IMPOSTOS.label: 4,
    }
    return specs.rosca(
        "fin-tipo",
        "A pagar por tipo",
        [(n, v, cores.get(n, "neutro")) for n, v in soma.items()],
        formato="brl",
        centro_rotulo="em aberto",
        largura="terco",
    )


def _por_pessoa(e: Escopo, direcao: str, sem_nome: str) -> list[tuple]:
    soma = defaultdict(lambda: ZERO)
    for g in financeiro.saldo_agrupado(_abertos(e, direcao), "payee__name"):
        soma[g["payee__name"] if g["payee__name"] is not None else sem_nome] += g[
            "total"
        ]
    return list(soma.items())


def grafico_favorecidos(e: Escopo) -> specs.Grafico:
    return specs.ranking(
        "fin-favorecidos",
        "A quem se deve mais",
        _por_pessoa(e, Direction.PAGAR, "Sem favorecido definido"),
        formato="brl",
        nome_serie="Em aberto",
        largura="terco",
        url=reverse("finance:contas_a_pagar"),
    )


def grafico_clientes(e: Escopo) -> specs.Grafico:
    return specs.ranking(
        "fin-clientes",
        "Quem deve mais",
        _por_pessoa(e, Direction.RECEBER, "Sem cliente definido"),
        formato="brl",
        nome_serie="Em aberto",
        largura="terco",
        url=reverse("finance:contas_a_receber"),
    )


def grafico_calendario(e: Escopo) -> specs.Grafico:
    fim = e.hoje + datetime.timedelta(days=180)
    dias = defaultdict(lambda: ZERO)
    for vencimento, _, saldo in por_vencimento(e, Direction.PAGAR):
        if e.hoje <= vencimento <= fim:
            dias[vencimento] += saldo
    return specs.calendario(
        "fin-calendario",
        "Vencimentos a pagar nos próximos 6 meses",
        e.hoje,
        fim,
        dict(dias),
        formato="brl",
        nota="Cada quadrado é um dia; mais escuro = mais dinheiro vencendo. Atrasados estão na faixa de vencimento acima.",
    )


def grafico_pagamentos_por_metodo(e: Escopo) -> specs.Grafico:
    meses = e.meses
    indice = {m: i for i, m in enumerate(meses)}
    por_metodo = defaultdict(lambda: [ZERO] * len(meses))
    for p in financeiro.pagamentos_para(
        e.user, farm=e.farm, direction=Direction.PAGAR, de=e.inicio, ate=e.fim
    ):
        m = p.date.replace(day=1)
        if m in indice:
            por_metodo[p.get_method_display()][indice[m]] += p.amount
    cores = {PaymentMethod(m).label: i for i, m in enumerate(PaymentMethod.values)}
    return specs.cartesiano(
        "fin-metodos",
        "Pagamentos por mês e forma de pagamento",
        [specs.rotulo_do_mes(m) for m in meses],
        [
            specs.serie(nome, dados, pilha="metodos", cor=cores.get(nome, 5))
            for nome, dados in sorted(por_metodo.items())
        ],
        formato="brl",
        titulo_y="R$ pagos",
        largura="metade",
        url=reverse("finance:pagamento_lista"),
    )


def tabela_proximos_vencimentos(e: Escopo) -> Tabela:
    # Só os dez que a tabela mostra, escolhidos pelo banco.
    abertos = list(
        _abertos(e, Direction.PAGAR)
        .select_related("payee")
        .order_by("due_date", "pk")[:10]
    )
    linhas, links, marcas, saldos = [], [], {}, []
    for i, t in enumerate(abertos):
        atrasado = t.due_date < e.hoje
        linhas.append(
            [
                t.code,
                t.payee.name if t.payee_id else "—",
                t.get_component_display(),
                f"{t.due_date:%d/%m/%Y}",
                specs.formatar(t.saldo, "brl"),
                t.get_payment_status_display(),
            ]
        )
        links.append(reverse("finance:titulo_detalhe", args=[t.pk]))
        saldos.append(t.saldo)
        if atrasado:
            marcas[(i, 3)] = ("ruim", f"vencido há {(e.hoje - t.due_date).days} dia(s)")
    tabela = Tabela(
        ["Título", "Favorecido", "Tipo", "Vencimento", "Saldo", "Situação"],
        linhas,
        numericas=[4],
        titulo="Dez próximos vencimentos a pagar",
        links=links,
        marcas=marcas,
        codigo=0,
        vazio="Nenhum título a pagar em aberto.",
    )
    tabela.barra(4, saldos)
    return tabela


# --------------------------------------------------------------------------
# Aba
# --------------------------------------------------------------------------


# Despesa = lançamento de custo confirmado da safra, o mesmo da aba Custos e do
# cartão da safra: os números batem (regra 6). Fica de fora a compra de animais,
# que a aba Compras já mostra como investimento.
NOTA_DAS_DESPESAS = (
    "Lançamentos de custo confirmados da safra, fora a compra de animais."
)


def grafico_despesas_por_centro(e: Escopo) -> specs.Grafico:
    return specs.ranking(
        "fin-despesas-centro",
        "Despesas por centro de custo",
        [(nome, valor) for nome, valor, _ in custos.por_centro(e)],
        formato="brl",
        nome_serie="Despesa",
        limite=12,
        largura="metade",
        url=reverse("costs:lista"),
        nota=NOTA_DAS_DESPESAS,
    )


def grafico_despesas_por_mes(e: Escopo) -> specs.Grafico:
    return specs.cartesiano(
        "fin-despesas-mes",
        "Despesas por mês",
        [specs.rotulo_do_mes(m) for m in e.meses],
        [specs.serie("Despesas", custos.totais_por_mes(e), cor=specs.COR_CUSTOS)],
        formato="brl",
        titulo_y="R$",
        largura="metade",
        url=reverse("costs:lista"),
        nota=NOTA_DAS_DESPESAS,
    )


def montar(e: Escopo) -> Painel:
    painel = Painel(kpis=kpis(e), kpis_titulo="Contas e caixa")
    total = fluxo(e).total
    sem_movimento = not any(
        (
            total.entradas_realizadas,
            total.entradas_previstas,
            total.saidas_realizadas,
            total.saidas_previstas,
        )
    )
    if (
        not por_vencimento(e, Direction.PAGAR)
        and not por_vencimento(e, Direction.RECEBER)
        and sem_movimento
        and not custos.total(e)
    ):
        painel.vazio = "Nenhum título lançado ainda."
    n_sem = financeiro.contar_operacoes_sem_titulo(e.user)
    if n_sem:
        painel.avisos.append(
            f"{n_sem} compra(s) ou venda(s) confirmada(s) ainda sem título: o dinheiro delas não aparece aqui."
        )
    painel.secoes = [
        Secao("Caixa", [grafico_fluxo(e)]),
        Secao(
            "Despesas",
            [grafico_despesas_por_centro(e), grafico_despesas_por_mes(e)],
            descricao="Os lançamentos de custo da safra, por competência (a data do fato).",
        ),
        Secao("Contas em aberto", [grafico_aging(e), grafico_pipeline(e)]),
        Secao(
            "Com quem",
            [grafico_por_tipo(e), grafico_favorecidos(e), grafico_clientes(e)],
        ),
        Secao(
            "Calendário",
            [grafico_calendario(e), grafico_pagamentos_por_metodo(e)],
            tabelas=[tabela_proximos_vencimentos(e)],
        ),
    ]
    return painel
