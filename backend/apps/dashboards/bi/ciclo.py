"""Aba **Ciclo de compra** — compromisso → viagem → recebimento → acerto.

A etapa é derivada (`etapa_do_compromisso`, ADR 0008), a quebra de peso vem de
`quebra_da_viagem` e o frete de `frete_da_viagem`: nada é gravado nem
recalculado aqui. Só quem pode ver o ciclo (`pode_ver_o_ciclo`).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

from django.db.models import Prefetch, Sum
from django.urls import reverse

from apps.core.money import safe_div
from apps.core.reversible import Status
from apps.procurement import receivings, trips
from apps.procurement import selectors as ciclo_sel
from apps.procurement.models import (
    CommitmentItem,
    Receiving,
    ReceivingLine,
    Trip,
    TripLoad,
)
from apps.procurement.selectors import Etapa

from . import specs
from .escopo import Escopo
from .specs import Kpi, Painel, Secao, Tabela

ZERO = Decimal("0")

#: Etapas na ordem do processo (ordinal: uma matiz, clara → escura). "Excluído"
#: não é etapa: o compromisso saiu da operação.
ORDEM_DAS_ETAPAS = (
    Etapa.EM_NEGOCIACAO,
    Etapa.APROVADO,
    Etapa.PROGRAMADO,
    Etapa.EM_VIAGEM,
    Etapa.RECEBIDO,
    Etapa.EM_ACERTO,
    Etapa.ACERTO_APROVADO,
)


ROTULO_CURTO = {
    Etapa.EM_NEGOCIACAO: "Em negociação",
    Etapa.APROVADO: "Aprovado",
    Etapa.PROGRAMADO: "Programado",
    Etapa.EM_VIAGEM: "Em viagem",
    Etapa.RECEBIDO: "Recebido",
    Etapa.EM_ACERTO: "Em acerto",
    Etapa.ACERTO_APROVADO: "Acerto aprovado",
}


def compromissos(e: Escopo) -> list:
    """Compromissos da safra no escopo, com a etapa derivada, sem os excluídos."""

    def calcular():
        validos = [
            c
            for c in ciclo_sel.listar_compromissos_para(
                e.user, season=e.season, farm=e.farm
            )
            if c.status != Status.EXCLUIDA and c.date <= e.fim
        ]
        etapas = ciclo_sel.etapas_dos_compromissos(validos)
        saida = [(c, etapas[c.pk]) for c in validos]
        return sorted(saida, key=lambda t: (t[0].date, t[0].pk))

    return e.memo("compromissos", calcular)


def cabecas_por_compromisso(e: Escopo) -> dict[int, dict]:
    """`{id: {previstas, embarcadas, recebidas}}` — três contagens de cabeças."""

    def calcular():
        ids = [c.pk for c, _ in compromissos(e)]
        previstas = dict(
            CommitmentItem.objects.filter(commitment_id__in=ids)
            .values_list("commitment_id")
            .annotate(t=Sum("head_count"))
            .order_by()
        )
        embarcadas = defaultdict(int)
        for commitment_id, planejadas, embarcado in (
            TripLoad.objects.filter(trip__commitment_id__in=ids)
            .exclude(trip__status=Status.EXCLUIDA)
            .values_list("trip__commitment_id", "planned_qty", "shipped_qty")
        ):
            embarcadas[commitment_id] += (
                embarcado if embarcado is not None else planejadas
            )
        recebidas = dict(
            ReceivingLine.objects.filter(
                load__trip__commitment_id__in=ids,
                receiving__status=Status.CONFIRMADA,
                load__trip__status=Status.CONFIRMADA,
            )
            .values_list("load__trip__commitment_id")
            .annotate(t=Sum("received_qty"))
            .order_by()
        )
        return {
            i: {
                "previstas": previstas.get(i, 0) or 0,
                "embarcadas": embarcadas.get(i, 0),
                "recebidas": recebidas.get(i, 0) or 0,
            }
            for i in ids
        }

    return e.memo("cabecas_por_compromisso", calcular)


def viagens(e: Escopo) -> list:
    def calcular():
        ids = [c.pk for c, _ in compromissos(e)]
        return list(
            Trip.objects.filter(commitment_id__in=ids)
            .exclude(status=Status.EXCLUIDA)
            .select_related("commitment__seller", "carrier")
            .prefetch_related("loads")
            .order_by("pickup_date", "id")
        )

    return e.memo("viagens", calcular)


def quebras(e: Escopo) -> list[tuple]:
    """`[(recebimento, QuebraDeViagem)]` das viagens recebidas com quebra informada."""

    def calcular():
        ids = [c.pk for c, _ in compromissos(e)]
        saida = []
        for r in (
            Receiving.objects.filter(
                trip__commitment_id__in=ids, status=Status.CONFIRMADA
            )
            .select_related("trip__commitment__seller")
            .prefetch_related(
                Prefetch("lines", queryset=ReceivingLine.objects.select_related("load"))
            )
            .order_by("date", "id")
        ):
            q = receivings.quebra_da_viagem(r)
            if q is not None and q.quebra_percentual is not None:
                saida.append((r, q))
        return saida

    return e.memo("quebras", calcular)


def quebra_media(e: Escopo) -> Decimal | None:
    """Média simples da quebra que o usuário informou em cada viagem."""
    q = [x.quebra_percentual for _, x in quebras(e)]
    return safe_div(sum(q, ZERO), len(q)) if q else None


def fretes(e: Escopo) -> list[tuple]:
    return e.memo("fretes", lambda: [(v, trips.frete_da_viagem(v)) for v in viagens(e)])


# --------------------------------------------------------------------------
# KPIs
# --------------------------------------------------------------------------


def kpis(e: Escopo) -> list[Kpi]:
    cs = compromissos(e)
    etapas = Counter(etapa for _, etapa in cs)
    cb = cabecas_por_compromisso(e)
    previstas = sum(v["previstas"] for v in cb.values())
    recebidas = sum(v["recebidas"] for v in cb.values())
    em_andamento = sum(
        n
        for etapa, n in etapas.items()
        if etapa not in (Etapa.EM_NEGOCIACAO, Etapa.ACERTO_APROVADO)
    )
    media = quebra_media(e)
    frete_total = sum((f.final for _, f in fretes(e) if f.final is not None), ZERO)
    n_com_frete = sum(1 for _, f in fretes(e) if f.final is not None)
    return [
        Kpi(
            "Compromissos na safra",
            specs.formatar(len(cs)),
            nota=f"{etapas[Etapa.ACERTO_APROVADO]} com acerto aprovado",
            url=reverse("procurement:compromisso_lista"),
            destaque=True,
        ),
        Kpi(
            "Em andamento",
            specs.formatar(em_andamento),
            nota="entre a aprovação e o acerto aprovado",
        ),
        Kpi(
            "Cabeças contratadas",
            specs.formatar(previstas),
            "cabeças",
            nota=f"{specs.formatar(recebidas)} já recebidas",
        ),
        Kpi(
            "Recebido do contratado",
            (
                specs.formatar(specs.pct(recebidas, previstas), "pct")
                if previstas
                else specs.TRAVESSAO
            ),
            nota="cabeças recebidas ÷ contratadas",
        ),
        Kpi(
            "Quebra de viagem média",
            specs.formatar(media, "pct2"),
            nota=f"{len(quebras(e))} viagem(ns) com quebra informada",
            ajuda="Média da quebra que o usuário digitou em cada recebimento. "
            "O sistema não calcula nem julga a quebra.",
        ),
        Kpi(
            "Aguardando acerto",
            specs.formatar(etapas[Etapa.RECEBIDO] + etapas[Etapa.EM_ACERTO]),
            nota="gado recebido, acerto não aprovado",
            estado=(
                "atencao"
                if (etapas[Etapa.RECEBIDO] + etapas[Etapa.EM_ACERTO])
                else "bom"
            ),
            estado_texto=(
                "Falta fechar"
                if (etapas[Etapa.RECEBIDO] + etapas[Etapa.EM_ACERTO])
                else "Em dia"
            ),
            ajuda="Enquanto o acerto não é aprovado o gado não está no saldo do rebanho (pendência #24).",
        ),
        Kpi(
            "Frete",
            specs.brl_curto(frete_total) if n_com_frete else specs.TRAVESSAO,
            nota=f"{n_com_frete} de {len(viagens(e))} viagens com frete",
            ajuda="Realizado, quando informado; senão o previsto pela tarifa.",
        ),
    ]


# --------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------


def grafico_funil(e: Escopo) -> specs.Grafico:
    cs = compromissos(e)
    cb = cabecas_por_compromisso(e)
    contagem = Counter(etapa for _, etapa in cs)
    cabecas = defaultdict(int)
    for c, etapa in cs:
        cabecas[etapa] += cb[c.pk]["previstas"]
    return specs.funil(
        "ciclo-funil",
        "Onde estão os compromissos",
        [
            (
                ROTULO_CURTO[etapa],
                contagem[etapa],
                f"{specs.formatar(cabecas[etapa])} cabeças contratadas",
            )
            for etapa in ORDEM_DAS_ETAPAS
        ],
        formato="num0",
        nota="Etapa derivada do que existe: aprovado, programado, viagem, recebimento, acerto.",
        largura="metade",
        url=reverse("procurement:compromisso_lista"),
    )


def grafico_previsto_embarcado_recebido(e: Escopo) -> specs.Grafico:
    cb = cabecas_por_compromisso(e)
    cs = [(c, t) for c, t in compromissos(e) if cb[c.pk]["previstas"]]
    return specs.cartesiano(
        "ciclo-previsto-recebido",
        "Contratado × embarcado × recebido",
        [c.code for c, _ in cs],
        [
            specs.serie(
                "Contratadas", [cb[c.pk]["previstas"] for c, _ in cs], cor="neutro"
            ),
            specs.serie(
                "Embarcadas",
                [cb[c.pk]["embarcadas"] for c, _ in cs],
                cor=specs.COR_COMPRAS,
            ),
            specs.serie(
                "Recebidas",
                [cb[c.pk]["recebidas"] for c, _ in cs],
                cor=specs.COR_VENDAS,
            ),
        ],
        formato="cb",
        titulo_y="Cabeças",
        largura="metade",
        nota="A diferença entre as barras de um mesmo compromisso é o que ficou pelo caminho.",
    )


def grafico_quebra(e: Escopo) -> specs.Grafico:
    q = quebras(e)
    g = specs.cartesiano(
        "ciclo-quebra",
        "Quebra de viagem de cada recebimento",
        [r.trip.code for r, _ in q],
        [
            specs.serie(
                "Quebra",
                [x.quebra_percentual for _, x in q],
                cor="marca",
                rotulo=True,
            )
        ],
        formato="pct2",
        titulo_y="% informado",
        nota="Quebra digitada em cada recebimento. Sem alerta automático: a leitura é sua.",
        largura="metade",
        url=reverse("reports:relatorio", args=["fretes-e-quebra"]),
    )
    return g


def grafico_produtores(e: Escopo) -> specs.Grafico:
    cb = cabecas_por_compromisso(e)
    soma = defaultdict(int)
    for c, _ in compromissos(e):
        soma[c.seller.name] += cb[c.pk]["previstas"]
    return specs.ranking(
        "ciclo-produtores",
        "Cabeças contratadas por produtor",
        list(soma.items()),
        formato="cb",
        nome_serie="Cabeças",
        largura="terco",
        url=reverse("partners:lista"),
    )


def grafico_frete(e: Escopo) -> specs.Grafico:
    fs = [(v, f) for v, f in fretes(e) if f.final is not None]
    return specs.cartesiano(
        "ciclo-frete",
        "Frete previsto × realizado por viagem",
        [v.code for v, _ in fs],
        [
            specs.serie("Previsto", [f.previsto for _, f in fs], cor="neutro"),
            specs.serie(
                "Realizado", [f.realizado for _, f in fs], cor=specs.COR_CUSTOS
            ),
        ],
        formato="brl",
        titulo_y="R$",
        largura="terco",
        nota="Viagem sem frete realizado informado mostra só o previsto pela tarifa.",
    )


def grafico_por_transportador(e: Escopo) -> specs.Grafico:
    soma = defaultdict(lambda: ZERO)
    for v, f in fretes(e):
        if f.final is not None:
            soma[v.carrier.name if v.carrier_id else "Sem transportador"] += f.final
    return specs.ranking(
        "ciclo-transportador",
        "Frete por transportador",
        list(soma.items()),
        formato="brl",
        nome_serie="Frete",
        largura="terco",
    )


def tabela_em_andamento(e: Escopo) -> Tabela:
    cb = cabecas_por_compromisso(e)
    abertos = [
        (c, etapa)
        for c, etapa in compromissos(e)
        if etapa not in (Etapa.ACERTO_APROVADO, Etapa.EXCLUIDO)
    ][:15]
    linhas, links, marcas = [], [], {}
    for i, (c, etapa) in enumerate(abertos):
        v = cb[c.pk]
        linhas.append(
            [
                c.code,
                c.seller.name,
                c.destination_farm.name,
                Etapa(etapa).label,
                specs.formatar(v["previstas"]),
                specs.formatar(v["recebidas"]),
                f"{c.pickup_date:%d/%m/%Y}" if c.pickup_date else specs.TRAVESSAO,
                f"{c.slaughter_date:%d/%m/%Y}" if c.slaughter_date else specs.TRAVESSAO,
            ]
        )
        links.append(reverse("procurement:compromisso_detalhe", args=[c.pk]))
        if etapa in (Etapa.RECEBIDO, Etapa.EM_ACERTO):
            marcas[(i, 3)] = ("atencao", "falta fechar o acerto")
    return Tabela(
        [
            "Compromisso",
            "Produtor",
            "Destino",
            "Etapa",
            "Contratadas",
            "Recebidas",
            "Retirada",
            "Abate previsto",
        ],
        linhas,
        numericas=[4, 5],
        titulo="Compromissos em andamento",
        links=links,
        marcas=marcas,
        codigo=0,
        vazio="Nenhum compromisso em andamento.",
    )


# --------------------------------------------------------------------------
# Aba
# --------------------------------------------------------------------------


def montar(e: Escopo) -> Painel:
    painel = Painel(kpis=kpis(e), kpis_titulo="Do compromisso ao acerto")
    if not compromissos(e):
        painel.vazio = "Nenhum compromisso de compra na safra e no recorte escolhidos."
    painel.secoes = [
        Secao("Processo", [grafico_funil(e), grafico_previsto_embarcado_recebido(e)]),
        Secao(
            "Viagens",
            [grafico_quebra(e), grafico_frete(e), grafico_por_transportador(e)],
        ),
        Secao("Com quem", [grafico_produtores(e)], tabelas=[tabela_em_andamento(e)]),
    ]
    return painel
