"""O acerto: previsto × realizado e o consolidado até o líquido.

**Tudo aqui é derivado** (regra 6): nada do que `calcular_acerto` devolve é
gravado. A aprovação grava os **efeitos** (as compras), e eles guardam os
números de quando foi aprovado; reabrir o acerto os desfaz.

Duas decisões isoladas aqui, ambas com pendência aberta e padrão reversível:

- `TRATAMENTO_POR_NATUREZA` — o que cada natureza de linha faz com o dinheiro
  (#21, aguarda o contador);
- `ratear_extras` — como o frete, a comissão e os tributos do contrato inteiro
  se dividem entre os itens que viram compras (#22).
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Min

from apps.commercial.commission import calcular_comissao
from apps.commercial.models import TaxNature
from apps.core.money import quantize_money, safe_div
from apps.core.reversible import Status
from apps.costs.allocation import ratear_em_centavos
from apps.procurement import selectors
from apps.procurement.grading import Romaneio, romaneio_do_item
from apps.procurement.models import (
    Commission,
    Commitment,
    CommitmentItem,
    PriceBasis,
    ReceivingLine,
    SettlementLine,
)
from apps.procurement.trips import frete_da_viagem

ZERO = Decimal("0")


class Tratamento:
    #: soma ao custo de aquisição (`tax_value`) e vira título de impostos
    CUSTO = "CUSTO"
    #: reduz o valor dos animais (custo **e** pagamento)
    DESCONTO_NO_ANIMAL = "DESCONTO_NO_ANIMAL"
    #: reduz só o líquido a pagar ao vendedor; o custo não muda
    ABATE_NO_LIQUIDO = "ABATE_NO_LIQUIDO"


#: Pendência #21 — hipótese, não regra: aguarda o contador e o produtor.
TRATAMENTO_POR_NATUREZA = {
    TaxNature.TRIBUTO: Tratamento.CUSTO,
    TaxNature.TAXA: Tratamento.CUSTO,
    TaxNature.DESCONTO: Tratamento.DESCONTO_NO_ANIMAL,
    TaxNature.ADIANTAMENTO: Tratamento.ABATE_NO_LIQUIDO,
    TaxNature.CREDITO: Tratamento.ABATE_NO_LIQUIDO,
}


# --------------------------------------------------------------------------
# Estruturas
# --------------------------------------------------------------------------


@dataclass
class ItemDoAcerto:
    item: CommitmentItem
    cabecas_previstas: int
    cabecas_programadas: int | None
    cabecas_embarcadas: int | None
    cabecas_recebidas: int
    peso_previsto_kg: Decimal | None
    peso_recebido_kg: Decimal | None
    categoria_prevista: str
    categorias_recebidas: list[str]
    base: str
    preco_previsto: Decimal | None
    preco_realizado: Decimal | None
    valor_previsto: Decimal | None
    romaneio: Romaneio | None
    #: o que os animais valem: líquido do romaneio ou cabeças × preço
    valor_do_item: Decimal | None
    primeiro_recebimento: datetime.date | None
    pendencias: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def recebido(self) -> bool:
        return self.cabecas_recebidas > 0


@dataclass(frozen=True)
class RateioDoItem:
    """O que a `Purchase` do item recebe do acerto."""

    animal_value: Decimal
    freight_value: Decimal
    commission_value: Decimal
    tax_value: Decimal
    #: adiantamentos e créditos que cabem a este item (só abatem o pagamento)
    abatimento: Decimal

    @property
    def titulo_dos_animais(self) -> Decimal:
        return self.animal_value - self.abatimento


@dataclass(frozen=True)
class Comparacao:
    rotulo: str
    previsto: object
    realizado: object
    #: "numero", "dinheiro", "kg", "data" ou "texto" — a tela formata
    tipo: str


@dataclass
class Acerto:
    commitment: Commitment
    settlement: object
    itens: list[ItemDoAcerto]
    cabecas_recebidas: int
    valor_dos_itens: Decimal
    descontos: Decimal
    valor_dos_animais: Decimal
    frete: Decimal
    frete_previsto: Decimal | None
    frete_realizado: Decimal | None
    tributos: Decimal
    adiantamentos: Decimal
    creditos: Decimal
    comissao_calculada: Decimal | None
    comissao_extra: Decimal
    comissao_total: Decimal
    custo_aquisicao: Decimal
    liquido_ao_produtor: Decimal
    transportador: object
    favorecido_da_comissao: object
    rateios: dict[int, RateioDoItem]
    comparacoes: list[Comparacao]
    pendencias: list[str]
    avisos: list[str]

    @property
    def aprovavel(self) -> bool:
        return not self.pendencias


# --------------------------------------------------------------------------
# Rateio (pendência #22)
# --------------------------------------------------------------------------


def _ratear(total: Decimal, pesos: dict) -> dict:
    total = quantize_money(total)
    if not total:
        return {chave: ZERO for chave in pesos}
    rateado = ratear_em_centavos(total, pesos)
    return {chave: rateado.get(chave, ZERO) for chave in pesos}


def ratear_extras(
    itens: list[ItemDoAcerto],
    *,
    frete: Decimal,
    comissao: Decimal,
    tributos: Decimal,
    descontos: Decimal,
    abatimentos: Decimal,
) -> dict[int, RateioDoItem]:
    """Divide o que é do contrato inteiro entre os itens que viram compra.

    - frete, comissão e tributos: por **cabeça recebida**;
    - descontos: pelo **valor** dos animais — desconto de preço acompanha o preço;
    - adiantamentos e créditos: pelo valor dos animais **já descontado**.

    A soma dos pedaços é exatamente o total (`ratear_em_centavos`: o resto do
    arredondamento vai, um centavo por vez, para quem tem a maior fração).
    """
    if not itens:
        return {}
    por_cabeca = {i.item.pk: Decimal(i.cabecas_recebidas) for i in itens}
    por_valor = {i.item.pk: i.valor_do_item for i in itens}

    desconto_r = _ratear(descontos, por_valor)
    animais = {pk: por_valor[pk] - desconto_r[pk] for pk in por_valor}
    abatimento_r = _ratear(abatimentos, animais)
    frete_r = _ratear(frete, por_cabeca)
    comissao_r = _ratear(comissao, por_cabeca)
    tributos_r = _ratear(tributos, por_cabeca)
    return {
        pk: RateioDoItem(
            animal_value=animais[pk],
            freight_value=frete_r[pk],
            commission_value=comissao_r[pk],
            tax_value=tributos_r[pk],
            abatimento=abatimento_r[pk],
        )
        for pk in por_cabeca
    }


# --------------------------------------------------------------------------
# Cálculo
# --------------------------------------------------------------------------


def _linhas_recebidas(item: CommitmentItem) -> list[ReceivingLine]:
    return list(
        ReceivingLine.objects.filter(
            load__item=item,
            receiving__status=Status.CONFIRMADA,
            load__trip__status=Status.CONFIRMADA,
        ).select_related("receiving", "load", "received_category")
    )


def _item_do_acerto(item: CommitmentItem) -> ItemDoAcerto:
    cargas = [
        c
        for c in item.loads.select_related("trip")
        if c.trip.status == Status.CONFIRMADA
    ]
    recebidas = _linhas_recebidas(item)
    cabecas = sum(linha.received_qty for linha in recebidas)
    pesos = [linha.received_weight_kg for linha in recebidas]
    peso_recebido = (
        sum(pesos, ZERO) if recebidas and all(p is not None for p in pesos) else None
    )
    categorias = sorted(
        {
            linha.received_category.name
            for linha in recebidas
            if linha.received_category_id
            and linha.received_category_id != item.category_id
        }
    )

    base = item.price_basis
    romaneio = romaneio_do_item(item) if base == PriceBasis.ARROBA else None
    if romaneio is not None and not romaneio.linhas:
        romaneio = None

    pendencias, avisos = [], []
    rotulo = f"Item {item.number} ({item.category.name})"
    valor_do_item = None
    preco_realizado = None
    if base == PriceBasis.ARROBA:
        preco_previsto = item.preco_da_faixa(item.expected_band)
        valor_previsto = (
            quantize_money(
                Decimal(item.head_count) * item.expected_arrobas * preco_previsto
            )
            if item.expected_arrobas is not None and preco_previsto is not None
            else None
        )
        if cabecas and romaneio is None:
            pendencias.append(
                f"{rotulo} é precificado por @ e ainda não tem romaneio: lance a "
                "classificação de carcaça."
            )
        if romaneio is not None:
            valor_do_item = romaneio.liquido
            preco_realizado = romaneio.preco_medio_por_arroba
            if cabecas and romaneio.cabecas != cabecas:
                avisos.append(
                    f"{rotulo}: o romaneio tem {romaneio.cabecas} cabeças e foram "
                    f"recebidas {cabecas}."
                )
    else:
        preco_previsto = item.unit_price
        preco_realizado = item.unit_price
        valor_previsto = (
            quantize_money(Decimal(item.head_count) * item.unit_price)
            if item.unit_price is not None
            else None
        )
        if cabecas:
            if item.unit_price is None:
                pendencias.append(f"{rotulo} não tem preço por cabeça.")
            else:
                valor_do_item = quantize_money(Decimal(cabecas) * item.unit_price)

    programadas = [c.planned_qty for c in cargas]
    embarcadas = [c.shipped_qty for c in cargas if c.shipped_qty is not None]
    if (cargas or item.head_count) and not cabecas and cargas:
        avisos.append(f"{rotulo} foi programado, mas nada foi recebido.")
    if cabecas > item.head_count:
        avisos.append(
            f"{rotulo}: foram recebidas {cabecas} cabeças, acima das "
            f"{item.head_count} do compromisso."
        )
    if categorias:
        avisos.append(
            f"{rotulo}: chegou categoria diferente da prevista ({', '.join(categorias)})."
        )

    primeira = (
        min((linha.receiving.date for linha in recebidas), default=None)
        if recebidas
        else None
    )
    return ItemDoAcerto(
        item=item,
        cabecas_previstas=item.head_count,
        cabecas_programadas=sum(programadas) if cargas else None,
        cabecas_embarcadas=sum(embarcadas) if embarcadas else None,
        cabecas_recebidas=cabecas,
        peso_previsto_kg=(
            Decimal(item.head_count) * item.avg_weight_kg
            if item.avg_weight_kg is not None
            else None
        ),
        peso_recebido_kg=peso_recebido,
        categoria_prevista=item.category.name,
        categorias_recebidas=categorias,
        base=base,
        preco_previsto=preco_previsto,
        preco_realizado=preco_realizado,
        valor_previsto=valor_previsto,
        romaneio=romaneio,
        valor_do_item=valor_do_item,
        primeiro_recebimento=primeira,
        pendencias=pendencias,
        avisos=avisos,
    )


def _soma_ou_none(valores) -> Decimal | None:
    valores = list(valores)
    return (
        sum(valores, ZERO) if valores and all(v is not None for v in valores) else None
    )


def calcular_acerto(commitment: Commitment) -> Acerto:
    settlement = selectors.acerto_vigente(commitment)
    linhas = (
        list(
            SettlementLine.objects.filter(settlement=settlement).select_related(
                "tax_type"
            )
        )
        if settlement is not None
        else []
    )

    itens = [
        _item_do_acerto(i)
        for i in commitment.items.select_related("category").order_by("number")
    ]
    recebidos = [i for i in itens if i.recebido]
    pendencias = [p for i in itens for p in i.pendencias]
    avisos = [a for i in itens for a in i.avisos]

    if commitment.status != Status.CONFIRMADA:
        pendencias.append("o compromisso ainda não foi aprovado.")
    if not recebidos:
        pendencias.append(
            "nenhum animal foi recebido ainda: lance o recebimento das viagens."
        )

    # ---- linhas digitadas, pelo tratamento da natureza -------------------
    def _soma(tratamento, naturezas=None):
        return sum(
            (
                linha.amount
                for linha in linhas
                if TRATAMENTO_POR_NATUREZA[linha.tax_type.nature] == tratamento
                and (naturezas is None or linha.tax_type.nature in naturezas)
            ),
            ZERO,
        )

    tributos = _soma(Tratamento.CUSTO)
    descontos = _soma(Tratamento.DESCONTO_NO_ANIMAL)
    adiantamentos = _soma(Tratamento.ABATE_NO_LIQUIDO, {TaxNature.ADIANTAMENTO})
    creditos = _soma(Tratamento.ABATE_NO_LIQUIDO, {TaxNature.CREDITO})

    # ---- frete: o realizado quando existe; sem ele, o previsto -----------
    viagens = list(selectors.viagens_ativas(commitment).select_related("carrier"))
    fretes = [(v, frete_da_viagem(v)) for v in viagens]
    frete = sum((f.final for _, f in fretes if f.final is not None), ZERO)
    previstos = [f.previsto for _, f in fretes if f.previsto is not None]
    realizados = [f.realizado for _, f in fretes if f.realizado is not None]
    for viagem, f in fretes:
        if f.origem == "previsto":
            avisos.append(
                f"Viagem {viagem.code}: frete realizado não informado; "
                "usando o previsto."
            )
    transportadores = {v.carrier_id: v.carrier for v, f in fretes if f.final}
    transportador = None
    if len(transportadores) == 1 and None not in transportadores:
        transportador = next(iter(transportadores.values()))
    elif len(transportadores) > 1:
        avisos.append(
            "O frete tem mais de um transportador: o título de frete fica sem "
            "favorecido, para o financeiro completar."
        )

    # ---- valor dos animais -----------------------------------------------
    valor_dos_itens = sum((i.valor_do_item for i in recebidos if i.valor_do_item), ZERO)
    valor_dos_animais = valor_dos_itens - descontos
    if recebidos and valor_dos_animais <= 0 and valor_dos_itens > 0:
        pendencias.append("os descontos passam do valor dos animais.")
    if adiantamentos + creditos > valor_dos_animais > 0:
        pendencias.append(
            "os adiantamentos e créditos passam do valor dos animais: "
            "não sobra nada a pagar ao vendedor."
        )

    # ---- comissão: do snapshot, sobre o que o acerto apurou ---------------
    cabecas = sum(i.cabecas_recebidas for i in recebidos)
    obj = (
        Commission.objects.filter(commitment=commitment).select_related("payee").first()
    )
    comissao_calculada = None
    extra = ZERO
    if obj is not None:
        extra = obj.extra_amount
        comissao_calculada = calcular_comissao(
            tipo=obj.type,
            base=obj.base,
            valor=obj.value,
            valor_bruto=valor_dos_animais if recebidos else None,
            deducoes=frete + tributos,
            cabecas=cabecas,
        )
    elif recebidos:
        avisos.append("Sem comissão: nenhuma regra valia na aprovação do compromisso.")
    comissao_total = (comissao_calculada or ZERO) + extra

    rateios: dict[int, RateioDoItem] = {}
    if recebidos and not any(i.valor_do_item is None for i in recebidos):
        rateios = ratear_extras(
            recebidos,
            frete=frete,
            comissao=comissao_total,
            tributos=tributos,
            descontos=descontos,
            abatimentos=adiantamentos + creditos,
        )
        for pk, rateio in rateios.items():
            if rateio.animal_value <= 0 or rateio.titulo_dos_animais <= 0:
                pendencias.append(
                    "os descontos, adiantamentos e créditos deixam um item sem valor."
                )
                break

    custo = valor_dos_animais + frete + tributos + comissao_total
    liquido = valor_dos_animais - adiantamentos - creditos

    # ---- previsto × realizado --------------------------------------------
    previsto_total = _soma_ou_none(i.valor_previsto for i in itens)
    primeira_viagem = min((v.pickup_date for v in viagens), default=None)
    comparacoes = [
        Comparacao(
            "Cabeças",
            sum(i.cabecas_previstas for i in itens),
            cabecas if recebidos else None,
            "numero",
        ),
        Comparacao(
            "Peso (kg)",
            _soma_ou_none(i.peso_previsto_kg for i in itens),
            _soma_ou_none(i.peso_recebido_kg for i in recebidos) if recebidos else None,
            "kg",
        ),
        Comparacao(
            "Categoria",
            ", ".join(sorted({i.categoria_prevista for i in itens})),
            (
                "; ".join(
                    f"{i.categoria_prevista} → {', '.join(i.categorias_recebidas)}"
                    for i in recebidos
                    if i.categorias_recebidas
                )
                or ("Conforme o previsto" if recebidos else None)
            ),
            "texto",
        ),
        Comparacao(
            "Valor dos animais",
            previsto_total,
            valor_dos_animais if recebidos and valor_dos_itens else None,
            "dinheiro",
        ),
        Comparacao(
            "Frete",
            sum(previstos, ZERO) if previstos else None,
            sum(realizados, ZERO) if realizados else None,
            "dinheiro",
        ),
        Comparacao("Data da retirada", commitment.pickup_date, primeira_viagem, "data"),
    ]

    return Acerto(
        commitment=commitment,
        settlement=settlement,
        itens=itens,
        cabecas_recebidas=cabecas,
        valor_dos_itens=valor_dos_itens,
        descontos=descontos,
        valor_dos_animais=valor_dos_animais,
        frete=frete,
        frete_previsto=sum(previstos, ZERO) if previstos else None,
        frete_realizado=sum(realizados, ZERO) if realizados else None,
        tributos=tributos,
        adiantamentos=adiantamentos,
        creditos=creditos,
        comissao_calculada=comissao_calculada,
        comissao_extra=extra,
        comissao_total=comissao_total,
        custo_aquisicao=custo,
        liquido_ao_produtor=liquido,
        transportador=transportador,
        favorecido_da_comissao=obj.payee if obj is not None else None,
        rateios=rateios,
        comparacoes=comparacoes,
        pendencias=pendencias,
        avisos=avisos,
    )


def preco_medio_por_cabeca(acerto: Acerto) -> Decimal | None:
    return safe_div(acerto.valor_dos_animais, acerto.cabecas_recebidas)


# --------------------------------------------------------------------------
# Ponte com o financeiro
# --------------------------------------------------------------------------


def ajustes_financeiros_da_compra(compra) -> dict:
    """O que o acerto muda nos títulos da compra que ele gerou: o **favorecido**
    do frete e da comissão (que, na compra direta, ficam "a definir") e o valor
    do título dos animais, que sai **líquido** de adiantamentos e créditos.

    Devolve `{}` para a compra que não nasceu de um acerto — a compra direta
    segue exatamente como era.
    """
    item = getattr(compra, "commitment_item", None)
    if item is None:
        return {}
    acerto = calcular_acerto(item.commitment)
    rateio = acerto.rateios.get(item.pk)
    ajustes = {
        "FRETE": {"payee": acerto.transportador},
        "COMISSAO": {"payee": acerto.favorecido_da_comissao},
    }
    if rateio is not None:
        ajustes["ANIMAIS"] = {"amount": rateio.titulo_dos_animais}
    return ajustes


def primeiro_recebimento_do_item(item: CommitmentItem) -> datetime.date | None:
    return ReceivingLine.objects.filter(
        load__item=item,
        receiving__status=Status.CONFIRMADA,
        load__trip__status=Status.CONFIRMADA,
    ).aggregate(d=Min("receiving__date"))["d"]
