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
    from apps.herd.models import HerdLedgerEntry

    return sum(
        quantidade
        for quantidade in HerdLedgerEntry.objects.filter(
            lot=lot, quantity__gt=0
        ).values_list("quantity", flat=True)
    )


def financeiro_do_lote(lot: Lot, *, cabecas_que_entraram: int, ate=None) -> dict:
    """Aquisição, custos diretos e rateados do lote. O que não tem dado
    fica `None` ("—" na tela), nunca zero:

        custo_total = aquisição + custos apropriados + custos rateados
                                             (docs/regras-negocio/05#custo)
    """
    import datetime
    from decimal import Decimal

    from django.db.models import Sum

    from apps.core.exceptions import BusinessError
    from apps.core.money import safe_div
    from apps.core.reversible import Status
    from apps.costs.allocation import ratear_custos_indiretos
    from apps.costs.models import CostEntry
    from apps.purchases.models import Purchase
    from apps.purchases.services import calcular_custo_da_compra

    compras = list(Purchase.objects.filter(lot=lot, status=Status.CONFIRMADA))
    aquisicao = None
    if compras:
        aquisicao = sum(
            (
                calcular_custo_da_compra(
                    head_count=c.head_count,
                    animal_value=c.animal_value,
                    freight_value=c.freight_value,
                    commission_value=c.commission_value,
                    tax_value=c.tax_value,
                ).custo_aquisicao
                for c in compras
            ),
            Decimal("0"),
        )

    # Os custos gerados pela compra já estão na aquisição: não contam duas vezes.
    diretos = CostEntry.objects.filter(
        lot=lot, status=Status.CONFIRMADA, source_purchase=None
    ).aggregate(total=Sum("amount"))["total"]

    rateados, aviso_rateio, criterios = None, None, []
    fim = ate or lot.exit_date or datetime.date.today()
    try:
        resultado = ratear_custos_indiretos(
            farm=lot.farm, start=lot.entry_date, end=fim
        )
        cota = resultado.cotas_por_lote.get(lot.pk)
        if cota:
            rateados = cota
            criterios = sorted(
                {c.criterio_rotulo for c in resultado.centros if lot.pk in c.cotas}
            )
    except BusinessError as exc:
        aviso_rateio = f"Custo rateado indisponível: {exc}"

    partes = [x for x in (aquisicao, diretos, rateados) if x is not None]
    custo_total = sum(partes, Decimal("0")) if partes else None
    custos_apropriados = [x for x in (diretos, rateados) if x is not None]
    return {
        "aquisicao": aquisicao,
        "custos": sum(custos_apropriados, Decimal("0")) if custos_apropriados else None,
        "custos_diretos": diretos,
        "custos_rateados": rateados,
        "criterios_de_rateio": criterios,
        "custo_total": custo_total,
        "custo_por_cabeca": (
            safe_div(custo_total, cabecas_que_entraram)
            if custo_total is not None
            else None
        ),
        # Depende do peso de carcaça vendido: quem preenche é `detalhe_do_lote`,
        # a partir de `SaleResultService` (Fase 3).
        "custo_por_arroba": None,
        "aviso_rateio": aviso_rateio,
    }


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
