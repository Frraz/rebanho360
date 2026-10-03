"""Relatórios do ciclo de compra (Fase 5), em conceito — não pixel a pixel — a
partir dos relatórios legados do SisAtak (docs/fontes/relatorios-legado/).

Como todo relatório do sistema, **não calcula**: chama `calcular_acerto` e os
serviços de viagem e recebimento, os mesmos que a tela usa. Indicador sem dado
sai como "—", e o programado × realizado diz por quê.

Registrados de forma preguiçosa em `services.RELATORIOS` (evita importação
circular com este módulo, que usa `Relatorio` e `Coluna` de lá).
"""

import datetime
from decimal import Decimal

from apps.core.formatting import dinheiro_br, numero_br
from apps.core.money import safe_div
from apps.core.reversible import Status
from apps.livestock.models import Sex
from apps.procurement import commitments, receivings, selectors, trips
from apps.procurement.models import Commitment, PriceBasis, Settlement, Trip
from apps.procurement.settlement import calcular_acerto
from apps.reports.services import (
    DINHEIRO,
    INTEIRO,
    NUMERO,
    PERCENTUAL,
    Coluna,
    Relatorio,
    _contexto,
    _filtro_de_periodo,
)

ZERO = Decimal("0")


# --------------------------------------------------------------------------
# Apoio
# --------------------------------------------------------------------------


def _data(valor: datetime.date | None) -> str | None:
    return f"{valor:%d/%m/%Y}" if valor else None


def _regra_em_texto(comissao) -> str | None:
    """A regra **gravada no compromisso** (snapshot), nunca a do cadastro de hoje."""
    return comissao.regra_em_texto() if comissao is not None else None


def _compromissos(user, *, season, farm, aprovados=True):
    qs = Commitment.objects.for_user(user).select_related(
        "seller", "destination_farm", "commissioned", "season"
    )
    qs = (
        qs.filter(status=Status.CONFIRMADA)
        if aprovados
        else qs.exclude(status=Status.EXCLUIDA)
    )
    if season is not None:
        qs = qs.filter(season=season)
    if farm is not None:
        qs = qs.filter(destination_farm=farm)
    return qs


def _faixas_em_texto(item) -> str | None:
    if item.price_basis != PriceBasis.ARROBA:
        return f"{dinheiro_br(item.unit_price)} por cabeça" if item.unit_price else None
    precos = [item.preco_da_faixa(n) for n in range(1, 6)]
    return " / ".join(numero_br(p, 2) if p is not None else "—" for p in precos)


# --------------------------------------------------------------------------
# Programação (F5-14)
# --------------------------------------------------------------------------


def programacao_de_embarque(user, *, season, farm, start=None, end=None) -> Relatorio:
    viagens = Trip.objects.for_user(user).exclude(status=Status.EXCLUIDA)
    viagens = viagens.filter(commitment__status=Status.CONFIRMADA).select_related(
        "commitment__seller", "commitment__destination_farm", "carrier"
    )
    if season is not None:
        viagens = viagens.filter(commitment__season=season)
    if farm is not None:
        viagens = viagens.filter(commitment__destination_farm=farm)
    if start:
        viagens = viagens.filter(pickup_date__gte=start)
    if end:
        viagens = viagens.filter(pickup_date__lte=end)

    linhas = []
    for v in viagens.order_by("pickup_date", "id"):
        recebimento = v.receivings.exclude(status=Status.EXCLUIDA).first()
        frete = trips.frete_da_viagem(v)
        linhas.append(
            {
                "retirada": _data(v.pickup_date),
                "viagem": v.code,
                "compromisso": v.commitment.code,
                "produtor": v.commitment.seller.name,
                "cidade": v.commitment.origin_city or None,
                "transportador": v.carrier.name if v.carrier_id else None,
                "veiculo": " · ".join(x for x in (v.driver_name, v.vehicle_plate) if x)
                or None,
                "cabecas": trips.cabecas_da_viagem(v),
                "distancia": v.distance_km,
                "frete": frete.previsto,
                "situacao": "Recebida" if recebimento else "A caminho",
            }
        )
    return Relatorio(
        titulo="Programação de embarque",
        descricao="Os caminhões programados: quando saem, de onde, quem leva e quanto.",
        colunas=[
            Coluna("retirada", "Retirada"),
            Coluna("viagem", "Viagem"),
            Coluna("compromisso", "Compromisso"),
            Coluna("produtor", "Produtor"),
            Coluna("cidade", "Cidade"),
            Coluna("transportador", "Transportador"),
            Coluna("veiculo", "Motorista · placa"),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("distancia", "Distância (km)", INTEIRO),
            Coluna("frete", "Frete previsto", DINHEIRO),
            Coluna("situacao", "Situação"),
        ],
        linhas=linhas,
        totais={
            "retirada": "Total",
            "cabecas": sum(lin["cabecas"] for lin in linhas),
            "frete": sum((lin["frete"] for lin in linhas if lin["frete"]), ZERO),
        },
        filtros=[*_contexto(season, farm), *_filtro_de_periodo(start, end)],
        notas=["O período filtra a data da retirada. Viagem excluída não entra."],
    )


