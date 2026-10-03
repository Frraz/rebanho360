"""Leitura. O painel responde "o que preciso fazer hoje?" — pendências em
primeiro lugar, números depois.

Nada é calculado aqui que tenha dono: peso, rendimento, resultado e
mortalidade vêm dos serviços deles (`CarcassService`, `SaleResultService`,
`taxa_de_mortalidade`). Este módulo reúne e conta, sempre dentro do escopo do
usuário (`for_user`, regra 4). Indicador sem dado é `None` — "—" na tela.
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Max, Sum
from django.urls import reverse

from apps.core.formatting import dinheiro_br, numero_br
from apps.core.money import safe_div
from apps.core.reversible import Status
from apps.costs.models import CostEntry
from apps.finance import selectors as financeiro
from apps.finance.permissions import pode_aprovar_pagamento, pode_ver_titulos
from apps.herd import selectors as herd_selectors
from apps.herd.models import (
    ENTRY_TYPES,
    EXIT_TYPES,
    HerdLedgerEntry,
    Weighing,
)
from apps.imports.models import BatchStatus, ImportKind, ImportRow, RowStatus
from apps.imports.permissions import pode_importar
from apps.livestock.models import Lot, LotStatus
from apps.procurement import selectors as ciclo
from apps.procurement.models import Commitment, ReceivingLine, Settlement
from apps.procurement.permissions import pode_aprovar_o_acerto, pode_ver_o_ciclo
from apps.purchases.models import Purchase
from apps.sales import carcass
from apps.sales.models import Sale, SaleType
from apps.sales.result import resultado_do_lote

DIAS_SEM_PESAGEM = 90
EXEMPLOS = 4


@dataclass(frozen=True)
class Pendencia:
    chave: str
    texto: str  # "3 transferências sem entrada correspondente"
    quantidade: int
    url: str
    exemplos: tuple = ()


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


# --------------------------------------------------------------------------
# Apoio: saldos e pesagens por lote, no escopo
# --------------------------------------------------------------------------


def _saldo_por_lote(user, farm=None) -> dict[int, int]:
    qs = HerdLedgerEntry.objects.for_user(user)
    if farm is not None:
        qs = qs.filter(farm=farm)
    return dict(qs.order_by().values_list("lot_id").annotate(t=Sum("quantity")))


def _ultima_pesagem_por_lote(user) -> dict[int, datetime.date]:
    return dict(
        Weighing.objects.for_user(user)
        .filter(status=Status.CONFIRMADA)
        .order_by()
        .values_list("lot_id")
        .annotate(d=Max("date"))
    )


def _lotes_abertos(user, farm=None):
    qs = Lot.objects.for_user(user).filter(status=LotStatus.ABERTO)
    if farm is not None:
        qs = qs.filter(farm=farm)
    return qs.select_related("farm").order_by("farm__name", "code")


# --------------------------------------------------------------------------
# As regras de pendência (docs/roadmap/fase-3, F3-09; financeiro: fase-4, F4-06)
# --------------------------------------------------------------------------


def _transferencias_sem_contrapartida(user) -> Pendencia | None:
    """No razão o trigger de banco já impede; o que aparece aqui são as
    linhas `TRANSF.` da planilha que ficaram sem par na importação — nunca
    importadas em silêncio (pendência #2)."""
    do_razao = list(herd_selectors.conciliar_transferencias(user))
    da_planilha = 0
    if pode_importar(user):
        da_planilha = (
            ImportRow.objects.filter(
                batch__kind=ImportKind.MOVIMENTACOES,
                status=RowStatus.PENDENTE,
                raw__tipo__startswith="TRANSF",
            )
            .exclude(batch__status=BatchStatus.CANCELADO)
            .count()
        )
    total = len(do_razao) + da_planilha
    if not total:
        return None
    exemplos = tuple(f"{m.code} · {m.date:%d/%m/%Y}" for m in do_razao[:EXEMPLOS])
    return Pendencia(
        "transferencias",
        _plural(
            total,
            "transferência sem entrada correspondente",
            "transferências sem entrada correspondente",
        ),
        total,
        (
            reverse("herd:conciliacao_transferencias")
            if do_razao
            else reverse("imports:lista")
        ),
        exemplos,
    )


def _custos_sem_centro(user) -> Pendencia | None:
    """Custo no sistema sempre tem centro (obrigatório). O que sobra sem
    centro são as linhas da planilha ainda em prévia."""
    if not pode_importar(user):
        return None
    total = ImportRow.objects.filter(
        batch__kind=ImportKind.CUSTOS,
        batch__status=BatchStatus.PREVIA,
        status=RowStatus.PENDENTE,
        messages__contains=[{"campo": "cost_center"}],
    ).count()
    if not total:
        return None
    return Pendencia(
        "custos_sem_centro",
        _plural(total, "custo sem centro de custo", "custos sem centro de custo"),
        total,
        reverse("imports:lista"),
    )


def _lotes_sem_pesagem(user, farm, hoje) -> Pendencia | None:
    saldos = _saldo_por_lote(user, farm)
    pesagens = _ultima_pesagem_por_lote(user)
    achados = []
    for lote in _lotes_abertos(user, farm):
        if saldos.get(lote.pk, 0) <= 0:
            continue
        ultima = pesagens.get(lote.pk)
        referencia = ultima or lote.entry_date
        dias = (hoje - referencia).days
        if dias > DIAS_SEM_PESAGEM:
            quando = f"última pesagem {ultima:%d/%m/%Y}" if ultima else "nunca pesado"
            achados.append(f"{lote.code} · {lote.farm.name} — {quando} ({dias} dias)")
    if not achados:
        return None
    return Pendencia(
        "sem_pesagem",
        _plural(
            len(achados),
            f"lote sem pesagem há mais de {DIAS_SEM_PESAGEM} dias",
            f"lotes sem pesagem há mais de {DIAS_SEM_PESAGEM} dias",
        ),
        len(achados),
        reverse("livestock:lote_lista"),
        tuple(achados[:EXEMPLOS]),
    )


def _vendas_sem_carcaca(user, farm) -> Pendencia | None:
    qs = Sale.objects.for_user(user).filter(
        status=Status.CONFIRMADA, type=SaleType.ABATE, carcass_weight_kg__isnull=True
    )
    if farm is not None:
        qs = qs.filter(farm=farm)
    vendas = list(qs.order_by("-date"))
    if not vendas:
        return None
    return Pendencia(
        "sem_carcaca",
        _plural(len(vendas), "venda sem peso de carcaça", "vendas sem peso de carcaça"),
        len(vendas),
        reverse("sales:lista") + "?sem_carcaca=1&situacao=CONFIRMADA",
        tuple(
            f"{v.code} · {v.date:%d/%m/%Y} · {v.head_count} cb"
            for v in vendas[:EXEMPLOS]
        ),
    )


def _lotes_zerados_abertos(user, farm) -> Pendencia | None:
    saldos = _saldo_por_lote(user, farm)
    achados = [
        lote
        for lote in _lotes_abertos(user, farm)
        # `in saldos`: lote que nunca teve animal não é "zerado", é novo.
        if lote.pk in saldos and saldos[lote.pk] == 0
    ]
    if not achados:
        return None
    return Pendencia(
        "zerado_aberto",
        _plural(
            len(achados),
            "lote a saldo zero ainda aberto",
            "lotes a saldo zero ainda abertos",
        ),
        len(achados),
        reverse("livestock:lote_lista"),
        tuple(f"{lote.code} · {lote.farm.name}" for lote in achados[:EXEMPLOS]),
    )


def _rendimento_fora_da_faixa(user, farm) -> Pendencia | None:
    qs = Sale.objects.for_user(user).filter(
        status=Status.CONFIRMADA, type=SaleType.ABATE, carcass_weight_kg__isnull=False
    )
    if farm is not None:
        qs = qs.filter(farm=farm)
    fora = []
    for venda in qs.order_by("-date"):
        rendimento = carcass.indicadores_da_venda(venda).rendimento
        if carcass.rendimento_fora_da_faixa(rendimento):
            fora.append(
                f"{venda.code} · {venda.date:%d/%m/%Y} — rendimento {numero_br(rendimento, 2)}%"
            )
    if not fora:
        return None
    return Pendencia(
        "rendimento",
        _plural(
            len(fora),
            "venda com rendimento fora da faixa",
            "vendas com rendimento fora da faixa",
        ),
        len(fora),
        reverse("sales:lista") + "?situacao=CONFIRMADA",
        tuple(fora[:EXEMPLOS]),
    )


def _titulos_vencidos(user, farm, hoje) -> Pendencia | None:
    """Alerta de vencido (F4-06): título a pagar em aberto cujo vencimento já
    passou. Só para quem pode ver o financeiro, e só das fazendas dele."""
    if not pode_ver_titulos(user):
        return None
    vencidos = financeiro.titulos_vencidos(user, farm=farm, hoje=hoje)
    if not vencidos:
        return None
    total = sum((t.balance for t in vencidos), start=Decimal("0"))
    return Pendencia(
        "titulos_vencidos",
        _plural(
            len(vencidos),
            "título a pagar vencido",
            "títulos a pagar vencidos",
        )
        + f", somando {dinheiro_br(total)}",
        len(vencidos),
        reverse("finance:contas_a_pagar") + "?situacao=vencidos",
        tuple(
            f"{t.code} · {t.payee.name if t.payee_id else 'favorecido a definir'} — "
            f"{dinheiro_br(t.balance)}, venceu em {t.due_date:%d/%m/%Y}"
            for t in vencidos[:EXEMPLOS]
        ),
    )


def _pagamentos_a_aprovar(user, farm) -> Pendencia | None:
    """Pagamento programado esperando alguém com permissão de aprovar."""
    if not pode_aprovar_pagamento(user):
        return None
    esperando = financeiro.titulos_aguardando_aprovacao(user, farm=farm)
    if not esperando:
        return None
    return Pendencia(
        "a_aprovar",
        _plural(
            len(esperando),
            "pagamento programado aguardando aprovação",
            "pagamentos programados aguardando aprovação",
        ),
        len(esperando),
        reverse("finance:contas_a_pagar") + "?situacao=PROGRAMADO",
        tuple(
            f"{t.code} · {t.payee.name if t.payee_id else '—'} — "
            f"{dinheiro_br(t.balance)}, para {t.scheduled_date:%d/%m/%Y}"
            for t in esperando[:EXEMPLOS]
            if t.scheduled_date
        ),
    )


def _recebido_aguardando_acerto(user, farm) -> Pendencia | None:
    """Gado que já chegou e ainda não tem acerto aberto. Enquanto o acerto não
    é aprovado o animal **não está no saldo** do rebanho (pendência #24): o
    painel diz isso, em vez de deixar o campo estranhar o número."""
    if not pode_ver_o_ciclo(user):
        return None
    compromissos = Commitment.objects.for_user(user).filter(status=Status.CONFIRMADA)
    if farm is not None:
        compromissos = compromissos.filter(destination_farm=farm)
    esperando = []
    for c in compromissos.select_related("seller").order_by("date", "id"):
        if ciclo.acerto_ativo(c) is not None:
            continue
        cabecas = ReceivingLine.objects.filter(
            load__item__commitment=c,
            receiving__status=Status.CONFIRMADA,
            load__trip__status=Status.CONFIRMADA,
        ).aggregate(total=Sum("received_qty"))["total"]
        if cabecas:
            esperando.append((c, cabecas))
    if not esperando:
        return None
    total = sum(cabecas for _, cabecas in esperando)
    return Pendencia(
        "recebido_sem_acerto",
        _plural(
            len(esperando),
            "compromisso com gado recebido e sem acerto",
            "compromissos com gado recebido e sem acerto",
        )
        + f" — {numero_br(Decimal(total), 0)} cabeças ainda fora do saldo do rebanho",
        len(esperando),
        reverse("procurement:compromisso_lista") + "?situacao=CONFIRMADA",
        tuple(
            f"{c.code} · {c.seller.name} — {cabecas} cabeças recebidas"
            for c, cabecas in esperando[:EXEMPLOS]
        ),
    )


def _acertos_a_aprovar(user, farm) -> Pendencia | None:
    """Acerto em andamento esperando quem pode aprovar."""
    if not pode_aprovar_o_acerto(user):
        return None
    acertos = Settlement.objects.for_user(user).filter(status=Status.RASCUNHO)
    if farm is not None:
        acertos = acertos.filter(commitment__destination_farm=farm)
    acertos = list(acertos.select_related("commitment__seller").order_by("date", "id"))
    if not acertos:
        return None
    return Pendencia(
        "acerto_a_aprovar",
        _plural(
            len(acertos),
            "acerto aguardando aprovação",
            "acertos aguardando aprovação",
        ),
        len(acertos),
        reverse("procurement:acerto_lista") + "?situacao=RASCUNHO",
        tuple(
            f"{a.code} · {a.commitment.seller.name} — aberto em {a.date:%d/%m/%Y}"
            for a in acertos[:EXEMPLOS]
        ),
    )


def pendencias_do_painel(user, *, farm=None, season=None, hoje=None) -> list[Pendencia]:
    """Só devolve o que **tem** pendência. Lista vazia = nada a fazer hoje."""
    hoje = hoje or datetime.date.today()
    regras = (
        _transferencias_sem_contrapartida(user),
        _custos_sem_centro(user),
        _lotes_sem_pesagem(user, farm, hoje),
        _vendas_sem_carcaca(user, farm),
        _lotes_zerados_abertos(user, farm),
        _rendimento_fora_da_faixa(user, farm),
        _titulos_vencidos(user, farm, hoje),
        _pagamentos_a_aprovar(user, farm),
        _recebido_aguardando_acerto(user, farm),
        _acertos_a_aprovar(user, farm),
    )
    return [p for p in regras if p is not None]


# --------------------------------------------------------------------------
# Cartões
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CartaoRebanho:
    cabecas: int
    fazendas: int
    lotes_abertos: int
    entradas_do_mes: int
    saidas_do_mes: int


def cartao_do_rebanho(user, *, farm=None, hoje=None) -> CartaoRebanho:
    hoje = hoje or datetime.date.today()
    qs = HerdLedgerEntry.objects.for_user(user)
    if farm is not None:
        qs = qs.filter(farm=farm)
    por_fazenda = dict(
        qs.filter(date__lte=hoje)
        .order_by()
        .values_list("farm_id")
        .annotate(t=Sum("quantity"))
    )
    no_mes = qs.filter(date__year=hoje.year, date__month=hoje.month)

    def soma(tipos, sinal):
        total = no_mes.filter(movement__type__in=tipos).aggregate(t=Sum("quantity"))[
            "t"
        ]
        return (total or 0) * sinal

    return CartaoRebanho(
        cabecas=sum(por_fazenda.values()),
        fazendas=sum(1 for t in por_fazenda.values() if t > 0),
        lotes_abertos=_lotes_abertos(user, farm).count(),
        entradas_do_mes=soma(ENTRY_TYPES, 1),
        saidas_do_mes=soma(EXIT_TYPES, -1),
    )


@dataclass(frozen=True)
class CartaoDaSafra:
    comprado_cabecas: int
    comprado_valor: Decimal
    vendido_cabecas: int
    vendido_valor: Decimal
    custos: Decimal
    custo_por_cabeca: Decimal | None  # custos da safra ÷ rebanho atual
    custo_por_arroba: Decimal | None  # dos lotes encerrados na safra
    lotes_encerrados: int = 0
    motivo_custo_por_arroba: str = ""
    avisos: list = field(default_factory=list)


def cartao_da_safra(
    user, *, season, farm=None, cabecas_atuais: int = 0
) -> CartaoDaSafra | None:
    if season is None:
        return None
    compras = Purchase.objects.for_user(user).filter(
        status=Status.CONFIRMADA, season=season
    )
    vendas = Sale.objects.for_user(user).filter(status=Status.CONFIRMADA, season=season)
    # Os custos que a compra gera (animais, frete...) já estão em "Comprado":
    # contá-los de novo em "Custos" dobraria a aquisição. Aqui só os avulsos —
    # o mesmo critério do total de R$ 1.046.907,76 da planilha.
    custos = CostEntry.objects.for_user(user).filter(
        status=Status.CONFIRMADA, season=season, source_purchase__isnull=True
    )
    if farm is not None:
        compras = compras.filter(destination_farm=farm)
        vendas = vendas.filter(farm=farm)
        custos = custos.filter(farm=farm)
    c = compras.aggregate(cb=Sum("head_count"), v=Sum("animal_value"))
    v = vendas.aggregate(cb=Sum("head_count"), v=Sum("total_value"))
    total_custos = custos.aggregate(t=Sum("amount"))["t"] or Decimal("0")

    # Custo/@ do painel = o dos lotes que fecharam a conta na safra: custo do
    # lote ÷ @ vendida, vindo do MESMO serviço que a tela do lote usa.
    encerrados = Lot.objects.for_user(user).filter(
        status=LotStatus.ENCERRADO,
        exit_date__gte=season.start_date,
        exit_date__lte=season.end_date,
    )
    if farm is not None:
        encerrados = encerrados.filter(farm=farm)
    custo_total_arroba, arrobas, completos = Decimal("0"), Decimal("0"), 0
    for lote in encerrados:
        r = resultado_do_lote(lote)
        if r.custo_considerado is not None and r.arrobas_vendidas:
            custo_total_arroba += r.custo_considerado
            arrobas += r.arrobas_vendidas
            completos += 1
    quantos = encerrados.count()
    motivo = ""
    if not quantos:
        motivo = "nenhum lote encerrou na safra ainda"
    elif not completos:
        motivo = "os lotes encerrados não têm custo de aquisição ou peso de carcaça"

    return CartaoDaSafra(
        comprado_cabecas=c["cb"] or 0,
        comprado_valor=c["v"] or Decimal("0"),
        vendido_cabecas=v["cb"] or 0,
        vendido_valor=v["v"] or Decimal("0"),
        custos=total_custos,
        custo_por_cabeca=(
            safe_div(total_custos, cabecas_atuais) if cabecas_atuais else None
        ),
        custo_por_arroba=safe_div(custo_total_arroba, arrobas),
        lotes_encerrados=completos,
        motivo_custo_por_arroba=motivo,
    )


# --------------------------------------------------------------------------
# Últimos lançamentos
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Lancamento:
    quando: datetime.datetime
    data: datetime.date
    tipo: str
    codigo: str
    resumo: str
    quem: str
    url: str


def ultimos_lancamentos(user, *, farm=None, limite: int = 8) -> list[Lancamento]:
    """Compras, vendas, movimentações e pesagens lançadas por pessoas (os
    movimentos que uma compra ou venda gera já aparecem nelas)."""
    itens = []
    confirmada = Status.CONFIRMADA

    compras = Purchase.objects.for_user(user).filter(status=confirmada)
    vendas = Sale.objects.for_user(user).filter(status=confirmada)
    movimentos = herd_selectors.listar_movimentos_para(user).filter(
        status=confirmada, origin_purchase__isnull=True, origin_sale__isnull=True
    )
    pesagens = Weighing.objects.for_user(user).filter(status=confirmada)
    if farm is not None:
        compras = compras.filter(destination_farm=farm)
        vendas = vendas.filter(farm=farm)
        pesagens = pesagens.filter(farm=farm)

    for c in compras.select_related("destination_farm", "created_by").order_by(
        "-created_at"
    )[:limite]:
        itens.append(
            Lancamento(
                c.created_at,
                c.date,
                "Compra",
                c.code,
                f"{c.head_count} cb · {c.destination_farm.name}",
                str(c.created_by or "—"),
                reverse("purchases:detalhe", args=[c.pk]),
            )
        )
    for v in vendas.select_related("farm", "buyer", "created_by").order_by(
        "-created_at"
    )[:limite]:
        itens.append(
            Lancamento(
                v.created_at,
                v.date,
                v.get_type_display(),
                v.code,
                f"{v.head_count} cb · {v.buyer.name}",
                str(v.created_by or "—"),
                reverse("sales:detalhe", args=[v.pk]),
            )
        )
    for m in movimentos.select_related("created_by").order_by("-created_at")[:limite]:
        itens.append(
            Lancamento(
                m.created_at,
                m.date,
                m.get_type_display(),
                m.code,
                f"{m.quantity} cb",
                str(m.created_by or "—"),
                reverse("herd:movimento_detalhe", args=[m.pk]),
            )
        )
    for p in pesagens.select_related("lot", "created_by").order_by("-created_at")[
        :limite
    ]:
        itens.append(
            Lancamento(
                p.created_at,
                p.date,
                "Pesagem",
                p.lot.code,
                f"{p.head_count} cb pesadas",
                str(p.created_by or "—"),
                reverse("livestock:lote_detalhe", args=[p.lot_id]),
            )
        )
    itens.sort(key=lambda i: i.quando, reverse=True)
    return itens[:limite]
