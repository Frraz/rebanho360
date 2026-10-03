"""Escrita. Toda operação que altera estado passa por aqui."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import registrar_auditoria
from apps.core import reversible
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.serialization import diff_fields, snapshot
from apps.costs.models import CostCenter, CostClass, CostEntry
from apps.herd.permissions import (
    pode_lancar_em_safra_encerrada,
    tem_acesso_de_escrita_a_fazenda,
)
from apps.herd.services import season_para_data
from apps.organizations.models import SeasonStatus


@transaction.atomic
def salvar_cadastro(instancia, *, usuario, criando: bool):
    """Centro/classe de custo: cadastro estrutural, sem efeito a desfazer."""
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


def centro_de_custo_por_nome(nome: str) -> CostCenter:
    """Os centros que o sistema usa por conta própria (DESPESA GADO,
    COMISSÃO, IMPOSTO E TAXAS) vêm da migração `costs.0004`."""
    centro = CostCenter.objects.filter(name=nome, is_active=True).first()
    if centro is None:
        raise BusinessError(
            f"O centro de custo {nome} não está cadastrado ou está inativo. "
            "Cadastre-o em Centros de custo antes de continuar."
        )
    return centro


def classe_de_custo_por_nome(nome: str) -> CostClass:
    classe = CostClass.objects.filter(name=nome, is_active=True).first()
    if classe is None:
        raise BusinessError(f"A classe de custo {nome} não está cadastrada.")
    return classe


def _validar_lancamento(
    *, date, farm, cost_center, cost_class, amount, description, lot, usuario, season
):
    """Regras do lançamento (docs/regras-negocio/02). Devolve a safra."""
    if amount is None or Decimal(amount) <= 0:
        raise BusinessError("O valor do custo deve ser maior que zero.")
    if not description or not description.strip():
        raise BusinessError("Informe a descrição do custo.")
    if date > timezone.localdate():
        raise BusinessError("Custo com data futura não é permitido.")
    if not cost_center.is_active:
        raise BusinessError(f"O centro de custo {cost_center} está inativo.")
    if not cost_class.is_active:
        raise BusinessError(f"A classe {cost_class} está inativa.")
    if not tem_acesso_de_escrita_a_fazenda(usuario, farm):
        raise BusinessError(f"Você não tem permissão de lançamento em {farm}.")
    if lot is not None and lot.farm_id != farm.pk:
        raise BusinessError(
            f"O lote {lot.code} é da fazenda {lot.farm}, não de {farm}. "
            "Custo direto só pode apontar para lote da própria fazenda."
        )

    season = season or season_para_data(date)
    if season is None:
        raise BusinessError(
            "Não há safra cadastrada que cubra esta data. Cadastre a safra antes."
        )
    if season.status == SeasonStatus.ENCERRADA and not pode_lancar_em_safra_encerrada(
        usuario
    ):
        raise BusinessError(
            f"A safra {season.name} está encerrada. Só o administrador pode "
            "lançar nela — reabra a safra antes, ou lance na safra corrente."
        )
    return season


@transaction.atomic
def registrar_custo(
    *,
    date,
    farm,
    cost_center,
    cost_class,
    amount,
    description,
    usuario,
    payer=None,
    lot=None,
    notes: str = "",
    season=None,
    source_purchase=None,
) -> CostEntry:
    season = _validar_lancamento(
        date=date,
        farm=farm,
        cost_center=cost_center,
        cost_class=cost_class,
        amount=amount,
        description=description,
        lot=lot,
        usuario=usuario,
        season=season,
    )
    custo = CostEntry(
        date=date,
        season=season,
        farm=farm,
        cost_center=cost_center,
        cost_class=cost_class,
        amount=amount,
        description=description.strip(),
        payer=payer,
        lot=lot,
        source_purchase=source_purchase,
        notes=notes,
        created_by=usuario,
    )
    custo.save()
    return reversible.confirmar(custo, usuario=usuario)


def _recusar_se_gerado_por_compra(custo: CostEntry, acao: str) -> None:
    if custo.source_purchase_id:
        raise BusinessError(
            f"Este custo foi gerado pela compra {custo.source_purchase.code} e "
            f"não pode ser {acao} direto. Corrija a compra — os custos "
            "acompanham."
        )


@transaction.atomic
def editar_custo(custo: CostEntry, dados: dict, *, usuario, motivo: str) -> CostEntry:
    _recusar_se_gerado_por_compra(custo, "editado")
    if not pode_editar_confirmado(usuario):
        raise BusinessError("Você não tem permissão para editar este custo.")

    novo = {
        "date": dados.get("date", custo.date),
        "farm": dados.get("farm", custo.farm),
        "cost_center": dados.get("cost_center", custo.cost_center),
        "cost_class": dados.get("cost_class", custo.cost_class),
        "amount": dados.get("amount", custo.amount),
        "description": dados.get("description", custo.description),
        "lot": dados.get("lot", custo.lot),
    }
    season = _validar_lancamento(**novo, usuario=usuario, season=None)
    campos = {
        **novo,
        "season": season,
        "payer": dados.get("payer", custo.payer),
        "notes": dados.get("notes", custo.notes),
    }
    return reversible.editar(custo, campos, usuario=usuario, motivo=motivo)


@transaction.atomic
def excluir_custo(
    custo: CostEntry, *, usuario, motivo: str, cascata: bool = False
) -> CostEntry:
    _recusar_se_gerado_por_compra(custo, "excluído")
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para excluir este custo.")
    return reversible.excluir(custo, usuario=usuario, motivo=motivo, cascata=cascata)


@transaction.atomic
def restaurar_custo(custo: CostEntry, *, usuario) -> CostEntry:
    _recusar_se_gerado_por_compra(custo, "restaurado")
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para restaurar este custo.")
    if custo.bloqueios():
        raise BlockingDependencyError(
            f"Não é possível restaurar: {custo.bloqueios()[0]}"
        )
    return reversible.restaurar(custo, usuario=usuario)