def programacao_de_abate(user, *, season, farm, start=None, end=None) -> Relatorio:
    """Por compromisso aprovado: quem, onde, quando e a que preço por faixa."""
    qs = _compromissos(user, season=season, farm=farm)
    if start:
        qs = qs.filter(slaughter_date__gte=start)
    if end:
        qs = qs.filter(slaughter_date__lte=end)

    linhas = []
    for c in qs.order_by("slaughter_date", "pickup_date", "id"):
        comissao = commitments.comissao_do(c)
        for item in c.items.select_related("category").order_by("number"):
            linhas.append(
                {
                    "compromisso": c.code,
                    "produtor": c.seller.name,
                    "propriedade": " · ".join(
                        x for x in (c.origin_property, c.origin_city) if x
                    )
                    or None,
                    "comprador": c.commissioned.name if c.commissioned_id else None,
                    "movimento": _data(c.date),
                    "retirada": _data(c.pickup_date),
                    "abate": _data(c.slaughter_date),
                    "caminhoes": c.trucks,
                    "distancia": c.distance_km,
                    "pagamento": (
                        f"{c.payment_days} dias" if c.payment_days else "à vista"
                    ),
                    "comissao": _regra_em_texto(comissao),
                    "item": f"{item.number} · {item.category.name}",
                    "cabecas": item.head_count,
                    "media_arrobas": item.expected_arrobas,
                    "precos": _faixas_em_texto(item),
                }
            )
    return Relatorio(
        titulo="Programação de abate",
        descricao=(
            "Por compromisso aprovado: produtor, datas, caminhões, distância, "
            "condição de pagamento, comissão e o preço de cada faixa."
        ),
        colunas=[
            Coluna("compromisso", "Compromisso"),
            Coluna("produtor", "Produtor"),
            Coluna("propriedade", "Propriedade · cidade"),
            Coluna("comprador", "Comprador"),
            Coluna("movimento", "Movimento"),
            Coluna("retirada", "Retirada"),
            Coluna("abate", "Abate"),
            Coluna("caminhoes", "Caminhões", INTEIRO),
            Coluna("distancia", "Distância (km)", INTEIRO),
            Coluna("pagamento", "Pagamento"),
            Coluna("comissao", "Comissão (regra gravada)"),
            Coluna("item", "Item"),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("media_arrobas", "Média @ prevista", NUMERO),
            Coluna("precos", "R$/@ por faixa (1 a 5)"),
        ],
        linhas=linhas,
        totais={
            "compromisso": "Total",
            "cabecas": sum(lin["cabecas"] for lin in linhas),
        },
        filtros=[*_contexto(season, farm), *_filtro_de_periodo(start, end)],
        notas=[
            "O período filtra a data prevista do abate. A comissão é a regra "
            "gravada no compromisso quando ele foi aprovado."
        ],
    )


# --------------------------------------------------------------------------
# Conferência do acerto (F5-15)
# --------------------------------------------------------------------------


def _celula(valor, tipo) -> str:
    from apps.procurement.templatetags.procurement_tags import comparado

    return comparado(valor, tipo)


