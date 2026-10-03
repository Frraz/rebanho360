"""Viagem, embarque e frete.

O frete **previsto** é derivado (critério × tarifa × o que embarcou); o
**realizado** é digitado. O acerto usa o realizado quando existe e, sem ele, o
previsto — dizendo qual usou (`FreteDaViagem.origem`).
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from apps.core import reversible
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.money import quantize_money
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.herd.permissions import tem_acesso_de_escrita_a_fazenda
from apps.organizations.models import Season, SeasonStatus
from apps.partners.models import PartnerRoleChoice
from apps.procurement import selectors
from apps.procurement.codes import codigo_da_etapa
from apps.procurement.commitments import (
    bloqueio_do_acerto_aprovado,
    exigir_acerto_aberto,
)
from apps.procurement.lines import sincronizar_linhas
from apps.procurement.models import (
    Commitment,
    FreightCriterion,
    Trip,
    TripLoad,
)
from apps.procurement.permissions import pode_lancar_no_ciclo

CAMPOS_EDITAVEIS = (
    "pickup_date",
    "carrier",
    "driver_name",
    "vehicle",
    "vehicle_plate",
    "adf_number",
    "distance_km",
    "freight_criterion",
    "freight_rate",
    "freight_actual",
    "freight_due_date",
    "notes",
)

CAMPOS_DA_CARGA = ("item", "planned_qty", "shipped_qty", "origin_weight_kg")


# --------------------------------------------------------------------------
# Frete — derivados
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FreteDaViagem:
    previsto: Decimal | None
    realizado: Decimal | None
    final: Decimal | None
    #: "realizado", "previsto" ou None (sem frete nenhum)
    origem: str | None


def cabecas_da_viagem(viagem: Trip) -> int:
    """O que embarcou; sem o embarcado informado, o programado."""
    return sum(
        carga.shipped_qty if carga.shipped_qty is not None else carga.planned_qty
        for carga in viagem.loads.all()
    )


def frete_previsto(viagem: Trip) -> Decimal | None:
    """`None` quando falta dado — nunca `0,00` (regra 3)."""
    criterio, tarifa = viagem.freight_criterion, viagem.freight_rate
    if not criterio or tarifa is None:
        return None
    tarifa = Decimal(tarifa)
    if criterio == FreightCriterion.POR_VIAGEM:
        return quantize_money(tarifa)
    if criterio == FreightCriterion.POR_KM:
        km = viagem.distance_km or viagem.commitment.distance_km
        return quantize_money(Decimal(km) * tarifa) if km else None
    if criterio == FreightCriterion.POR_CABECA:
        cabecas = cabecas_da_viagem(viagem)
        return quantize_money(Decimal(cabecas) * tarifa) if cabecas else None
    if criterio == FreightCriterion.POR_KG:
        pesos = [carga.origin_weight_kg for carga in viagem.loads.all()]
        if not pesos or any(peso is None for peso in pesos):
            return None
        return quantize_money(sum(pesos, Decimal("0")) * tarifa)
    return None


def frete_da_viagem(viagem: Trip) -> FreteDaViagem:
    previsto = frete_previsto(viagem)
    realizado = viagem.freight_actual
    if realizado is not None:
        return FreteDaViagem(previsto, realizado, realizado, "realizado")
    if previsto is not None:
        return FreteDaViagem(previsto, None, previsto, "previsto")
    return FreteDaViagem(None, None, None, None)


def embarcado_do_item(item) -> int:
    """Cabeças embarcadas do item em todas as viagens que não saíram."""
    cargas = TripLoad.objects.filter(item=item).exclude(trip__status=Status.EXCLUIDA)
    return sum(
        c.shipped_qty if c.shipped_qty is not None else c.planned_qty for c in cargas
    )


def avisos_da_viagem(viagem: Trip) -> list[str]:
    """Embarcar acima do compromisso avisa (não bloqueia: o contrato muda)."""
    avisos = []
    for carga in viagem.loads.all():
        item = carga.item
        total = embarcado_do_item(item)
        if total > item.head_count:
            avisos.append(
                f"Item {item.number}: {total} cabeças embarcadas, acima das "
                f"{item.head_count} do compromisso."
            )
    return avisos


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------


def _validar_viagem(dados: dict, compromisso: Commitment, *, usuario) -> None:
    if compromisso.status != Status.CONFIRMADA:
        raise BusinessError("A viagem só se lança depois da aprovação do compromisso.")
    if not tem_acesso_de_escrita_a_fazenda(usuario, compromisso.destination_farm):
        raise BusinessError(
            f"Você não tem permissão de lançamento em {compromisso.destination_farm}."
        )
    if dados.get("pickup_date") is None:
        raise BusinessError("Informe a data da retirada.")
    carrier = dados.get("carrier")
    if (
        carrier is not None
        and not carrier.roles.filter(role=PartnerRoleChoice.TRANSPORTADOR).exists()
    ):
        raise BusinessError(
            f"{carrier} não tem o papel de Transportador. "
            "Acrescente o papel no cadastro do parceiro."
        )
    criterio, tarifa = dados.get("freight_criterion"), dados.get("freight_rate")
    if criterio and tarifa is None:
        raise BusinessError("Informe a tarifa do frete para o critério escolhido.")
    if tarifa is not None and not criterio:
        raise BusinessError(
            "Escolha o critério do frete (por cabeça, km, kg ou viagem)."
        )
    if tarifa is not None and Decimal(tarifa) < 0:
        raise BusinessError("A tarifa do frete não pode ser negativa.")
    realizado = dados.get("freight_actual")
    if realizado is not None and Decimal(realizado) < 0:
        raise BusinessError("O frete realizado não pode ser negativo.")
    distancia = dados.get("distance_km")
    if distancia is not None and distancia < 0:
        raise BusinessError("A distância não pode ser negativa.")


def _validar_cargas(cargas: list[dict], compromisso: Commitment) -> None:
    if not cargas:
        raise BusinessError("A viagem precisa levar pelo menos um item.")
    itens = {i.pk for i in compromisso.items.all()}
    vistos = set()
    for carga in cargas:
        item = carga["item"]
        if item.pk not in itens:
            raise BusinessError(
                f"O item {item.number} não pertence ao compromisso {compromisso.code}."
            )
        if item.pk in vistos:
            raise BusinessError(f"O item {item.number} aparece duas vezes na viagem.")
        vistos.add(item.pk)
        if (carga.get("planned_qty") or 0) < 0 or (carga.get("shipped_qty") or 0) < 0:
            raise BusinessError("Cabeças não podem ser negativas.")
        peso = carga.get("origin_weight_kg")
        if peso is not None and Decimal(peso) <= 0:
            raise BusinessError(
                "O peso de origem, quando informado, deve ser maior que zero."
            )
        if not (carga.get("planned_qty") or carga.get("shipped_qty")):
            raise BusinessError(
                f"Item {item.number}: informe as cabeças programadas ou embarcadas."
            )


def _sincronizar_cargas(viagem: Trip, cargas: list[dict], *, usuario, motivo=""):
    _validar_cargas(cargas, viagem.commitment)

    def _impedir_retirada(carga: TripLoad):
        if carga.received_lines.exists():
            raise BlockingDependencyError(
                f"Não é possível retirar o item {carga.item.number} da viagem: "
                "ele já foi recebido. Corrija antes o recebimento."
            )

    def _criar(entrada: dict) -> TripLoad:
        carga = TripLoad(trip=viagem)
        for campo in CAMPOS_DA_CARGA:
            if campo in entrada:
                setattr(carga, campo, entrada[campo])
        carga.planned_qty = carga.planned_qty or 0
        carga.save()
        return carga

    return sincronizar_linhas(
        existentes=list(viagem.loads.all()),
        entradas=cargas,
        campos=CAMPOS_DA_CARGA,
        criar=_criar,
        usuario=usuario,
        motivo=motivo,
        antes_de_retirar=_impedir_retirada,
    )


# --------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------


@transaction.atomic
def criar_viagem(
    *, usuario, compromisso: Commitment, cargas: list[dict], **dados
) -> Trip:
    """Registra a viagem **já confirmada**: viagem não tem rascunho a revisar."""
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para lançar viagens.")
    compromisso = Commitment.objects.select_for_update().get(pk=compromisso.pk)
    exigir_acerto_aberto(compromisso, "lançar uma viagem")
    dados = {campo: dados.get(campo) for campo in CAMPOS_EDITAVEIS} | {
        "driver_name": dados.get("driver_name") or "",
        "vehicle": dados.get("vehicle") or "",
        "adf_number": (dados.get("adf_number") or "").strip(),
        "vehicle_plate": (dados.get("vehicle_plate") or "").upper(),
        "freight_criterion": dados.get("freight_criterion") or "",
        "notes": dados.get("notes") or "",
    }
    if dados["distance_km"] is None:
        dados["distance_km"] = compromisso.distance_km
    _validar_viagem(dados, compromisso, usuario=usuario)

    season = Season.objects.select_for_update().get(pk=compromisso.season_id)
    viagem = Trip(**dados, commitment=compromisso, created_by=usuario)
    viagem.code = codigo_da_etapa(
        Trip, compromisso=compromisso, sufixo="V", legado="VG", season=season
    )
    viagem.save()
    _sincronizar_cargas(viagem, cargas, usuario=usuario)
    return reversible.confirmar(viagem, usuario=usuario)


@transaction.atomic
def editar_viagem(
    viagem: Trip, dados: dict, cargas: list[dict] | None, *, usuario, motivo: str
) -> Trip:
    if not pode_editar_confirmado(usuario):
        raise BusinessError("Você não tem permissão para editar viagem.")
    exigir_acerto_aberto(viagem.commitment, "corrigir a viagem")

    novos = {
        campo: dados.get(campo, getattr(viagem, campo)) for campo in CAMPOS_EDITAVEIS
    }
    novos["vehicle_plate"] = (novos["vehicle_plate"] or "").upper()
    novos["adf_number"] = (novos.get("adf_number") or "").strip()
    _validar_viagem(novos, viagem.commitment, usuario=usuario)
    viagem = reversible.editar(viagem, novos, usuario=usuario, motivo=motivo)
    if cargas is not None:
        _sincronizar_cargas(viagem, cargas, usuario=usuario, motivo=motivo)
    return viagem


@transaction.atomic
def excluir_viagem(
    viagem: Trip, *, usuario, motivo: str, cascata: bool = False
) -> Trip:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para excluir viagem.")
    return reversible.excluir(viagem, usuario=usuario, motivo=motivo, cascata=cascata)


@transaction.atomic
def restaurar_viagem(viagem: Trip, *, usuario) -> Trip:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para restaurar viagem.")
    if viagem.commitment.status != Status.CONFIRMADA:
        raise BusinessError(
            "O compromisso desta viagem está excluído: restaure o compromisso antes."
        )
    if viagem.bloqueios():
        raise BlockingDependencyError(
            f"Não é possível restaurar: {viagem.bloqueios()[0]}"
        )
    return reversible.restaurar(viagem, usuario=usuario)


def bloqueios_da_viagem(viagem: Trip) -> list:
    bloqueios = []
    compromisso = viagem.commitment
    if compromisso.season.status == SeasonStatus.ENCERRADA:
        bloqueios.append(
            f"a safra {compromisso.season.name} está encerrada. Peça a um "
            "administrador para reabrir a safra antes de editar ou excluir."
        )
    acerto = selectors.acerto_aprovado(compromisso)
    if acerto is not None:
        bloqueios.append(bloqueio_do_acerto_aprovado(acerto, "mexer na viagem"))
    return bloqueios
