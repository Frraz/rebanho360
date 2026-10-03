"""Leitura. Contas a pagar, fluxo de caixa, mapa financeiro.

Toda listagem passa por `for_user()` — nunca `.all()` (regra 4). Pago, a
pagar e vencido **não são campos**: saem das baixas e do vencimento, aqui, uma
vez só — a tela, o relatório e o painel consomem as mesmas funções (regra 6).
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.urls import reverse

from apps.core.exceptions import Bloqueio
from apps.core.formatting import dinheiro_br
from apps.core.reversible import Status
from apps.finance.models import (
    SITUACOES_EM_ABERTO,
    Direction,
    Invoice,
    Payment,
    PaymentStatus,
)

ZERO = Decimal("0")
DIAS_DA_SEMANA = 7


# --------------------------------------------------------------------------
# Listagens
# --------------------------------------------------------------------------


def listar_titulos_para(
    user,
    *,
    season=None,
    farm=None,
    direction=None,
    situacao: str = "",
    payee=None,
    de: datetime.date | None = None,
    ate: datetime.date | None = None,
    incluir_cancelados: bool = False,
):
    """Títulos no escopo do usuário, com o total baixado já somado (`paid_sum`).

    `situacao`: `""`/`"abertos"` (em aberto), `"todos"` ou um código de
    `PaymentStatus`. `"vencidos"` é derivado do vencimento, não de um estado.
    `de`/`ate` filtram o **vencimento**."""
    qs = (
        Invoice.objects.for_user(user)
        .select_related(
            "payee",
            "bank_account",
            "farm",
            "season",
            "origin_purchase",
            "origin_sale",
        )
        .annotate(
            paid_sum=Sum(
                "payments__amount", filter=Q(payments__status=Status.CONFIRMADA)
            )
        )
    )
    if not incluir_cancelados:
        qs = qs.filter(status=Status.CONFIRMADA)
    if season is not None:
        qs = qs.filter(season=season)
    if farm is not None:
        qs = qs.filter(farm=farm)
    if direction:
        qs = qs.filter(direction=direction)
    if payee is not None:
        qs = qs.filter(payee=payee)
    if de is not None:
        qs = qs.filter(due_date__gte=de)
    if ate is not None:
        qs = qs.filter(due_date__lte=ate)

    if situacao in ("", "abertos"):
        qs = qs.filter(payment_status__in=SITUACOES_EM_ABERTO)
    elif situacao == "vencidos":
        qs = qs.filter(
            payment_status__in=SITUACOES_EM_ABERTO, due_date__lt=datetime.date.today()
        )
    elif situacao != "todos":
        qs = qs.filter(payment_status=situacao)
    return qs.order_by("due_date", "id")


def pagamentos_para(
    user,
    *,
    farm=None,
    direction=None,
    de: datetime.date | None = None,
    ate: datetime.date | None = None,
    incluir_desfeitos: bool = False,
):
    qs = Payment.objects.for_user(user).select_related(
        "invoice", "invoice__payee", "invoice__farm"
    )
    if not incluir_desfeitos:
        qs = qs.filter(status=Status.CONFIRMADA)
    if farm is not None:
        qs = qs.filter(invoice__farm=farm)
    if direction:
        qs = qs.filter(invoice__direction=direction)
    if de is not None:
        qs = qs.filter(date__gte=de)
    if ate is not None:
        qs = qs.filter(date__lte=ate)
    return qs.order_by("-date", "-id")


def operacoes_sem_titulo(user):
    """Compras e vendas confirmadas que nunca passaram pelo financeiro — as
    do histórico, importadas antes da Fase 4. Gerar o título é decisão de
    quem conhece o caso (muitas já foram pagas fora do sistema)."""
    from apps.purchases.models import Purchase
    from apps.sales.models import Sale

    compras = (
        Purchase.objects.for_user(user)
        .filter(status=Status.CONFIRMADA)
        .annotate(n_titulos=Count("invoices"))
        .filter(n_titulos=0)
        .select_related("seller", "destination_farm")
        .order_by("-date", "-id")
    )
    vendas = (
        Sale.objects.for_user(user)
        .filter(status=Status.CONFIRMADA)
        .annotate(n_titulos=Count("invoices"))
        .filter(n_titulos=0)
        .select_related("buyer", "farm")
        .order_by("-date", "-id")
    )
    return list(compras), list(vendas)


# --------------------------------------------------------------------------
# Resumo de vencimentos — "o que vence esta semana e quanto"
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FaixaDeVencimento:
    rotulo: str
    quantidade: int = 0
    valor: Decimal = ZERO


@dataclass(frozen=True)
class ResumoDeVencimentos:
    vencidos: FaixaDeVencimento
    hoje: FaixaDeVencimento
    proximos_7_dias: FaixaDeVencimento
    depois: FaixaDeVencimento
    em_aberto: FaixaDeVencimento


def _saldo_em_aberto(titulo) -> Decimal:
    return titulo.amount - Decimal(titulo.paid_sum or 0)


def resumir_vencimentos(titulos, *, hoje: datetime.date | None = None):
    """Soma o que **falta** (valor − baixado) por faixa de vencimento.
    `titulos` já deve ser uma lista de títulos em aberto, anotada com
    `paid_sum` (`listar_titulos_para`)."""
    hoje = hoje or datetime.date.today()
    fim = hoje + datetime.timedelta(days=DIAS_DA_SEMANA - 1)
    soma = defaultdict(lambda: [0, ZERO])
    for titulo in titulos:
        if titulo.payment_status not in SITUACOES_EM_ABERTO:
            continue
        saldo = _saldo_em_aberto(titulo)
        if titulo.due_date < hoje:
            faixa = "vencidos"
        elif titulo.due_date == hoje:
            faixa = "hoje"
        elif titulo.due_date <= fim:
            faixa = "semana"
        else:
            faixa = "depois"
        for chave in (faixa, "total"):
            soma[chave][0] += 1
            soma[chave][1] += saldo
    return ResumoDeVencimentos(
        vencidos=FaixaDeVencimento("Vencidos", *soma["vencidos"]),
        hoje=FaixaDeVencimento("Vencem hoje", *soma["hoje"]),
        proximos_7_dias=FaixaDeVencimento("Nos próximos 7 dias", *soma["semana"]),
        depois=FaixaDeVencimento("Depois disso", *soma["depois"]),
        em_aberto=FaixaDeVencimento("Em aberto", *soma["total"]),
    )


# --------------------------------------------------------------------------
# O que bloqueia a montante (F4-05)
# --------------------------------------------------------------------------


def _link_da_baixa(baixa) -> tuple[str, str]:
    return reverse("finance:pagamento_detalhe", args=[baixa.pk]), (
        "Ir para o recebimento" if baixa.a_receber else "Ir para o pagamento"
    )


def bloqueios_financeiros_da_compra(compra) -> list[Bloqueio]:
    """Baixa existente bloqueia editar/excluir a compra e a venda do lote
    dela: o dinheiro saiu de verdade, e desfazer aqui não o devolve. A
    mensagem diz o caminho — "desfaça antes a baixa" — com o link."""
    bloqueios = []
    baixas = Payment.objects.filter(
        status=Status.CONFIRMADA, invoice__origin_purchase=compra
    ).select_related("invoice")
    for baixa in baixas.order_by("date", "id"):
        url, rotulo = _link_da_baixa(baixa)
        bloqueios.append(
            Bloqueio(
                f"o título {baixa.invoice.code} desta compra já tem pagamento "
                f"baixado em {baixa.date:%d/%m/%Y} ({dinheiro_br(baixa.amount)}). "
                f"Para prosseguir, desfaça antes a baixa do pagamento {baixa.code}.",
                url,
                rotulo,
            )
        )

    lote = compra.lot
    if lote is not None and lote.origin_purchase_id == compra.pk:
        das_vendas = Payment.objects.filter(
            status=Status.CONFIRMADA,
            invoice__origin_sale__lot=lote,
            invoice__origin_sale__status=Status.CONFIRMADA,
        ).select_related("invoice", "invoice__origin_sale")
        for baixa in das_vendas.order_by("date", "id"):
            venda = baixa.invoice.origin_sale
            url, rotulo = _link_da_baixa(baixa)
            bloqueios.append(
                Bloqueio(
                    f"o lote {lote.code} foi vendido na {venda.code}, e o pagamento "
                    f"dessa venda já foi baixado em {baixa.date:%d/%m/%Y}. "
                    f"Para prosseguir, desfaça antes a baixa do pagamento {baixa.code}.",
                    url,
                    rotulo,
                )
            )
    return bloqueios


def bloqueios_financeiros_da_venda(venda) -> list[Bloqueio]:
    bloqueios = []
    baixas = Payment.objects.filter(
        status=Status.CONFIRMADA, invoice__origin_sale=venda
    ).select_related("invoice")
    for baixa in baixas.order_by("date", "id"):
        url, rotulo = _link_da_baixa(baixa)
        bloqueios.append(
            Bloqueio(
                f"o título {baixa.invoice.code} desta venda já tem recebimento "
                f"baixado em {baixa.date:%d/%m/%Y} ({dinheiro_br(baixa.amount)}). "
                f"Para prosseguir, desfaça antes a baixa do pagamento {baixa.code}.",
                url,
                rotulo,
            )
        )
    return bloqueios


# --------------------------------------------------------------------------
# Fluxo de caixa projetado (F4-07)
# --------------------------------------------------------------------------


@dataclass
class LinhaDoFluxo:
    rotulo: str
    mes: datetime.date | None = None
    entradas_realizadas: Decimal = ZERO
    entradas_previstas: Decimal = ZERO
    saidas_realizadas: Decimal = ZERO
    saidas_previstas: Decimal = ZERO
    saldo_do_mes: Decimal = ZERO
    saldo_acumulado: Decimal = ZERO


@dataclass
class FluxoDeCaixa:
    linhas: list[LinhaDoFluxo] = field(default_factory=list)
    total: LinhaDoFluxo = field(default_factory=lambda: LinhaDoFluxo("Total"))
    vencido_nao_pago: Decimal = ZERO  # a pagar
    vencido_a_receber: Decimal = ZERO


def _primeiro_dia(data: datetime.date) -> datetime.date:
    return data.replace(day=1)


def _meses(inicio: datetime.date, fim: datetime.date) -> list[datetime.date]:
    meses, atual = [], _primeiro_dia(inicio)
    while atual <= fim:
        meses.append(atual)
        atual = (atual + datetime.timedelta(days=32)).replace(day=1)
    return meses


NOMES_DOS_MESES = (
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
)


def rotulo_do_mes(mes: datetime.date) -> str:
    return f"{NOMES_DOS_MESES[mes.month - 1]}/{mes.year}"


def fluxo_de_caixa(
    user, *, season, farm=None, hoje: datetime.date | None = None
) -> FluxoDeCaixa:
    """Entradas previstas de venda contra saídas previstas de título, mês a
    mês da safra, com o **realizado separado do previsto**.

    - Previsto = o que **falta** (valor − baixado) dos títulos em aberto, no mês
      do vencimento. Vencido e não pago fica no mês em que venceu — e é somado
      em `vencido_nao_pago` (a pagar) e `vencido_a_receber`, porque o caixa real
      de hoje não o terá mais naquele mês.
    - Realizado = as baixas, no mês da data do pagamento.
    - Fora da safra, o que existe cai em "Antes da safra" e "Depois da safra".
    Não há saldo bancário inicial no sistema: o saldo acumulado parte de zero."""
    hoje = hoje or datetime.date.today()
    inicio, fim = season.start_date, season.end_date
    meses = _meses(inicio, fim)
    por_mes = {m: LinhaDoFluxo(rotulo_do_mes(m), m) for m in meses}
    antes, depois = LinhaDoFluxo("Antes da safra"), LinhaDoFluxo("Depois da safra")

    def linha_de(data: datetime.date) -> LinhaDoFluxo:
        if data < inicio:
            return antes
        if data > fim:
            return depois
        return por_mes[_primeiro_dia(data)]

    resultado = FluxoDeCaixa()
    abertos = listar_titulos_para(user, farm=farm, situacao="abertos")
    for titulo in abertos:
        saldo = _saldo_em_aberto(titulo)
        if saldo <= 0:
            continue
        linha = linha_de(titulo.due_date)
        a_receber = titulo.direction == Direction.RECEBER
        if a_receber:
            linha.entradas_previstas += saldo
        else:
            linha.saidas_previstas += saldo
        if titulo.due_date < hoje:
            if a_receber:
                resultado.vencido_a_receber += saldo
            else:
                resultado.vencido_nao_pago += saldo

    for baixa in pagamentos_para(user, farm=farm):
        linha = linha_de(baixa.date)
        if baixa.invoice.direction == Direction.RECEBER:
            linha.entradas_realizadas += baixa.amount
        else:
            linha.saidas_realizadas += baixa.amount

    ordem = [antes, *por_mes.values(), depois]
    acumulado = ZERO
    for linha in ordem:
        linha.saldo_do_mes = (
            linha.entradas_realizadas
            + linha.entradas_previstas
            - linha.saidas_realizadas
            - linha.saidas_previstas
        )
        acumulado += linha.saldo_do_mes
        linha.saldo_acumulado = acumulado
        for campo in (
            "entradas_realizadas",
            "entradas_previstas",
            "saidas_realizadas",
            "saidas_previstas",
            "saldo_do_mes",
        ):
            setattr(
                resultado.total,
                campo,
                getattr(resultado.total, campo) + getattr(linha, campo),
            )
    resultado.total.saldo_acumulado = acumulado
    # "Antes"/"Depois" só aparecem se houver algo — linha zerada é ruído.
    resultado.linhas = [
        linha
        for linha in ordem
        if linha.mes is not None
        or any(
            (
                linha.entradas_realizadas,
                linha.entradas_previstas,
                linha.saidas_realizadas,
                linha.saidas_previstas,
            )
        )
    ]
    return resultado


# --------------------------------------------------------------------------
# Mapa financeiro (F4-08)
# --------------------------------------------------------------------------


@dataclass
class LinhaDoMapa:
    rotulo: str
    titulos: int = 0
    total: Decimal = ZERO
    pago: Decimal = ZERO
    a_pagar: Decimal = ZERO
    vencido: Decimal = ZERO


def _agrupar(titulos, chave, hoje) -> list[LinhaDoMapa]:
    grupos: dict[str, LinhaDoMapa] = {}
    for titulo in titulos:
        rotulo = chave(titulo)
        linha = grupos.setdefault(rotulo, LinhaDoMapa(rotulo))
        pago = Decimal(titulo.paid_sum or 0)
        saldo = titulo.amount - pago
        linha.titulos += 1
        linha.total += titulo.amount
        linha.pago += pago
        if saldo > 0:
            if titulo.due_date < hoje:
                linha.vencido += saldo
            else:
                linha.a_pagar += saldo
    return sorted(grupos.values(), key=lambda g: (-g.total, g.rotulo))


def mapa_financeiro(
    user, *, farm=None, direction=Direction.PAGAR, hoje: datetime.date | None = None
) -> dict[str, list[LinhaDoMapa]]:
    """Consolidado por favorecido, por tipo e por safra: total, pago, a pagar e
    vencido — o que hoje exige cruzar três abas. Só título ativo conta."""
    hoje = hoje or datetime.date.today()
    titulos = list(
        listar_titulos_para(user, farm=farm, direction=direction, situacao="todos")
    )
    return {
        "favorecido": _agrupar(
            titulos,
            lambda t: t.payee.name if t.payee_id else "Sem favorecido definido",
            hoje,
        ),
        "tipo": _agrupar(titulos, lambda t: t.get_component_display(), hoje),
        "safra": _agrupar(titulos, lambda t: t.season.name, hoje),
    }


# --------------------------------------------------------------------------
# Painel
# --------------------------------------------------------------------------


def titulos_vencidos(user, *, farm=None, hoje: datetime.date | None = None):
    """Títulos a pagar vencidos e ainda em aberto, no escopo do usuário."""
    hoje = hoje or datetime.date.today()
    return [
        t
        for t in listar_titulos_para(
            user, farm=farm, direction=Direction.PAGAR, situacao="vencidos"
        )
        if t.due_date < hoje
    ]


def titulos_aguardando_aprovacao(user, *, farm=None):
    return list(
        listar_titulos_para(
            user,
            farm=farm,
            direction=Direction.PAGAR,
            situacao=PaymentStatus.PROGRAMADO,
        )
    )