def conferencia_do_acerto(user, *, season, farm, acerto: Settlement | None = None):
    """Um acerto, em três blocos: o resumo financeiro e tributário, o
    detalhamento dos títulos e o romaneio valorizado. Mesmos números da tela."""
    vazio = Relatorio(
        titulo="Conferência do acerto",
        descricao="Resumo financeiro e tributário, títulos e romaneio de um acerto.",
        colunas=[Coluna("item", "Item"), Coluna("valor", "Valor", DINHEIRO)],
        linhas=[],
        filtros=[*_contexto(season, farm), "Nenhum acerto escolhido"],
        notas=["Abra um acerto e use o relatório a partir dele."],
    )
    if acerto is None:
        return vazio

    c = acerto.commitment
    calculo = calcular_acerto(c)
    situacao = {
        Status.CONFIRMADA: "aprovado",
        Status.RASCUNHO: "em andamento",
        Status.EXCLUIDA: "excluído",
    }[acerto.status]

    resumo = [
        {
            "item": "Valor dos animais (romaneio e cabeças)",
            "valor": calculo.valor_dos_itens,
        },
        {"item": "(−) Descontos", "valor": calculo.descontos},
        {"item": "Valor dos animais", "valor": calculo.valor_dos_animais},
        {"item": "(+) Frete", "valor": calculo.frete},
    ]
    for linha in acerto.lines.select_related("tax_type"):
        resumo.append(
            {
                "item": f"{linha.tax_type.name} ({linha.tax_type.get_nature_display().lower()})",
                "valor": linha.amount,
            }
        )
    resumo += [
        {"item": "(+) Comissão", "valor": calculo.comissao_calculada},
        {"item": "(+) Comissão extra", "valor": calculo.comissao_extra},
        {"item": "Custo de aquisição", "valor": calculo.custo_aquisicao},
        {"item": "(−) Adiantamentos", "valor": calculo.adiantamentos},
        {"item": "(−) Créditos", "valor": calculo.creditos},
        {"item": "Líquido a pagar ao vendedor", "valor": calculo.liquido_ao_produtor},
    ]
    for nota in acerto.fiscal_notes.all():
        resumo.append(
            {
                "item": f"Nota fiscal {nota.number}"
                + (f"/{nota.series}" if nota.series else "")
                + f" de {nota.issue_date:%d/%m/%Y}",
                "valor": nota.amount,
            }
        )

    titulos = []
    for item in c.items.select_related("purchase"):
        compra = item.purchase
        if compra is None or compra.status != Status.CONFIRMADA:
            continue
        for t in compra.invoices.filter(status=Status.CONFIRMADA).select_related(
            "payee"
        ):
            titulos.append(
                {
                    "titulo": t.code,
                    "componente": t.get_component_display(),
                    "emissao": _data(t.issue_date),
                    "vencimento": _data(t.due_date),
                    "favorecido": t.payee.name if t.payee_id else "A definir",
                    "valor": t.amount,
                    "situacao": t.situacao_rotulo,
                }
            )
    detalhamento = Relatorio(
        titulo="Detalhamento financeiro",
        descricao="",
        colunas=[
            Coluna("titulo", "Título"),
            Coluna("componente", "Componente"),
            Coluna("emissao", "Emissão"),
            Coluna("vencimento", "Vencimento"),
            Coluna("favorecido", "Favorecido"),
            Coluna("valor", "Valor", DINHEIRO),
            Coluna("situacao", "Situação"),
        ],
        linhas=titulos,
        totais=(
            {"titulo": "Total", "valor": sum((t["valor"] for t in titulos), ZERO)}
            if titulos
            else None
        ),
        notas=(
            []
            if titulos
            else [
                "Os títulos nascem quando o acerto é aprovado. Dado bancário não vai em relatório."
            ]
        ),
    )

    romaneio_linhas, total_cab, total_peso, total_liq = [], 0, ZERO, ZERO
    for d in calculo.itens:
        if d.romaneio is None:
            continue
        for v in d.romaneio.linhas:
            g = v.linha
            romaneio_linhas.append(
                {
                    "produto": f"{d.item.number} · {d.item.category.name}",
                    "classificacao": g.carcass_class.name,
                    "faixa": f"Faixa {g.band}",
                    "cabecas": g.head_count,
                    "peso": g.carcass_weight_kg,
                    "media": v.media_arrobas,
                    "valor_arroba": g.price_per_arroba,
                    "valor_kg": v.valor_por_kg,
                    "desconto": g.discount_percent,
                    "liquido": v.liquido,
                }
            )
            total_cab += g.head_count
            total_peso += g.carcass_weight_kg
            total_liq += v.liquido
    romaneio = Relatorio(
        titulo="Romaneio de abate valorizado",
        descricao="",
        colunas=[
            Coluna("produto", "Produto"),
            Coluna("classificacao", "Classificação"),
            Coluna("faixa", "Faixa"),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("peso", "Peso (kg)", NUMERO),
            Coluna("media", "Média @", NUMERO),
            Coluna("valor_arroba", "Valor da @", DINHEIRO),
            Coluna("valor_kg", "Valor/kg", DINHEIRO),
            Coluna("desconto", "% desc.", PERCENTUAL),
            Coluna("liquido", "Valor líquido", DINHEIRO),
        ],
        linhas=romaneio_linhas,
        totais=(
            {
                "produto": "Total",
                "cabecas": total_cab,
                "peso": total_peso,
                "liquido": total_liq,
            }
            if romaneio_linhas
            else None
        ),
    )

    comparativo = Relatorio(
        titulo="Previsto × realizado",
        descricao="",
        colunas=[
            Coluna("item", "Item"),
            Coluna("previsto", "Previsto"),
            Coluna("realizado", "Realizado"),
        ],
        linhas=[
            {
                "item": cmp.rotulo,
                "previsto": _celula(cmp.previsto, cmp.tipo),
                "realizado": _celula(cmp.realizado, cmp.tipo),
            }
            for cmp in calculo.comparacoes
        ],
    )

    return Relatorio(
        titulo="Conferência do acerto",
        descricao=(
            f"Acerto {acerto.code} · {c.seller.name} · compromisso {c.code}"
            f" · {situacao}."
        ),
        colunas=[Coluna("item", "Item"), Coluna("valor", "Valor", DINHEIRO)],
        linhas=resumo,
        filtros=[
            *_contexto(season, farm),
            f"Acerto {acerto.code} ({situacao})",
            f"Compromisso {c.code}",
            f"Produtor {c.seller.name}",
            f"Fazenda {c.destination_farm.name}",
        ],
        notas=[
            *calculo.pendencias,
            *calculo.avisos,
        ],
        secoes=[comparativo, detalhamento, romaneio],
    )


