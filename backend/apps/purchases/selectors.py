"""Leitura. Consultas e relatórios de compra.

Toda listagem passa por `for_user()` — nunca `.all()` (regra 4).
"""

from decimal import Decimal

from django.db.models import Count, Sum

from apps.core.reversible import Status
from apps.purchases.models import Purchase
from apps.purchases.services import calcular_custo_da_compra, custo_da_compra


def listar_compras_para(user, *, season=None, farm=None, situacao: str = ""):
    qs = Purchase.objects.for_user(user).select_related(
        "destination_farm", "category", "seller", "lot", "season"
    )
    if season is not None:
        qs = qs.filter(season=season)
    if farm is not None:
        qs = qs.filter(destination_farm=farm)
    if situacao:
        qs = qs.filter(status=situacao)
    return qs


def compras_do_periodo(user, *, season=None, farm=None, start=None, end=None):
    """Substitui `COMPRA DE GADO` + `DASH COMPRAS`: o que foi comprado, de
    quem, por quanto. Só compras confirmadas contam."""
    qs = listar_compras_para(
        user, season=season, farm=farm, situacao=Status.CONFIRMADA
    ).order_by("date", "id")
    if start is not None:
        qs = qs.filter(date__gte=start)
    if end is not None:
        qs = qs.filter(date__lte=end)

    linhas = [{"compra": compra, "custo": custo_da_compra(compra)} for compra in qs]
    cabecas = sum(linha["compra"].head_count for linha in linhas)
    valor_animais = sum(
        (linha["compra"].animal_value for linha in linhas), Decimal("0")
    )
    peso = [linha["compra"].total_weight_kg for linha in linhas]
    totais = calcular_custo_da_compra(
        head_count=cabecas,
        animal_value=valor_animais,
        freight_value=sum((x["compra"].freight_value for x in linhas), Decimal("0")),
        commission_value=sum(
            (x["compra"].commission_value for x in linhas), Decimal("0")
        ),
        tax_value=sum((x["compra"].tax_value for x in linhas), Decimal("0")),
        # Só há peso total quando TODAS as compras foram pesadas: somar parte
        # delas e dividir pelo total de cabeças mentiria no custo/@.
        total_weight_kg=sum(peso, Decimal("0")) if peso and all(peso) else None,
    )
    return linhas, {"cabecas": cabecas, "valor_animais": valor_animais, "custo": totais}


def compras_por_mes(user, *, season=None, farm=None):
    """Cabeças e valor por mês — a distribuição que a planilha mostra no
    `DASH COMPRAS` (jul 96 · ago 40 · out 54 ...)."""
    from django.db.models.functions import TruncMonth

    qs = listar_compras_para(user, season=season, farm=farm, situacao=Status.CONFIRMADA)
    return list(
        qs.annotate(mes=TruncMonth("date"))
        .values("mes")
        .annotate(
            compras=Count("id"), cabecas=Sum("head_count"), valor=Sum("animal_value")
        )
        .order_by("mes")
    )


def custo_de_aquisicao_por_lote(user, *, season=None, farm=None):
    """Quanto custou formar cada lote: o que a planilha não tem."""
    linhas, vistos = [], set()
    for compra in listar_compras_para(
        user, season=season, farm=farm, situacao=Status.CONFIRMADA
    ).filter(lot__isnull=False):
        if compra.lot_id in vistos:
            continue
        vistos.add(compra.lot_id)
        compras_do_lote = [
            c
            for c in listar_compras_para(user, situacao=Status.CONFIRMADA).filter(
                lot=compra.lot
            )
        ]
        cabecas = sum(c.head_count for c in compras_do_lote)
        animais = sum((c.animal_value for c in compras_do_lote), Decimal("0"))
        pesos = [c.total_weight_kg for c in compras_do_lote]
        custo = calcular_custo_da_compra(
            head_count=cabecas,
            animal_value=animais,
            freight_value=sum((c.freight_value for c in compras_do_lote), Decimal("0")),
            commission_value=sum(
                (c.commission_value for c in compras_do_lote), Decimal("0")
            ),
            tax_value=sum((c.tax_value for c in compras_do_lote), Decimal("0")),
            total_weight_kg=sum(pesos, Decimal("0")) if all(pesos) else None,
        )
        linhas.append(
            {
                "lote": compra.lot,
                "fazenda": compra.destination_farm,
                "compras": len(compras_do_lote),
                "cabecas": cabecas,
                "custo": custo,
            }
        )
    return linhas
