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


def etapas_dos_compromissos(commitments) -> dict:
    """`{pk: etapa}` de vários compromissos com duas consultas (acertos e
    viagens), em vez de duas por compromisso. A etapa é derivada (ADR 0008)."""
    commitments = list(commitments)
    abertos = [
        c for c in commitments if c.status not in (Status.EXCLUIDA, Status.RASCUNHO)
    ]
    ids = [c.pk for c in abertos]
    # Há no máximo um acerto ativo por compromisso (restrição no banco).
    acertos = dict(
        Settlement.objects.filter(commitment_id__in=ids)
        .exclude(status=Status.EXCLUIDA)
        .values_list("commitment_id", "status")
    )
    viagens = {
        linha["commitment_id"]: linha
        for linha in Trip.objects.filter(commitment_id__in=ids)
        .exclude(status=Status.EXCLUIDA)
        .values("commitment_id")
        .annotate(
            total=Count("id", distinct=True),
            recebidas=Count(
                "id", filter=Q(receivings__status=Status.CONFIRMADA), distinct=True
            ),
        )
        .order_by("commitment_id")
    }

    etapas = {}
    for c in commitments:
        if c.status == Status.EXCLUIDA:
            etapas[c.pk] = Etapa.EXCLUIDO
        elif c.status == Status.RASCUNHO:
            etapas[c.pk] = Etapa.EM_NEGOCIACAO
        elif c.pk in acertos:
            etapas[c.pk] = (
                Etapa.ACERTO_APROVADO
                if acertos[c.pk] == Status.CONFIRMADA
                else Etapa.EM_ACERTO
            )
        elif c.pk in viagens and viagens[c.pk]["total"]:
            v = viagens[c.pk]
            etapas[c.pk] = (
                Etapa.RECEBIDO if v["recebidas"] == v["total"] else Etapa.EM_VIAGEM
            )
        elif c.pickup_date:
            etapas[c.pk] = Etapa.PROGRAMADO
        else:
            etapas[c.pk] = Etapa.APROVADO
    return etapas


def etapa_do_compromisso(commitment: Commitment) -> str:
    return etapas_dos_compromissos([commitment])[commitment.pk]


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
