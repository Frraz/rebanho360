"""Leitura. Consultas e agregações."""

from django.db.models import Q, Sum

from apps.herd.models import TWO_LINE_TYPES, HerdLedgerEntry, HerdMovement
from apps.livestock.models import AnimalCategory, Lot


def posicao_do_rebanho(*, user, farm=None, season=None, until=None):
    """Substitui o quadro-resumo das abas de fazenda — e o consolidado
    que a aba `GERAL` tentava ser. Nunca mostra número negativo, porque
    o saldo é sempre `SUM` do razão (ADR 0002), já protegido pela
    invariante de saldo não negativo (F1-09)."""
    qs = HerdLedgerEntry.objects.for_user(user)
    if farm is not None:
        qs = qs.filter(farm=farm)
    if season is not None:
        qs = qs.filter(season=season)
    if until is not None:
        qs = qs.filter(date__lte=until)

    # Uma consulta para todas as categorias (eram duas por categoria).
    somas = {
        linha["category_id"]: linha
        for linha in qs.values("category_id")
        .annotate(
            entradas=Sum("quantity", filter=Q(quantity__gt=0)),
            saidas=Sum("quantity", filter=Q(quantity__lt=0)),
        )
        .order_by()
    }
    linhas = []
    for categoria in AnimalCategory.objects.filter(is_active=True):
        soma = somas.get(categoria.pk, {})
        entradas = soma.get("entradas") or 0
        saidas = soma.get("saidas") or 0
        linhas.append(
            {
                "categoria": categoria,
                "entradas": entradas,
                "saidas": -saidas,
                "posicao": entradas + saidas,
            }
        )

    total = {
        "entradas": sum(linha["entradas"] for linha in linhas),
        "saidas": sum(linha["saidas"] for linha in linhas),
        "posicao": sum(linha["posicao"] for linha in linhas),
    }
    return linhas, total


def lotes_da_fazenda(user, farm_id):
    if not farm_id:
        return Lot.objects.none()
    return Lot.objects.for_user(user).filter(farm_id=farm_id, status="ABERTO")


def conciliar_transferencias(user=None):
    """F1-15 — o relatório que a planilha nunca teve: toda saída de
    deslocamento sem entrada correspondente. O trigger de banco
    (F1-06) já torna isso impossível pelos caminhos normais; este
    relatório é a segunda camada — útil sobretudo depois que a Fase 2
    importar histórico (pendência #2). Numa operação saudável, vem
    vazio: é isso que prova que o modelo está fechando."""
    base = listar_movimentos_para(user) if user is not None else HerdMovement.objects
    return (
        base.filter(type__in=TWO_LINE_TYPES)
        .annotate(soma=Sum("entries__quantity"))
        .exclude(soma=0)
        .exclude(soma__isnull=True)
        .order_by("date")
    )


def listar_movimentos_para(user):
    from apps.herd.models import HerdMovement

    if user.has_broad_access:
        return HerdMovement.objects.all()
    fazendas = user.accessible_farms()
    # Sem `distinct()`: o filtro não junta tabela de muitos, então não há linha
    # repetida — e o `DISTINCT` obrigava o banco a ordenar a tabela inteira.
    return HerdMovement.objects.filter(
        Q(origin_farm__in=fazendas) | Q(destination_farm__in=fazendas)
    )
