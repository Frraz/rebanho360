"""Escrita. Toda operação que altera estado passa por aqui."""

from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.serialization import diff_fields, snapshot
from apps.partners.models import BankAccount, Partner, PartnerRole


@transaction.atomic
def salvar_parceiro(partner: Partner, roles: list[str], *, usuario, criando: bool):
    """Salva o Partner e sincroniza os papéis marcados — nunca duplica o
    cadastro para a mesma pessoa exercer mais de um papel."""
    antes = None if criando else snapshot(Partner.objects.get(pk=partner.pk))
    partner.save()

    atuais = set(partner.roles.values_list("role", flat=True))
    desejados = set(roles)

    for role in desejados - atuais:
        PartnerRole.objects.create(partner=partner, role=role)
    PartnerRole.objects.filter(partner=partner, role__in=(atuais - desejados)).delete()

    depois = snapshot(partner)
    registrar_auditoria(
        action=AuditAction.CREATE if criando else AuditAction.UPDATE,
        entity=partner,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois) if antes else None,
        actor=usuario,
    )
    return partner


@transaction.atomic
def salvar_conta_bancaria(
    conta: BankAccount, *, usuario, criando: bool, motivo: str = ""
):
    """Alterar dado bancário é auditoria de severidade alta — sempre
    registrada, com motivo nas edições (docs/regras-negocio/06)."""
    antes = None if criando else snapshot(BankAccount.objects.get(pk=conta.pk))

    if conta.is_default:
        BankAccount.objects.filter(partner=conta.partner, is_default=True).exclude(
            pk=conta.pk
        ).update(is_default=False)

    conta.save()
    depois = snapshot(conta)
    registrar_auditoria(
        action=AuditAction.CREATE if criando else AuditAction.UPDATE,
        entity=conta,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois) if antes else None,
        reason=motivo,
        actor=usuario,
    )
    return conta