# --------------------------------------------------------------------------
# Comissão, fretes e quebra (F5-16)
# --------------------------------------------------------------------------


def comissao_por_comprador(user, *, season, farm, start=None, end=None) -> Relatorio:
    """A comissão **gravada na operação** (snapshot), não a do cadastro de hoje."""
    qs = _compromissos(user, season=season, farm=farm).filter(commission__isnull=False)
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)

    linhas = []
    for c in qs.order_by("commissioned__name", "date", "id"):
        calculo = calcular_acerto(c)
        comissao = commitments.comissao_do(c)
        recebidos = [i for i in calculo.itens if i.recebido]
        machos = sum(
            i.cabecas_recebidas for i in recebidos if i.item.category.sex == Sex.MACHO
        )
        femeas = sum(
            i.cabecas_recebidas for i in recebidos if i.item.category.sex == Sex.FEMEA
        )
        acerto = calculo.settlement
        if acerto is None or acerto.status == Status.EXCLUIDA:
            situacao = "Sem acerto"
        else:
            situacao = (
                "Aprovado" if acerto.status == Status.CONFIRMADA else "Em andamento"
            )
        linhas.append(
            {
                "comprador": (
                    comissao.payee.name
                    if comissao.payee_id
                    else (c.commissioned.name if c.commissioned_id else None)
                ),
                "compromisso": c.code,
                "data": _data(
                    acerto.date
                    if acerto and acerto.status != Status.EXCLUIDA
                    else c.date
                ),
                "pecuarista": c.seller.name,
                "machos": machos if recebidos else None,
                "femeas": femeas if recebidos else None,
                "cabecas": calculo.cabecas_recebidas or None,
                "regra": _regra_em_texto(comissao),
                "comissao": calculo.comissao_total if recebidos else None,
                "situacao": situacao,
            }
        )
    return Relatorio(
        titulo="Comissão por comprador",
        descricao="Por comprador: o que cada compromisso rende de comissão, pela regra gravada nele.",
        colunas=[
            Coluna("comprador", "Comprador"),
            Coluna("compromisso", "Compromisso"),
            Coluna("data", "Data"),
            Coluna("pecuarista", "Pecuarista"),
            Coluna("machos", "Machos", INTEIRO),
            Coluna("femeas", "Fêmeas", INTEIRO),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("regra", "Regra gravada"),
            Coluna("comissao", "Comissão", DINHEIRO),
            Coluna("situacao", "Acerto"),
        ],
        linhas=linhas,
        totais={
            "comprador": "Total",
            "machos": sum(lin["machos"] or 0 for lin in linhas),
            "femeas": sum(lin["femeas"] or 0 for lin in linhas),
            "cabecas": sum(lin["cabecas"] or 0 for lin in linhas),
            "comissao": sum(
                (lin["comissao"] for lin in linhas if lin["comissao"]), ZERO
            ),
        },
        filtros=[*_contexto(season, farm), *_filtro_de_periodo(start, end)],
        notas=[
            "A regra é a gravada no compromisso na aprovação: mudar o cadastro "
            'depois não altera este relatório. "—" = ainda não há animal recebido.',
        ],
    )


