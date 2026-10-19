"""Complementação logística independente do acerto já aprovado."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import reversible
from apps.core.exceptions import BusinessError
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.serialization import diff_fields, snapshot
from apps.costs.services import (
    centro_de_custo_por_nome,
    classe_de_custo_por_nome,
    registrar_custo,
)
from apps.finance import services as finance
from apps.finance.models import Component, Direction
from apps.herd.permissions import tem_acesso_de_escrita_a_fazenda
from apps.herd.services import season_para_data
from apps.organizations.models import Season, SeasonStatus
from apps.partners.models import PartnerRoleChoice
from apps.procurement.models import Commitment, FreightAllocation, FreightSupplement
from apps.procurement.permissions import pode_lancar_no_ciclo
from apps.procurement.selectors import acerto_aprovado
from apps.purchases.models import Purchase

CAMPOS = ("carrier", "date", "due_date", "amount", "trucks", "truck", "notes")


def _travar(frete, usuario):
    compromisso = Commitment.objects.select_for_update().get(pk=frete.commitment_id)
    if not pode_lancar_no_ciclo(usuario) or not tem_acesso_de_escrita_a_fazenda(
        usuario, compromisso.destination_farm
    ):
        raise BusinessError("Você não tem permissão para lançar frete nesta fazenda.")
    if compromisso.status != Status.CONFIRMADA or acerto_aprovado(compromisso) is None:
        raise BusinessError("Aprove o acerto antes de complementar o frete.")
    safra_operacao = Season.objects.select_for_update().get(pk=compromisso.season_id)
    if safra_operacao.status == SeasonStatus.ENCERRADA:
        raise BusinessError(
            "A safra da operação está encerrada. Reabra a safra antes de lançar frete."
        )
    if frete.date < compromisso.date or frete.date > timezone.localdate():
        raise BusinessError(
            "A data do frete deve ficar entre a data da operação e hoje."
        )
    safra = season_para_data(frete.date)
    if safra is None or safra.company_id != compromisso.season.company_id:
        raise BusinessError("Cadastre uma safra da empresa que cubra a data do frete.")
    safra = Season.objects.select_for_update().get(pk=safra.pk)
    if safra.status == SeasonStatus.ENCERRADA:
        raise BusinessError(
            "A safra da data do frete está encerrada. Reabra a safra antes de lançar o frete."
        )
    frete.accounting_season = safra
    if frete.due_date < frete.date or frete.amount <= 0 or frete.trucks <= 0:
        raise BusinessError(
            "Informe valor e caminhões maiores que zero e vencimento a partir da data do frete."
        )
    if (
        not frete.carrier.is_active
        or not frete.carrier.roles.filter(role=PartnerRoleChoice.TRANSPORTADOR).exists()
    ):
        raise BusinessError("Selecione uma transportadora ativa.")
    # A mesma ordem de travas do acerto; nenhuma compra pode mudar durante o rateio.
    compras = list(
        Purchase.objects.select_for_update()
        .filter(commitment_item__commitment=compromisso, status=Status.CONFIRMADA)
        .order_by("pk")
    )
    return compromisso, compras


def _distribuir(compras, amount, distribuicao):
    if len(compras) == 1 and not distribuicao:
        distribuicao = {compras[0].pk: amount}
    distribuicao = {int(k): Decimal(v) for k, v in (distribuicao or {}).items() if v}
    if not distribuicao or set(distribuicao) - {c.pk for c in compras}:
        raise BusinessError(
            "Distribua o frete somente entre as compras desta operação."
        )
    if any(v <= 0 or v != v.quantize(Decimal("0.01")) for v in distribuicao.values()):
        raise BusinessError("A distribuição deve ter valores positivos em centavos.")
    if sum(distribuicao.values(), Decimal(0)) != amount:
        raise BusinessError("A soma da distribuição deve ser igual ao valor do frete.")
    return distribuicao


@transaction.atomic
def criar(*, compromisso, usuario, distribuicao=None, **dados):
    frete = FreightSupplement(
        commitment=compromisso,
        created_by=usuario,
        **{k: v for k, v in dados.items() if k in CAMPOS},
    )
    _, compras = _travar(frete, usuario)
    rateio = _distribuir(compras, frete.amount, distribuicao)
    frete.full_clean(exclude=["invoice"])
    frete.save()
    for pk, valor in rateio.items():
        FreightAllocation.objects.create(supplement=frete, purchase_id=pk, amount=valor)
    registrar_auditoria(
        action=AuditAction.CREATE,
        entity=frete,
        after={
            **snapshot(frete),
            "distribuicao": {str(k): str(v) for k, v in rateio.items()},
        },
        actor=usuario,
    )
    return frete


@transaction.atomic
def confirmar(frete, *, usuario):
    Commitment.objects.select_for_update().get(pk=frete.commitment_id)
    frete = FreightSupplement.objects.select_for_update().get(pk=frete.pk)
    if frete.status != Status.RASCUNHO:
        raise BusinessError("Este frete já foi confirmado ou excluído.")
    _travar(frete, usuario)
    return reversible.confirmar(frete, usuario=usuario)


@transaction.atomic
def editar(frete, dados, *, usuario, motivo, distribuicao=None):
    Commitment.objects.select_for_update().get(pk=frete.commitment_id)
    frete = FreightSupplement.objects.select_for_update().get(pk=frete.pk)
    if frete.status == Status.EXCLUIDA:
        raise BusinessError("Este frete foi excluído.")
    if frete.status == Status.CONFIRMADA and not pode_editar_confirmado(usuario):
        raise BusinessError("Você não tem permissão para corrigir frete confirmado.")
    if not motivo.strip():
        raise BusinessError("Informe o motivo da correção.")
    novos = {k: dados.get(k, getattr(frete, k)) for k in CAMPOS}
    candidato = FreightSupplement(commitment=frete.commitment, **novos)
    _, compras = _travar(candidato, usuario)
    rateio = _distribuir(compras, candidato.amount, distribuicao)
    bloqueios = frete.bloqueios()
    if bloqueios:
        raise BusinessError(str(bloqueios[0]))
    antes = {
        **snapshot(frete),
        "distribuicao": {
            str(k): str(v)
            for k, v in frete.allocations.values_list("purchase_id", "amount")
        },
    }
    if frete.status == Status.CONFIRMADA:
        desfazer(frete, usuario=usuario)
    # Linhas do rateio são substituídas com o antes/depois imutável na auditoria.
    frete.allocations.all().delete()
    for pk, valor in rateio.items():
        FreightAllocation.objects.create(supplement=frete, purchase_id=pk, amount=valor)
    for k, v in novos.items():
        setattr(frete, k, v)
    frete.full_clean(exclude=["invoice"])
    if frete.status == Status.CONFIRMADA:
        aplicar(frete, usuario=usuario)
    frete.version += 1
    frete.updated_by = usuario
    frete.save()
    depois = {
        **snapshot(frete),
        "distribuicao": {str(k): str(v) for k, v in rateio.items()},
    }
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=frete,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois),
        reason=motivo,
        actor=usuario,
    )
    return frete


@transaction.atomic
def excluir(frete, *, usuario, motivo, cascata=False):
    Commitment.objects.select_for_update().get(pk=frete.commitment_id)
    frete = FreightSupplement.objects.select_for_update().get(pk=frete.pk)
    if not pode_excluir_confirmado(usuario) or not tem_acesso_de_escrita_a_fazenda(
        usuario, frete.commitment.destination_farm
    ):
        raise BusinessError("Você não tem permissão para excluir este frete.")
    return reversible.excluir(frete, usuario=usuario, motivo=motivo, cascata=cascata)


@transaction.atomic
def restaurar(frete, *, usuario):
    Commitment.objects.select_for_update().get(pk=frete.commitment_id)
    frete = FreightSupplement.objects.select_for_update().get(pk=frete.pk)
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para restaurar este frete.")
    if frete.status != Status.EXCLUIDA:
        raise BusinessError("Só é possível restaurar um frete excluído.")
    _travar(frete, usuario)
    bloqueios = frete.bloqueios()
    if bloqueios:
        raise BusinessError(str(bloqueios[0]))
    if frete.invoice_id:
        return reversible.restaurar(frete, usuario=usuario)
    # Um rascunho excluído não pode gerar dívida ao ser restaurado.
    antes = snapshot(frete)
    frete.status = Status.RASCUNHO
    frete.deleted_at = None
    frete.deleted_by = None
    frete.delete_reason = ""
    frete.updated_by = usuario
    frete.version += 1
    frete.save()
    registrar_auditoria(
        action=AuditAction.RESTORE,
        entity=frete,
        before=antes,
        after=snapshot(frete),
        actor=usuario,
    )
    return frete


def aplicar(frete, *, usuario):
    compromisso, compras = _travar(frete, usuario)
    rateio = dict(frete.allocations.values_list("purchase_id", "amount"))
    _distribuir(compras, frete.amount, rateio)
    acerto = acerto_aprovado(compromisso)
    titulo = finance._sincronizar_titulo(
        campo_origem="origin_settlement",
        origem=acerto,
        direction=Direction.PAGAR,
        componente=Component.FRETE,
        farm=compromisso.destination_farm,
        season=frete.accounting_season,
        issue_date=frete.date,
        due_date=frete.due_date,
        amount=frete.amount,
        payee=frete.carrier,
        usuario=usuario,
        criar=True,
        restaurar_cancelados=True,
        seguir_favorecido=True,
        ref=f"complemento:{frete.pk}",
    )
    frete.invoice = titulo
    frete.save(update_fields=["invoice"])
    for compra in compras:
        if compra.pk in rateio:
            registrar_custo(
                date=frete.date,
                farm=compromisso.destination_farm,
                cost_center=centro_de_custo_por_nome("FRETE DE COMPRA"),
                cost_class=classe_de_custo_por_nome("CUSTEIO"),
                amount=rateio[compra.pk],
                description=f"{frete} · frete de compra",
                usuario=usuario,
                lot=compra.lot,
                season=frete.accounting_season,
                source_purchase=compra,
                source_freight=frete,
                operation_type=compra.operation_type,
                reference=str(frete),
            )


def desfazer(frete, *, usuario):
    if frete.invoice_id:
        from apps.finance.models import Invoice

        titulo = Invoice.objects.select_for_update().get(pk=frete.invoice_id)
        if titulo.status == Status.CONFIRMADA:
            finance._cancelar_com_a_origem(titulo, frete, usuario=usuario)
    for custo in frete.cost_entries.filter(status=Status.CONFIRMADA):
        reversible.excluir(
            custo,
            usuario=usuario,
            motivo=f"Correção/exclusão do frete {frete}",
            cascata=True,
        )
