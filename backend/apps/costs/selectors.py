"""Leitura. Consultas e agregações de custo.

Toda listagem passa por `for_user()` — nunca `.all()` (regra 4).
"""

from decimal import Decimal

from django.db.models import Count, Q, Sum

from apps.core.money import quantize_percent, safe_div
from apps.core.reversible import Status
from apps.costs.models import CostCenter, CostClass, CostEntry


def listar_centros():
    return CostCenter.objects.select_related("parent").order_by("name")


def listar_classes():
    return CostClass.objects.order_by("name")


def listar_custos_para(
    user,
    *,
    season=None,
    farm=None,
    cost_center=None,
    cost_class=None,
    texto: str = "",
    situacao: str = Status.CONFIRMADA,
):
    qs = CostEntry.objects.for_user(user).select_related(
        "farm", "cost_center", "cost_class", "season", "lot", "source_purchase"
    )
    if situacao:
        qs = qs.filter(status=situacao)
    if season is not None:
        qs = qs.filter(season=season)
    if farm is not None:
        qs = qs.filter(farm=farm)
    if cost_center is not None:
        qs = qs.filter(cost_center=cost_center)
    if cost_class is not None:
        qs = qs.filter(cost_class=cost_class)
    if texto:
        qs = qs.filter(Q(description__icontains=texto) | Q(notes__icontains=texto))
    return qs


def total_dos_custos(qs) -> Decimal:
    return qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")


def _confirmados(user, *, season=None, farm=None):
    qs = CostEntry.objects.for_user(user).filter(status=Status.CONFIRMADA)
    if season is not None:
        qs = qs.filter(season=season)
    if farm is not None:
        qs = qs.filter(farm=farm)
    return qs


def _com_participacao(linhas: list[dict]) -> tuple[list[dict], Decimal]:
    total = sum((linha["total"] for linha in linhas), Decimal("0"))
    for linha in linhas:
        participacao = safe_div(linha["total"], total)
        linha["participacao"] = (
            quantize_percent(participacao * 100) if participacao is not None else None
        )
    return linhas, total


def custos_por_centro(user, *, season=None, farm=None):
    """Substitui o `DASH FINANCEIRO`: onde o dinheiro foi."""
    dados = (
        _confirmados(user, season=season, farm=farm)
        .values("cost_center__name")
        .annotate(total=Sum("amount"), lancamentos=Count("id"))
        .order_by("-total")
    )
    linhas = [
        {
            "nome": d["cost_center__name"],
            "total": d["total"],
            "lancamentos": d["lancamentos"],
        }
        for d in dados
    ]
    return _com_participacao(linhas)


def custos_por_fazenda(user, *, season=None):
    dados = (
        _confirmados(user, season=season)
        .values("farm__name")
        .annotate(total=Sum("amount"), lancamentos=Count("id"))
        .order_by("-total")
    )
    linhas = [
        {"nome": d["farm__name"], "total": d["total"], "lancamentos": d["lancamentos"]}
        for d in dados
    ]
    return _com_participacao(linhas)


def custos_por_classe(user, *, season=None, farm=None):
    """Custeio × investimento: quanto é gasto, quanto é imobilizado."""
    dados = (
        _confirmados(user, season=season, farm=farm)
        .values("cost_class__name")
        .annotate(total=Sum("amount"), lancamentos=Count("id"))
        .order_by("-total")
    )
    linhas = [
        {
            "nome": d["cost_class__name"],
            "total": d["total"],
            "lancamentos": d["lancamentos"],
        }
        for d in dados
    ]
    return _com_participacao(linhas)