def fretes_e_quebra(user, *, season, farm, start=None, end=None) -> Relatorio:
    viagens = Trip.objects.for_user(user).exclude(status=Status.EXCLUIDA)
    viagens = viagens.filter(commitment__status=Status.CONFIRMADA).select_related(
        "commitment__destination_farm", "carrier"
    )
    if season is not None:
        viagens = viagens.filter(commitment__season=season)
    if farm is not None:
        viagens = viagens.filter(commitment__destination_farm=farm)
    if start:
        viagens = viagens.filter(pickup_date__gte=start)
    if end:
        viagens = viagens.filter(pickup_date__lte=end)

    linhas = []
    for v in viagens.order_by("pickup_date", "id"):
        recebimento = v.receivings.exclude(status=Status.EXCLUIDA).first()
        frete = trips.frete_da_viagem(v)
        quebra = receivings.quebra_da_viagem(recebimento) if recebimento else None
        diferenca = (
            frete.realizado - frete.previsto
            if frete.realizado is not None and frete.previsto is not None
            else None
        )
        linhas.append(
            {
                "retirada": _data(v.pickup_date),
                "viagem": v.code,
                "compromisso": v.commitment.code,
                "transportador": v.carrier.name if v.carrier_id else None,
                "cabecas": trips.cabecas_da_viagem(v),
                "distancia": v.distance_km,
                "previsto": frete.previsto,
                "realizado": frete.realizado,
                "diferenca": diferenca,
                "origem": quebra.peso_origem_kg if quebra else None,
                "recebido": quebra.peso_recebido_kg if quebra else None,
                "quebra": quebra.quebra_percentual if quebra else None,
                "alerta": (
                    "Acima do limite"
                    if quebra and quebra.acima_do_limite
                    else ("Dentro do limite" if quebra else None)
                ),
            }
        )
    return Relatorio(
        titulo="Fretes e quebra de viagem",
        descricao="Por viagem: frete previsto × realizado e a quebra de peso entre a origem e a chegada.",
        colunas=[
            Coluna("retirada", "Retirada"),
            Coluna("viagem", "Viagem"),
            Coluna("compromisso", "Compromisso"),
            Coluna("transportador", "Transportador"),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("distancia", "Distância (km)", INTEIRO),
            Coluna("previsto", "Frete previsto", DINHEIRO),
            Coluna("realizado", "Frete realizado", DINHEIRO),
            Coluna("diferenca", "Diferença", DINHEIRO),
            Coluna("origem", "Peso de origem (kg)", NUMERO),
            Coluna("recebido", "Peso recebido (kg)", NUMERO),
            Coluna("quebra", "Quebra", PERCENTUAL),
            Coluna("alerta", "Limite"),
        ],
        linhas=linhas,
        totais={
            "retirada": "Total",
            "cabecas": sum(lin["cabecas"] for lin in linhas),
            "previsto": sum(
                (lin["previsto"] for lin in linhas if lin["previsto"]), ZERO
            ),
            "realizado": sum(
                (lin["realizado"] for lin in linhas if lin["realizado"] is not None),
                ZERO,
            ),
        },
        filtros=[*_contexto(season, farm), *_filtro_de_periodo(start, end)],
        notas=[
            'A quebra só mede: não desconta nada do valor dos animais. "—" = falta '
            "o peso de origem ou o recebido, ou o frete ainda não foi cobrado.",
        ],
    )


