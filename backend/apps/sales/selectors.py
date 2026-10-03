"""Leitura. Consultas de venda.

Toda listagem passa por `for_user()` — nunca `.all()` (regra 4).
"""

from apps.core.reversible import Status
from apps.sales.models import Sale


def listar_vendas_para(
    user, *, season=None, farm=None, situacao: str = "", sem_carcaca: bool = False
):
    qs = Sale.objects.for_user(user).select_related(
        "farm", "lot", "category", "buyer", "season"
    )
    if season is not None:
        qs = qs.filter(season=season)
    if farm is not None:
        qs = qs.filter(farm=farm)
    if situacao:
        qs = qs.filter(status=situacao)
    if sem_carcaca:
        # Abate cujo romaneio ainda não chegou: pendência do painel.
        qs = qs.filter(type="ABATE", carcass_weight_kg__isnull=True)
    return qs


def vendas_confirmadas_para(user, *, season=None, farm=None, start=None, end=None):
    """Só venda confirmada conta em indicador, relatório e dashboard."""
    qs = listar_vendas_para(
        user, season=season, farm=farm, situacao=Status.CONFIRMADA
    ).order_by("date", "id")
    if start is not None:
        qs = qs.filter(date__gte=start)
    if end is not None:
        qs = qs.filter(date__lte=end)
    return qs
