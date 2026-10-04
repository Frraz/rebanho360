"""Leitura. Consultas e agregações."""

from apps.livestock.models import AnimalCategory, Breed, Lot, LotStatus


def listar_categorias():
    return AnimalCategory.objects.all()


def listar_racas():
    return Breed.objects.all()


def listar_lotes_para(user):
    # Lote excluído (criado por uma compra que foi desfeita) sai da operação.
    return (
        Lot.objects.for_user(user)
        .exclude(status=LotStatus.EXCLUIDO)
        .select_related("farm", "season", "breed")
    )


def cabecas_que_entraram(lot: Lot) -> int:
    """Soma das linhas positivas do razão do lote: compra, saldo inicial,
    nascimento e entrada de transferência. Fonte única — a tela do lote e o
    resultado dele usam o mesmo número."""
    return cabecas_que_entraram_por_lote([lot]).get(lot.pk, 0)


def cabecas_que_entraram_por_lote(lots) -> dict:
    """`cabecas_que_entraram` de vários lotes numa só consulta: `{lot_id: n}`.
    Lote sem entrada não aparece; quem consulta usa `.get(pk, 0)`."""
    from django.db.models import Sum

    from apps.herd.models import HerdLedgerEntry

    ids = [lt.pk for lt in lots]
    return {
        lot_id: total or 0
        for lot_id, total in HerdLedgerEntry.objects.filter(
            lot_id__in=ids, quantity__gt=0
        )
        .values_list("lot_id")
        .annotate(total=Sum("quantity"))
        .order_by("lot_id")
    }


def financeiro_dos_lotes(lots, *, entradas=None, ate=None) -> dict:
    """Aquisição, custos diretos e rateados de vários lotes: `{lot_id: dict}`,
    cada dict igual ao de `financeiro_do_lote`. O que não tem dado fica `None`
    ("—" na tela), nunca zero:

        custo_total = aquisição + custos apropriados + custos rateados
                                             (docs/regras-negocio/05#custo)

    O número de consultas **não depende** de quantos lotes vêm: compras e
    custos diretos entram agrupados e o rateio lê o razão e os custos indiretos
    uma vez por fazenda (`BaseDeRateio`), não uma vez por lote e por centro.

    `entradas`: `{lot_id: cabeças que entraram}`; sem ele, calcula.
    """
    import datetime
    from collections import defaultdict
    from decimal import Decimal

    from django.db.models import Sum

    from apps.core.exceptions import BusinessError
    from apps.core.money import safe_div
    from apps.core.reversible import Status
    from apps.costs.allocation import BaseDeRateio
    from apps.costs.models import CostEntry
    from apps.purchases.models import Purchase
    from apps.purchases.services import calcular_custo_da_compra

    lots = list(lots)
    if not lots:
        return {}
    ids = [lt.pk for lt in lots]
    if entradas is None:
        entradas = cabecas_que_entraram_por_lote(lots)

    compras = defaultdict(list)
    for c in Purchase.objects.filter(lot_id__in=ids, status=Status.CONFIRMADA):
        compras[c.lot_id].append(c)

    # Os custos gerados pela compra já estão na aquisição: não contam duas vezes.
    diretos = dict(
        CostEntry.objects.filter(
            lot_id__in=ids, status=Status.CONFIRMADA, source_purchase=None
        )
        .values_list("lot_id")
        .annotate(total=Sum("amount"))
        .order_by("lot_id")
    )

    hoje = datetime.date.today()
    fim = {lt.pk: ate or lt.exit_date or hoje for lt in lots}
    por_fazenda = defaultdict(list)
    for lt in lots:
        por_fazenda[lt.farm_id].append(lt)
    rateios = {}  # lot_id → (RateioResultado | None, aviso | None)
    for grupo in por_fazenda.values():
        base = BaseDeRateio(grupo[0].farm, ate=max(fim[lt.pk] for lt in grupo))
        for lt in grupo:
            try:
                rateios[lt.pk] = (
                    base.ratear(start=lt.entry_date, end=fim[lt.pk]),
                    None,
                )
            except BusinessError as exc:
                rateios[lt.pk] = (None, f"Custo rateado indisponível: {exc}")

    saida = {}
    for lt in lots:
        aquisicao = None
        if compras[lt.pk]:
            aquisicao = sum(
                (
                    calcular_custo_da_compra(
                        head_count=c.head_count,
                        animal_value=c.animal_value,
                        freight_value=c.freight_value,
                        commission_value=c.commission_value,
                        tax_value=c.tax_value,
                    ).custo_aquisicao
                    for c in compras[lt.pk]
                ),
                Decimal("0"),
            )
        direto = diretos.get(lt.pk)

        rateados, criterios = None, []
        resultado, aviso_rateio = rateios[lt.pk]
        if resultado is not None:
            cota = resultado.cotas_por_lote.get(lt.pk)
            if cota:
                rateados = cota
                criterios = sorted(
                    {c.criterio_rotulo for c in resultado.centros if lt.pk in c.cotas}
                )

        partes = [x for x in (aquisicao, direto, rateados) if x is not None]
        custo_total = sum(partes, Decimal("0")) if partes else None
        apropriados = [x for x in (direto, rateados) if x is not None]
        saida[lt.pk] = {
            "aquisicao": aquisicao,
            "custos": sum(apropriados, Decimal("0")) if apropriados else None,
            "custos_diretos": direto,
            "custos_rateados": rateados,
            "criterios_de_rateio": criterios,
            "custo_total": custo_total,
            "custo_por_cabeca": (
                safe_div(custo_total, entradas.get(lt.pk, 0))
                if custo_total is not None
                else None
            ),
            # Depende do peso de carcaça vendido: quem preenche é `detalhe_do_lote`,
            # a partir de `SaleResultService` (Fase 3).
            "custo_por_arroba": None,
            "aviso_rateio": aviso_rateio,
        }
    return saida