# --------------------------------------------------------------------------
# Histórico por pecuarista e programado × realizado (F5-17)
# --------------------------------------------------------------------------


def historico_por_pecuarista(user, *, season, farm, start=None, end=None) -> Relatorio:
    """Só acerto aprovado: o que virou compra. R$/@ e custo/@ só existem para
    quem vendeu por @ de carcaça."""
    acertos = (
        Settlement.objects.for_user(user)
        .filter(status=Status.CONFIRMADA)
        .select_related("commitment__seller", "commitment__destination_farm")
    )
    if season is not None:
        acertos = acertos.filter(commitment__season=season)
    if farm is not None:
        acertos = acertos.filter(commitment__destination_farm=farm)
    if start:
        acertos = acertos.filter(date__gte=start)
    if end:
        acertos = acertos.filter(date__lte=end)

    linhas = []
    for a in acertos.order_by("commitment__seller__name", "date", "id"):
        c = a.commitment
        calculo = calcular_acerto(c)
        recebidos = [i for i in calculo.itens if i.recebido]
        so_arroba = bool(recebidos) and all(
            i.base == PriceBasis.ARROBA for i in recebidos
        )
        arrobas = (
            sum((i.romaneio.arrobas for i in recebidos if i.romaneio), ZERO)
            if so_arroba
            else None
        )
        peso_carcaca = (
            sum((i.romaneio.peso_kg for i in recebidos if i.romaneio), ZERO)
            if so_arroba
            else None
        )
        linhas.append(
            {
                "pecuarista": c.seller.name,
                "acerto": a.code,
                "data": _data(a.date),
                "cidade": c.origin_city or None,
                "pagamento": f"{c.payment_days} dias" if c.payment_days else "à vista",
                "cabecas": calculo.cabecas_recebidas,
                "peso": peso_carcaca,
                "media_arrobas": safe_div(arrobas, calculo.cabecas_recebidas),
                "valor": calculo.valor_dos_animais,
                "comissao": calculo.comissao_total,
                "frete": calculo.frete,
                "distancia": c.distance_km,
                "preco_arroba": safe_div(calculo.valor_dos_animais, arrobas),
                "custo_arroba": safe_div(calculo.custo_aquisicao, arrobas),
            }
        )
    return Relatorio(
        titulo="Histórico por pecuarista",
        descricao="Cada acerto aprovado: cabeças, @, valor, comissão, frete, distância, R$/@ e custo/@.",
        colunas=[
            Coluna("pecuarista", "Pecuarista"),
            Coluna("acerto", "Acerto"),
            Coluna("data", "Data"),
            Coluna("cidade", "Cidade"),
            Coluna("pagamento", "Pagamento"),
            Coluna("cabecas", "Cabeças", INTEIRO),
            Coluna("peso", "Carcaça (kg)", NUMERO),
            Coluna("media_arrobas", "Média @", NUMERO),
            Coluna("valor", "Valor dos animais", DINHEIRO),
            Coluna("comissao", "Comissão", DINHEIRO),
            Coluna("frete", "Frete", DINHEIRO),
            Coluna("distancia", "Distância (km)", INTEIRO),
            Coluna("preco_arroba", "R$/@", DINHEIRO),
            Coluna("custo_arroba", "Custo/@", DINHEIRO),
        ],
        linhas=linhas,
        totais={
            "pecuarista": "Total",
            "cabecas": sum(lin["cabecas"] for lin in linhas),
            "valor": sum((lin["valor"] for lin in linhas), ZERO),
            "comissao": sum((lin["comissao"] for lin in linhas), ZERO),
            "frete": sum((lin["frete"] for lin in linhas), ZERO),
        },
        filtros=[*_contexto(season, farm), *_filtro_de_periodo(start, end)],
        notas=[
            "R$/@ e custo/@ só existem quando todos os itens foram vendidos por @ de "
            'carcaça (com romaneio); por cabeça, ficam em "—". O período filtra a '
            "data do acerto.",
        ],
    )


