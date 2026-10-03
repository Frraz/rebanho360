"""O acerto: previsto × realizado e o consolidado até o líquido.

**Tudo aqui é derivado** (regra 6): nada do que `calcular_acerto` devolve é
gravado. A aprovação grava os **efeitos** (as compras e os títulos), e eles
guardam os números de quando foi aprovado; reabrir o acerto os desfaz.

O cliente (2026-10-03) pediu um sistema de **registro**, não de dedução:

- os valores de tributos, taxas e descontos são **digitados** (alíquota e base
  são só campos auxiliares);
- **não há rateio automático** (#13): com mais de um item recebido, o usuário
  informa quanto do frete, da comissão, dos tributos, dos descontos e dos
  adiantamentos é de cada item (`SettlementAllocation`), e o acerto só é
  aprovado quando a soma fecha com o total. `sugerir_distribuicao` existe só
  para pré-preencher a tela — quem confirma é o usuário;
- cada comprador tem a sua comissão (#30), calculada sobre o valor bruto dos
  animais ou informada direto (#4).

Uma decisão isolada aqui, com pendência aberta e padrão reversível:
`TRATAMENTO_POR_NATUREZA` — o que cada natureza de linha faz com o dinheiro,
quando o tipo não define o próprio efeito (#21).
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Min

from apps.commercial.commission import calcular_comissao
from apps.commercial.models import TaxNature
from apps.core.formatting import dinheiro_br
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
    SettlementAllocation,
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


def efeito_da_linha(linha: SettlementLine) -> str:
    """O que o valor da linha faz: o efeito definido no **tipo** (o usuário
    decide, não o sistema) ou, sem ele, o padrão da natureza."""
    return linha.tax_type.effect or TRATAMENTO_POR_NATUREZA[linha.tax_type.nature]


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
class ComissaoDoComprador:
    """A comissão de um comprador no acerto: o que o snapshot dá e o extra."""

    commission: Commission
    calculada: Decimal | None
    extra: Decimal

    @property
    def total(self) -> Decimal:
        return (self.calculada or ZERO) + self.extra

    @property
    def payee(self):
        return self.commission.payee


@dataclass(frozen=True)
class FreteDaViagemNoAcerto:
    viagem: object
    valor: Decimal
    favorecido: object
    vencimento: datetime.date | None


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
    comissoes: list[ComissaoDoComprador]
    fretes: list[FreteDaViagemNoAcerto]
    linhas: list
    custo_aquisicao: Decimal
    liquido_ao_produtor: Decimal
    transportador: object
    favorecido_da_comissao: object
    #: o que falta distribuir entre os itens (só com mais de um item recebido)
    distribuicao_pendente: dict
    rateios: dict[int, RateioDoItem]
    comparacoes: list[Comparacao]
    pendencias: list[str]
    avisos: list[str]

    @property
    def aprovavel(self) -> bool:
        return not self.pendencias


# --------------------------------------------------------------------------
# Distribuição entre itens (pendência #22 / cliente 2026-10-03: sem rateio
# automático)
# --------------------------------------------------------------------------

#: Os totais do acerto que, com mais de um item, o usuário reparte à mão —
#: campo da `SettlementAllocation` → rótulo na mensagem.
TOTAIS_A_DISTRIBUIR = (
    ("discount_value", "Descontos"),
    ("abatement_value", "Adiantamentos e créditos"),
    ("freight_value", "Frete"),
    ("commission_value", "Comissão"),
    ("tax_value", "Tributos e taxas"),
)


def _ratear(total: Decimal, pesos: dict) -> dict:
    total = quantize_money(total)
    if not total:
        return {chave: ZERO for chave in pesos}
    rateado = ratear_em_centavos(total, pesos)
    return {chave: rateado.get(chave, ZERO) for chave in pesos}


def sugerir_distribuicao(
    itens: list[ItemDoAcerto],
    *,
    frete: Decimal,
    comissao: Decimal,
    tributos: Decimal,
    descontos: Decimal,
    abatimentos: Decimal,
) -> dict[int, dict[str, Decimal]]:
    """**Só uma sugestão** para pré-preencher a tela de distribuição: por cabeça
    recebida (frete, comissão, tributos) e por valor (descontos e abatimentos),
    sem centavo perdido. O sistema **não aplica** isso sozinho: a distribuição
    só vale depois que o usuário a confirma e salva.
    """
    if not itens:
        return {}
    por_cabeca = {i.item.pk: Decimal(i.cabecas_recebidas) for i in itens}
    por_valor = {i.item.pk: (i.valor_do_item or ZERO) for i in itens}
    desconto_r = _ratear(descontos, por_valor)
    animais = {pk: por_valor[pk] - desconto_r[pk] for pk in por_valor}
    abatimento_r = _ratear(abatimentos, animais)
    frete_r = _ratear(frete, por_cabeca)
    comissao_r = _ratear(comissao, por_cabeca)
    tributos_r = _ratear(tributos, por_cabeca)
    return {
        pk: {
            "discount_value": desconto_r[pk],
            "abatement_value": abatimento_r[pk],
            "freight_value": frete_r[pk],
            "commission_value": comissao_r[pk],
            "tax_value": tributos_r[pk],
        }
        for pk in por_cabeca
    }


def distribuicao_informada(
    itens: list[ItemDoAcerto],
    alocacoes: dict[int, SettlementAllocation],
    totais: dict[str, Decimal],
) -> tuple[dict[int, dict[str, Decimal]], dict[str, Decimal]]:
    """O que cada item recebe de cada total, e quanto **falta** distribuir.

    Com **um** item recebido não há o que repartir: ele fica com tudo.
    Com mais de um, vale o que o usuário informou; `falta[campo]` é o total
    menos a soma informada (positivo = falta, negativo = passou). Total zero
    nunca falta.
    """
    if len(itens) == 1:
        pk = itens[0].item.pk
        return {pk: dict(totais)}, {}
    distribuicao = {}
    for i in itens:
        a = alocacoes.get(i.item.pk)
        distribuicao[i.item.pk] = {
            campo: (getattr(a, campo) if a is not None else ZERO)
            for campo, _ in TOTAIS_A_DISTRIBUIR
        }
    falta = {}
    for campo, _ in TOTAIS_A_DISTRIBUIR:
        informado = sum((d[campo] for d in distribuicao.values()), ZERO)
        diferenca = quantize_money(totais[campo] - informado)
        if diferenca:
            falta[campo] = diferenca
    return distribuicao, falta


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

    # ---- linhas digitadas, pelo efeito definido no tipo ou na natureza ----
    def _soma(tratamento, naturezas=None):
        return sum(
            (
                linha.amount
                for linha in linhas
                if efeito_da_linha(linha) == tratamento
                and (naturezas is None or linha.tax_type.nature in naturezas)
            ),
            ZERO,
        )

    tributos = _soma(Tratamento.CUSTO)
    descontos = _soma(Tratamento.DESCONTO_NO_ANIMAL)
    adiantamentos = _soma(Tratamento.ABATE_NO_LIQUIDO, {TaxNature.ADIANTAMENTO})
    creditos = _soma(Tratamento.ABATE_NO_LIQUIDO, {TaxNature.CREDITO})
    # Efeito de abatimento em tipo que não é adiantamento nem crédito (o usuário
    # escolheu o efeito no tipo): entra no mesmo balde dos abatimentos.
    creditos += sum(
        (
            linha.amount
            for linha in linhas
            if efeito_da_linha(linha) == Tratamento.ABATE_NO_LIQUIDO
            and linha.tax_type.nature not in (TaxNature.ADIANTAMENTO, TaxNature.CREDITO)
        ),
        ZERO,
    )

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
    # O frete é pago ao transportador **da viagem**, um título por viagem, com
    # vencimento próprio (cliente, 2026-10-03). Viagem com frete e sem
    # transportador gera título sem favorecido, para completar.
    fretes_do_acerto = []
    for viagem, f in fretes:
        if not f.final:
            continue
        fretes_do_acerto.append(
            FreteDaViagemNoAcerto(
                viagem=viagem,
                valor=f.final,
                favorecido=viagem.carrier,
                vencimento=viagem.freight_due_date,
            )
        )
        if viagem.carrier_id is None:
            avisos.append(
                f"Viagem {viagem.code}: tem frete e não tem transportador; o "
                "título de frete fica sem favorecido."
            )
    transportadores = {v.carrier_id: v.carrier for v, f in fretes if f.final}
    transportador = (
        next(iter(transportadores.values()))
        if len(transportadores) == 1 and None not in transportadores
        else None
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

    # ---- comissão: uma por comprador, do snapshot, sobre o valor bruto ----
    cabecas = sum(i.cabecas_recebidas for i in recebidos)
    comissoes = []
    for obj in (
        Commission.objects.filter(commitment=commitment)
        .select_related("payee")
        .order_by("position", "id")
    ):
        comissoes.append(
            ComissaoDoComprador(
                commission=obj,
                calculada=calcular_comissao(
                    tipo=obj.type,
                    base=obj.base,
                    valor=obj.value,
                    valor_bruto=valor_dos_animais if recebidos else None,
                    deducoes=frete + tributos,
                    cabecas=cabecas,
                ),
                extra=obj.extra_amount,
            )
        )
    if not comissoes and recebidos:
        avisos.append("Sem comissão: nenhuma regra valia na aprovação do compromisso.")
    for c in comissoes:
        if c.payee is None and c.total:
            avisos.append(
                "Há comissão sem comprador definido: o título fica sem favorecido."
            )
    comissao_calculada = (
        sum((c.calculada or ZERO) for c in comissoes) if comissoes else None
    )
    extra = sum((c.extra for c in comissoes), ZERO)
    comissao_total = sum((c.total for c in comissoes), ZERO)

    # ---- distribuição entre os itens: informada, nunca deduzida -----------
    rateios: dict[int, RateioDoItem] = {}
    distribuicao_pendente: dict[str, Decimal] = {}
    if recebidos and not any(i.valor_do_item is None for i in recebidos):
        alocacoes = (
            {
                a.item_id: a
                for a in SettlementAllocation.objects.filter(settlement=settlement)
            }
            if settlement is not None
            else {}
        )
        totais = {
            "discount_value": descontos,
            "abatement_value": adiantamentos + creditos,
            "freight_value": frete,
            "commission_value": comissao_total,
            "tax_value": tributos,
        }
        distribuicao, distribuicao_pendente = distribuicao_informada(
            recebidos, alocacoes, totais
        )
        for campo, rotulo in TOTAIS_A_DISTRIBUIR:
            falta = distribuicao_pendente.get(campo)
            if falta is None:
                continue
            if falta > 0:
                pendencias.append(
                    f"{rotulo} ({dinheiro_br(totais[campo])}): faltam "
                    f"{dinheiro_br(falta)} para distribuir entre os itens. "
                    "Informe quanto é de cada item."
                )
            else:
                pendencias.append(
                    f"a distribuição de {rotulo.lower()} entre os itens passa do "
                    f"total ({dinheiro_br(totais[campo])}) em {dinheiro_br(-falta)}."
                )
        rateios = {
            i.item.pk: RateioDoItem(
                animal_value=(i.valor_do_item or ZERO)
                - distribuicao[i.item.pk]["discount_value"],
                freight_value=distribuicao[i.item.pk]["freight_value"],
                commission_value=distribuicao[i.item.pk]["commission_value"],
                tax_value=distribuicao[i.item.pk]["tax_value"],
                abatimento=distribuicao[i.item.pk]["abatement_value"],
            )
            for i in recebidos
        }
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
        comissoes=comissoes,
        fretes=fretes_do_acerto,
        linhas=linhas,
        custo_aquisicao=custo,
        liquido_ao_produtor=liquido,
        transportador=transportador,
        favorecido_da_comissao=(comissoes[0].payee if comissoes else None),
        distribuicao_pendente=distribuicao_pendente,
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
    """O que o acerto muda nos títulos da compra que ele gerou.

    A compra de um acerto só gera o título **dos animais** — pelo valor
    **líquido** de adiantamentos e créditos. Frete, comissão e tributos têm
    título próprio, com favorecido e vencimento próprios, gerados pelo acerto
    (`finance.services.gerar_titulos_do_acerto`): `somente_animais` diz isso ao
    financeiro.

    Devolve `{}` para a compra que não nasceu de um acerto — a compra direta
    segue exatamente como era.
    """
    item = getattr(compra, "commitment_item", None)
    if item is None:
        return {}
    acerto = calcular_acerto(item.commitment)
    rateio = acerto.rateios.get(item.pk)
    ajustes = {"somente_animais": True}
    if rateio is not None:
        ajustes["ANIMAIS"] = {"amount": rateio.titulo_dos_animais}
    return ajustes


def primeiro_recebimento_do_item(item: CommitmentItem) -> datetime.date | None:
    return ReceivingLine.objects.filter(
        load__item=item,
        receiving__status=Status.CONFIRMADA,
        load__trip__status=Status.CONFIRMADA,
    ).aggregate(d=Min("receiving__date"))["d"]