def financeiro_do_lote(lot: Lot, *, cabecas_que_entraram: int, ate=None) -> dict:
    """Aquisição, custos diretos e rateados do lote — um lote é o caso de
    `financeiro_dos_lotes` com uma só posição, então a tela do lote e o
    dashboard produzem o mesmo número pelo mesmo código."""
    return financeiro_dos_lotes(
        [lot], entradas={lot.pk: cabecas_que_entraram}, ate=ate
    )[lot.pk]


def detalhe_do_lote(lot: Lot, *, rendimento_entrada=None) -> dict:
    """Agrega posição (razão), desempenho (pesagens), financeiro e resultado,
    e os avisos de dado faltando que a planilha nunca teve —
    docs/fluxos/01#a-tela-central-o-lote.

    Cada número vem do serviço dono dele (`WeightGainService`,
    `SaleResultService`, `financeiro_do_lote`): esta função só reúne. Sem
    dado, o item fica `None` ("—") e o motivo entra em `avisos`.

    `rendimento_entrada` (%) é a estimativa que o usuário informa para a @
    produzida — o sistema não escolhe um valor (pendência #15).
    """
    import datetime

    from apps.herd import services as herd_services
    from apps.herd.models import HerdLedgerEntry, MovementType, Weighing
    from apps.herd.weight_gain import desempenho_do_lote
    from apps.sales.result import resultado_do_lote

    linhas = HerdLedgerEntry.objects.filter(lot=lot)
    entradas = cabecas_que_entraram(lot)
    mortes = -sum(
        e.quantity
        for e in linhas.filter(quantity__lt=0, movement__type=MovementType.MORTE)
    )
    saidas_totais = -sum(e.quantity for e in linhas.filter(quantity__lt=0))
    cabecas = herd_services.saldo(lot=lot)["head_count"]

    ultima_pesagem = (
        Weighing.objects.filter(lot=lot, status="CONFIRMADA").order_by("-date").first()
    )
    peso_medio = ultima_pesagem.average_weight_kg if ultima_pesagem else None
    desempenho = desempenho_do_lote(lot, rendimento_entrada=rendimento_entrada)

    fim = lot.exit_date or datetime.date.today()
    dias = (fim - lot.entry_date).days

    avisos = []
    if (
        ultima_pesagem is not None
        and lot.status == "ABERTO"
        and (datetime.date.today() - ultima_pesagem.date).days > 90
    ):
        avisos.append(
            f"Sem pesagem desde {ultima_pesagem.date:%d/%m/%Y} — "
            "GMD pode estar desatualizado."
        )
    avisos.extend(desempenho.motivos)

    financeiro = financeiro_do_lote(lot, cabecas_que_entraram=entradas)
    if financeiro["aviso_rateio"]:
        avisos.append(financeiro["aviso_rateio"])

    resultado = resultado_do_lote(lot, financeiro=financeiro)
    financeiro["custo_por_arroba"] = resultado.custo_por_arroba
    # Os motivos do resultado só entram quando há venda: lote sem venda não
    # precisa de aviso "sem resultado", é o estado normal de lote aberto.
    if resultado.vendas:
        avisos.extend(resultado.motivos)

    return {
        "posicao": {
            "cabecas": cabecas,
            "entradas": entradas,
            "saidas": saidas_totais,
            "mortes": mortes,
        },
        "desempenho": {
            "peso_medio": peso_medio,
            "gmd": desempenho.gmd,
            "gmd_desde_a_entrada": desempenho.gmd_desde_a_entrada,
            "gmd_ultimo_trecho": (
                desempenho.trechos[-1].gmd if desempenho.trechos else None
            ),
            "arroba_produzida": desempenho.arrobas_produzidas,
            "arroba_estimada": desempenho.arrobas_estimadas,
            "rendimento_entrada": desempenho.rendimento_entrada,
            "dias": dias,
        },
        "financeiro": financeiro,
        "resultado": resultado,
        "avisos": avisos,
    }


def sugerir_proxima_categoria(categoria: AnimalCategory) -> AnimalCategory | None:
    """Categoria seguinte de mesmo sexo, pela ordem etária — sugestão para
    o lançamento de EVOLUCAO, nunca automática (docs/regras-negocio/01)."""
    if categoria.age_order is None:
        return None
    return (
        AnimalCategory.objects.filter(
            sex=categoria.sex, age_order__gt=categoria.age_order, is_active=True
        )
        .order_by("age_order")
        .first()
    )
