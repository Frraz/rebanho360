"""Escrita do ciclo reprodutivo. Registro de apoio: sem efeito em rebanho, custo
ou título — mas editável e excluível com motivo e auditoria como todo registro
(regra 5)."""

from django.db import transaction

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import reversible
from apps.core.exceptions import BusinessError
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.core.serialization import snapshot
from apps.herd.permissions import (
    pode_lancar_movimento,
    tem_acesso_de_escrita_a_fazenda,
)
from apps.organizations.models import Season
from apps.reproduction.models import GRUPOS, BreedingCycle

CAMPOS = (
    "breeding_months",
    "females_total",
    "females_over_18m",
    *(campo for exp, pre, _ in GRUPOS for campo in (exp, pre)),
    "inseminated",
    "pregnant_by_ai",
    "pregnant_by_bull",
    "weaned_calves",
    "notes",
)


def _validar(dados: dict, *, usuario, farm) -> None:
    if not tem_acesso_de_escrita_a_fazenda(usuario, farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {farm}.")
    for exp, pre, rotulo in GRUPOS:
        if (dados.get(pre) or 0) > (dados.get(exp) or 0):
            raise BusinessError(
                f"{rotulo}: as prenhes ({dados.get(pre)}) passam das fêmeas em "
                f"monta ({dados.get(exp)})."
            )
    if (dados.get("pregnant_by_ai") or 0) > (dados.get("inseminated") or 0):
        raise BusinessError("As prenhes por IA/IATF passam das fêmeas inseminadas.")
    prenhes = sum((dados.get(pre) or 0) for _, pre, _ in GRUPOS)
    if (dados.get("pregnant_by_ai") or 0) + (
        dados.get("pregnant_by_bull") or 0
    ) > prenhes:
        raise BusinessError(
            "Prenhes por IA/IATF e por touro, somadas, passam do total de prenhes."
        )
    meses = dados.get("breeding_months")
    if meses is not None and not 1 <= meses <= 12:
        raise BusinessError("O tempo de estação vai de 1 a 12 meses.")


def _codigo(season: Season) -> str:
    base = f"RP-{season.name}-"
    return (
        f"{base}{BreedingCycle.objects.filter(code__startswith=base).count() + 1:04d}"
    )


@transaction.atomic
def registrar_ciclo(*, usuario, farm, season, **dados) -> BreedingCycle:
    if not pode_lancar_movimento(usuario):
        raise BusinessError("Você não tem permissão para lançar ciclos reprodutivos.")
    dados = {campo: dados.get(campo) for campo in CAMPOS}
    for campo, valor in dados.items():
        if valor is None and campo not in ("breeding_months", "notes"):
            dados[campo] = 0
    dados["notes"] = dados.get("notes") or ""
    _validar(dados, usuario=usuario, farm=farm)
    season = Season.objects.select_for_update().get(pk=season.pk)
    existente = (
        BreedingCycle.objects.filter(farm=farm, season=season)
        .exclude(status=Status.EXCLUIDA)
        .first()
    )
    if existente is not None:
        raise BusinessError(
            f"{farm} já tem o ciclo {existente.code} na safra {season.name}. "
            "Corrija o que existe em vez de lançar outro."
        )
    ciclo = BreedingCycle(
        farm=farm, season=season, created_by=usuario, code=_codigo(season), **dados
    )
    ciclo.save()
    registrar_auditoria(
        action=AuditAction.CREATE, entity=ciclo, after=snapshot(ciclo), actor=usuario
    )
    return reversible.confirmar(ciclo, usuario=usuario)


@transaction.atomic
def editar_ciclo(
    ciclo: BreedingCycle, dados: dict, *, usuario, motivo: str
) -> BreedingCycle:
    if not pode_editar_confirmado(usuario):
        raise BusinessError("Você não tem permissão para editar ciclos reprodutivos.")
    novos = {campo: dados.get(campo, getattr(ciclo, campo)) for campo in CAMPOS}
    _validar(novos, usuario=usuario, farm=ciclo.farm)
    return reversible.editar(ciclo, novos, usuario=usuario, motivo=motivo)


@transaction.atomic
def excluir_ciclo(
    ciclo: BreedingCycle, *, usuario, motivo: str, cascata: bool = False
) -> BreedingCycle:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para excluir ciclos reprodutivos.")
    return reversible.excluir(ciclo, usuario=usuario, motivo=motivo, cascata=cascata)


@transaction.atomic
def restaurar_ciclo(ciclo: BreedingCycle, *, usuario) -> BreedingCycle:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError(
            "Você não tem permissão para restaurar ciclos reprodutivos."
        )
    existente = (
        BreedingCycle.objects.filter(farm=ciclo.farm, season=ciclo.season)
        .exclude(status=Status.EXCLUIDA)
        .exclude(pk=ciclo.pk)
        .first()
    )
    if existente is not None:
        raise BusinessError(
            f"Já existe o ciclo {existente.code} para esta fazenda e safra."
        )
    return reversible.restaurar(ciclo, usuario=usuario)
