"""Leitura do ciclo. A **etapa** do compromisso é derivada do que existe —
nunca um campo que possa discordar da realidade (ADR 0008)."""

from django.db import models
from django.db.models import Count, Q

from apps.core.reversible import Status
from apps.procurement.models import (
    Commitment,
    Receiving,
    Settlement,
    Trip,
)


class Etapa(models.TextChoices):
    EM_NEGOCIACAO = "EM_NEGOCIACAO", "Em negociação"
    APROVADO = "APROVADO", "Compromisso aprovado"
    PROGRAMADO = "PROGRAMADO", "Programado"
    EM_VIAGEM = "EM_VIAGEM", "Em viagem"
    RECEBIDO = "RECEBIDO", "Recebido"
    EM_ACERTO = "EM_ACERTO", "Em acerto"
    ACERTO_APROVADO = "ACERTO_APROVADO", "Acerto aprovado"
    EXCLUIDO = "EXCLUIDO", "Excluído"


class SituacaoFinanceira(models.TextChoices):
    """O que acontece **depois** do acerto aprovado (cliente, 2026-10-03,
    pendência #29). Derivada dos títulos — o financeiro faz a operação avançar
    sem ninguém atualizar status à mão. `ENCERRADA` é o único passo manual."""

    AGUARDANDO_FINANCEIRO = "AGUARDANDO_FINANCEIRO", "Aguardando financeiro"
    PAGAMENTO_PROGRAMADO = "PAGAMENTO_PROGRAMADO", "Pagamento programado"
    PAGO = "PAGO", "Pago"
    ENCERRADA = "ENCERRADA", "Encerrada"


def situacao_financeira(commitment: Commitment) -> str | None:
    """`None` enquanto não há acerto aprovado: a etapa do ciclo é a que vale."""
    if commitment.status != Status.CONFIRMADA:
        return None
    if commitment.encerrada:
        return SituacaoFinanceira.ENCERRADA
    acerto = acerto_aprovado(commitment)
    if acerto is None:
        return None
    from apps.finance.models import Direction, Invoice, PaymentStatus

    titulos = Invoice.objects.filter(
        Q(origin_settlement=acerto)
        | Q(origin_purchase__commitment_item__commitment=commitment),
        status=Status.CONFIRMADA,
        direction=Direction.PAGAR,
    ).values_list("payment_status", flat=True)
    situacoes = list(titulos)
    if not situacoes:
        return SituacaoFinanceira.AGUARDANDO_FINANCEIRO
    if all(s == PaymentStatus.PAGO for s in situacoes):
        return SituacaoFinanceira.PAGO
    if any(s != PaymentStatus.A_PAGAR for s in situacoes):
        return SituacaoFinanceira.PAGAMENTO_PROGRAMADO
    return SituacaoFinanceira.AGUARDANDO_FINANCEIRO


def acerto_vigente(commitment: Commitment) -> Settlement | None:
    """O acerto que vale: o ativo; sem ele, o último excluído (é o que a
    restauração reaplica)."""
    acertos = Settlement.objects.filter(commitment=commitment)
    ativo = acertos.exclude(status=Status.EXCLUIDA).first()
    return ativo or acertos.order_by("-id").first()


def acerto_ativo(commitment: Commitment) -> Settlement | None:
    return (
        Settlement.objects.filter(commitment=commitment)
        .exclude(status=Status.EXCLUIDA)
        .first()
    )


def acerto_aprovado(commitment: Commitment) -> Settlement | None:
    return Settlement.objects.filter(
        commitment=commitment, status=Status.CONFIRMADA
    ).first()


def viagens_ativas(commitment: Commitment):
    return Trip.objects.filter(commitment=commitment).exclude(status=Status.EXCLUIDA)


def recebimentos_ativos(commitment: Commitment):
    return Receiving.objects.filter(trip__commitment=commitment).exclude(
        status=Status.EXCLUIDA
    )


def etapa_do_compromisso(commitment: Commitment) -> str:
    if commitment.status == Status.EXCLUIDA:
        return Etapa.EXCLUIDO
    if commitment.status == Status.RASCUNHO:
        return Etapa.EM_NEGOCIACAO

    acerto = acerto_ativo(commitment)
    if acerto is not None:
        return (
            Etapa.ACERTO_APROVADO
            if acerto.status == Status.CONFIRMADA
            else Etapa.EM_ACERTO
        )

    viagens = viagens_ativas(commitment).aggregate(
        total=Count("id", distinct=True),
        recebidas=Count(
            "id", filter=Q(receivings__status=Status.CONFIRMADA), distinct=True
        ),
    )
    if viagens["total"]:
        return (
            Etapa.RECEBIDO
            if viagens["recebidas"] == viagens["total"]
            else Etapa.EM_VIAGEM
        )
    if commitment.pickup_date:
        return Etapa.PROGRAMADO
    return Etapa.APROVADO


def listar_compromissos_para(user, *, season=None, farm=None, situacao: str = ""):
    qs = Commitment.objects.for_user(user).select_related(
        "seller", "destination_farm", "commissioned", "season"
    )
    if season is not None:
        qs = qs.filter(season=season)
    if farm is not None:
        qs = qs.filter(destination_farm=farm)
    if situacao:
        qs = qs.filter(status=situacao)
    return qs
