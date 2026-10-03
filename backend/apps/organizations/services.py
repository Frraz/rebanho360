"""Escrita. Toda operação que altera estado passa por aqui."""

from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core.exceptions import BusinessError
from apps.core.serialization import diff_fields, snapshot
from apps.organizations.models import Season, SeasonStatus


@transaction.atomic
def salvar_cadastro(instancia, *, usuario, criando: bool):
    """Salva Company/BusinessUnit/Season com auditoria simples.

    Não usa o mecanismo `ReversibleModel` (F0-10): esses são cadastros
    estruturais, não documentos com efeito a desfazer em cascata.
    """
    antes = None if criando else snapshot(type(instancia).objects.get(pk=instancia.pk))
    instancia.save()
    depois = snapshot(instancia)
    registrar_auditoria(
        action=AuditAction.CREATE if criando else AuditAction.UPDATE,
        entity=instancia,
        before=antes,
        after=depois,
        changed_fields=diff_fields(antes, depois) if antes else None,
        actor=usuario,
    )
    return instancia


@transaction.atomic
def marcar_como_corrente(season: Season, *, usuario) -> Season:
    """Torna `season` a safra corrente da empresa; as demais deixam de ser.

    A constraint `uniq_current_season_per_company` garante no banco que
    nunca há duas safras correntes ao mesmo tempo — aqui só sequencia a
    troca sem violar a janela entre os dois updates.
    """
    Season.objects.filter(company=season.company, is_current=True).exclude(
        pk=season.pk
    ).update(is_current=False)
    season.is_current = True
    season.save(update_fields=["is_current"])
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=season,
        after=snapshot(season),
        changed_fields=["is_current"],
        actor=usuario,
    )
    return season


@transaction.atomic
def encerrar_safra(season: Season, *, usuario) -> Season:
    if season.status == SeasonStatus.ENCERRADA:
        raise BusinessError(f"A safra {season.name} já está encerrada.")
    antes = snapshot(season)
    season.status = SeasonStatus.ENCERRADA
    season.save(update_fields=["status"])
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=season,
        before=antes,
        after=snapshot(season),
        changed_fields=["status"],
        reason="Safra encerrada",
        actor=usuario,
    )
    return season


@transaction.atomic
def reabrir_safra(season: Season, *, usuario) -> Season:
    if season.status == SeasonStatus.ABERTA:
        raise BusinessError(f"A safra {season.name} já está aberta.")
    antes = snapshot(season)
    season.status = SeasonStatus.ABERTA
    season.save(update_fields=["status"])
    registrar_auditoria(
        action=AuditAction.UPDATE,
        entity=season,
        before=antes,
        after=snapshot(season),
        changed_fields=["status"],
        reason="Safra reaberta",
        actor=usuario,
    )
    return season
