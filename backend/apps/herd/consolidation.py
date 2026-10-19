"""Posição consolidada compartilhada pelo Mapa de Gado e relatório."""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Q, Sum

from apps.core.money import safe_div
from apps.herd.models import HerdLedgerEntry
from apps.livestock.models import Sex


def consolidar(user, *, company, ate, farm=None, unidade=None, categoria=None):
    qs = HerdLedgerEntry.objects.for_user(user).filter(
        Q(farm__business_unit__company=company)
        | Q(farm__business_unit__isnull=True, season__company=company),
        date__lte=ate,
    )
    if farm:
        qs = qs.filter(farm=farm)
    if unidade:
        qs = qs.filter(farm__business_unit=unidade)
    if categoria:
        qs = qs.filter(category=categoria)
    linhas = list(
        qs.values(
            "farm_id",
            "farm__name",
            "farm__business_unit__code",
            "farm__business_unit__name",
            "category_id",
            "category__name",
            "category__sex",
        )
        .annotate(cabecas=Sum("quantity"))
        .filter(cabecas__gt=0)
        .order_by("farm__business_unit__code", "farm__name", "category__name")
    )
    total = sum(linha["cabecas"] for linha in linhas)
    sexos = defaultdict(int)
    categorias = defaultdict(int)
    for linha in linhas:
        sexos[linha["category__sex"]] += linha["cabecas"]
        categorias[linha["category__name"]] += linha["cabecas"]
    return {
        "linhas": linhas,
        "total": total,
        "sexos": [
            {
                "sexo": Sex(s).label,
                "cabecas": sexos[s],
                "percentual": safe_div(Decimal(sexos[s]) * 100, total),
            }
            for s in Sex.values
        ],
        "ranking": sorted(categorias.items(), key=lambda x: (-x[1], x[0])),
    }
