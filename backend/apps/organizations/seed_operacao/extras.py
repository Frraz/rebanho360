"""Correções, exclusões e baixas desfeitas — o que acontece numa operação real
e que enche a auditoria, as telas de "excluídos" e os alertas.

Tudo com motivo e pelos serviços de produção. Acontece **antes** de encerrar
as safras (safra encerrada bloqueia editar e excluir).
"""

from apps.core.reversible import Status
from apps.costs.models import CostEntry
from apps.costs.services import editar_custo, excluir_custo
from apps.finance import services as financeiro
from apps.finance.models import Payment
from apps.organizations import services as org_services
from apps.organizations.models import SeasonStatus
from apps.purchases import services as compras
from apps.purchases.models import Purchase

from . import catalogo as cat
from .util import D, dias, q2


def correcoes(ctx):
    rnd = ctx.rnd
    custos = list(
        CostEntry.objects.filter(
            farm__code__startswith=cat.PREFIXO,
            status=Status.CONFIRMADA,
            lot__isnull=True,
            source_purchase__isnull=True,
        ).order_by("id")
    )
    if len(custos) >= 8:
        escolhidos = rnd.sample(custos, k=5)
        for custo in escolhidos[:3]:
            ctx.tentar(
                "correcao_custo",
                editar_custo,
                custo,
                {"amount": q2(custo.amount * D("1.08"))},
                usuario=ctx.admin,
                motivo="Valor conferido com a nota fiscal do fornecedor.",
            )
        for custo in escolhidos[3:]:
            ctx.tentar(
                "exclusao_custo",
                excluir_custo,
                custo,
                usuario=ctx.admin,
                motivo="Lançamento em duplicidade com o da semana anterior.",
            )

    # Compra direta recente: corrige o frete e exclui outra lançada por engano.
    recentes = list(
        Purchase.objects.filter(
            destination_farm__code__startswith=cat.PREFIXO,
            status=Status.CONFIRMADA,
            commitment_item__isnull=True,
            date__gte=ctx.cutoff - dias(60),
        ).order_by("-date", "id")
    )
    if recentes:
        compra = recentes[0]
        ctx.tentar(
            "correcao_compra",
            compras.editar_compra,
            compra,
            {"freight_value": q2(compra.freight_value * D("1.15"))},
            usuario=ctx.admin,
            motivo="Frete reajustado: o transportador cobrou a diária de espera.",
        )
    if len(recentes) > 1:
        ctx.tentar(
            "exclusao_compra",
            compras.excluir_compra,
            recentes[-1],
            usuario=ctx.admin,
            motivo="Compra lançada em duplicidade; a nota fiscal é a mesma da anterior.",
            cascata=True,
        )


def desfazer_uma_baixa(ctx):
    """Uma baixa desfeita (pagamento devolvido pelo banco), com motivo."""
    pagamento = (
        Payment.objects.filter(
            invoice__farm__code__startswith=cat.PREFIXO, status=Status.CONFIRMADA
        )
        .order_by("-date", "-id")
        .first()
    )
    if pagamento is None:
        return
    ctx.tentar(
        "baixa_desfeita",
        financeiro.desfazer_baixa,
        pagamento,
        usuario=ctx.admin,
        motivo="Pagamento devolvido pelo banco: conta do favorecido com dado incorreto.",
    )


def encerrar_safras(ctx):
    """Encerra só as safras que o seed criou e que já passaram."""
    for safra in ctx.safras:
        if safra.pk not in ctx.safras_criadas or safra.end_date >= ctx.cutoff:
            continue
        safra.refresh_from_db()
        if safra.status == SeasonStatus.ABERTA:
            ctx.tentar(
                "safra_encerrada", org_services.encerrar_safra, safra, usuario=ctx.admin
            )