def _porque_nao(dados) -> str | None:
    motivos = []
    if not dados.recebido:
        motivos.append("sem recebimento")
    if dados.base == PriceBasis.ARROBA and dados.recebido and dados.romaneio is None:
        motivos.append("sem romaneio")
    if dados.valor_previsto is None:
        motivos.append(
            "sem média @ e faixa esperada"
            if dados.base == PriceBasis.ARROBA
            else "sem preço por cabeça"
        )
    if dados.peso_previsto_kg is None:
        motivos.append("sem peso médio previsto")
    if dados.recebido and dados.peso_recebido_kg is None:
        motivos.append("sem peso recebido")
    return "; ".join(motivos) or None


def programado_x_realizado(user, *, season, farm, start=None, end=None) -> Relatorio:
    """Onde a operação divergiu do previsto. É o relatório que a Fase 3 deixou
    de fora por falta de fonte: o "programado" é o compromisso."""
    qs = _compromissos(user, season=season, farm=farm)
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)

    linhas = []
    for c in qs.order_by("date", "id"):
        calculo = calcular_acerto(c)
        viagens = list(selectors.viagens_ativas(c))
        primeira = min((v.pickup_date for v in viagens), default=None)
        for d in calculo.itens:
            diferenca = (
                d.cabecas_recebidas - d.cabecas_previstas if d.recebido else None
            )
            linhas.append(
                {
                    "compromisso": c.code,
                    "produtor": c.seller.name,
                    "item": f"{d.item.number} · {d.item.category.name}",
                    "previstas": d.cabecas_previstas,
                    "recebidas": d.cabecas_recebidas if d.recebido else None,
                    "diferenca": diferenca,
                    "peso_previsto": d.peso_previsto_kg,
                    "peso_recebido": d.peso_recebido_kg,
                    "preco_previsto": d.preco_previsto,
                    "preco_realizado": d.preco_realizado,
                    "valor_previsto": d.valor_previsto,
                    "valor_realizado": d.valor_do_item,
                    "retirada_prevista": _data(c.pickup_date),
                    "retirada_real": _data(primeira),
                    "porque": _porque_nao(d),
                }
            )
    return Relatorio(
        titulo="Programado × realizado",
        descricao="Por item de compromisso aprovado: o que estava previsto e o que de fato aconteceu.",
        colunas=[
            Coluna("compromisso", "Compromisso"),
            Coluna("produtor", "Produtor"),
            Coluna("item", "Item"),
            Coluna("previstas", "Cabeças previstas", INTEIRO),
            Coluna("recebidas", "Cabeças recebidas", INTEIRO),
            Coluna("diferenca", "Diferença", INTEIRO),
            Coluna("peso_previsto", "Peso previsto (kg)", NUMERO),
            Coluna("peso_recebido", "Peso recebido (kg)", NUMERO),
            Coluna("preco_previsto", "Preço previsto", DINHEIRO),
            Coluna("preco_realizado", "Preço realizado", DINHEIRO),
            Coluna("valor_previsto", "Valor previsto", DINHEIRO),
            Coluna("valor_realizado", "Valor realizado", DINHEIRO),
            Coluna("retirada_prevista", "Retirada prevista"),
            Coluna("retirada_real", "Retirada real"),
            Coluna("porque", "Por que há —"),
        ],
        linhas=linhas,
        totais={
            "compromisso": "Total",
            "previstas": sum(lin["previstas"] for lin in linhas),
            "recebidas": sum(lin["recebidas"] or 0 for lin in linhas),
        },
        filtros=[*_contexto(season, farm), *_filtro_de_periodo(start, end)],
        notas=[
            "Preço e valor, previstos e realizados, estão na base de cada item (por @ "
            "de carcaça ou por cabeça). O período filtra a data do compromisso.",
        ],
    )
