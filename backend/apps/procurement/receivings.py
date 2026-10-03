"""Recebimento e quebra de viagem.

**Quebra** = `(peso de origem − peso recebido) ÷ peso de origem`, derivada.
Só mede e alerta (pendência #23): não desconta nada do valor dos animais.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import reversible
from apps.core.exceptions import BlockingDependencyError, BusinessError
from apps.core.money import safe_div
from apps.core.permissions import pode_editar_confirmado, pode_excluir_confirmado
from apps.core.reversible import Status
from apps.herd.permissions import tem_acesso_de_escrita_a_fazenda
from apps.organizations.models import Season, SeasonStatus
from apps.procurement import selectors
from apps.procurement.codes import proximo_codigo
from apps.procurement.commitments import (
    bloqueio_do_acerto_aprovado,
    exigir_acerto_aberto,
)
from apps.procurement.lines import sincronizar_linhas
from apps.procurement.models import Receiving, ReceivingLine, Trip
from apps.procurement.permissions import pode_lancar_no_ciclo

CAMPOS_EDITAVEIS = ("date", "notes")
CAMPOS_DA_LINHA = (
    "load",
    "received_qty",
    "received_weight_kg",
    "received_category",
    "occurrence",
)


# --------------------------------------------------------------------------
# Derivados
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QuebraDeViagem:
    peso_origem_kg: Decimal
    peso_recebido_kg: Decimal
    quebra_kg: Decimal
    #: em pontos percentuais (2,5 = 2,5%); negativo = chegou mais do que saiu
    quebra_percentual: Decimal | None
    acima_do_limite: bool
    #: alguma carga não tinha os dois pesos e ficou de fora da conta
    parcial: bool


def quebra_da_viagem(recebimento: Receiving) -> QuebraDeViagem | None:
    """`None` quando nenhuma carga tem os dois pesos — "—" na tela, nunca
    `0%`. Peso de origem zero também devolve `None` (regra 3)."""
    origem = Decimal("0")
    recebido = Decimal("0")
    pares = 0
    linhas = list(recebimento.lines.select_related("load"))
    for linha in linhas:
        peso_origem = linha.load.origin_weight_kg
        if peso_origem is not None and linha.received_weight_kg is not None:
            origem += peso_origem
            recebido += linha.received_weight_kg
            pares += 1
    if not pares:
        return None
    razao = safe_div(origem - recebido, origem)
    percentual = razao * 100 if razao is not None else None
    limite = Decimal(settings.QUEBRA_ALERTA_PERCENTUAL)
    return QuebraDeViagem(
        peso_origem_kg=origem,
        peso_recebido_kg=recebido,
        quebra_kg=origem - recebido,
        quebra_percentual=percentual,
        acima_do_limite=percentual is not None and percentual > limite,
        parcial=pares < len(linhas),
    )


def diferenca_de_cabecas(linha: ReceivingLine) -> int | None:
    """Embarcadas − recebidas; `None` se não se sabe quantas embarcaram."""
    embarcadas = linha.load.shipped_qty
    return None if embarcadas is None else embarcadas - linha.received_qty


def cabecas_recebidas(recebimento: Receiving) -> int:
    return sum(linha.received_qty for linha in recebimento.lines.all())


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------


def _validar_recebimento(dados: dict, viagem: Trip, *, usuario) -> None:
    compromisso = viagem.commitment
    if viagem.status != Status.CONFIRMADA:
        raise BusinessError(f"A viagem {viagem.code} está excluída.")
    if not tem_acesso_de_escrita_a_fazenda(usuario, compromisso.destination_farm):
        raise BusinessError(
            f"Você não tem permissão de lançamento em {compromisso.destination_farm}."
        )
    data = dados.get("date")
    if data is None:
        raise BusinessError("Informe a data do recebimento.")
    if data > timezone.localdate():
        raise BusinessError("Recebimento com data futura não é permitido.")
    if data < viagem.pickup_date:
        raise BusinessError(
            f"O recebimento não pode ser antes da retirada ({viagem.pickup_date:%d/%m/%Y})."
        )
    season = compromisso.season
    if season.status == SeasonStatus.ENCERRADA:
        raise BusinessError(
            f"A safra {season.name} está encerrada. Reabra a safra antes de lançar."
        )


def _validar_linhas(linhas: list[dict], viagem: Trip) -> None:
    if not linhas:
        raise BusinessError("Informe o que chegou: pelo menos uma linha.")
    cargas = {c.pk for c in viagem.loads.all()}
    vistos = set()
    for linha in linhas:
        carga = linha["load"]
        if carga.pk not in cargas:
            raise BusinessError(f"A carga {carga} não pertence à viagem {viagem.code}.")
        if carga.pk in vistos:
            raise BusinessError(
                f"O item {carga.item.number} aparece duas vezes no recebimento."
            )
        vistos.add(carga.pk)
        if (linha.get("received_qty") or 0) < 0:
            raise BusinessError("Cabeças recebidas não podem ser negativas.")
        peso = linha.get("received_weight_kg")
        if peso is not None and Decimal(peso) <= 0:
            raise BusinessError(
                "O peso recebido, quando informado, deve ser maior que zero."
            )
        categoria = linha.get("received_category")
        if categoria is not None and not categoria.is_active:
            raise BusinessError(f"A categoria {categoria} está inativa.")


def _sincronizar_linhas(
    recebimento: Receiving, linhas: list[dict], *, usuario, motivo=""
):
    _validar_linhas(linhas, recebimento.trip)

    def _criar(entrada: dict) -> ReceivingLine:
        linha = ReceivingLine(receiving=recebimento)
        for campo in CAMPOS_DA_LINHA:
            if campo in entrada:
                setattr(linha, campo, entrada[campo])
        linha.occurrence = linha.occurrence or ""
        linha.save()
        return linha

    return sincronizar_linhas(
        existentes=list(recebimento.lines.all()),
        entradas=linhas,
        campos=CAMPOS_DA_LINHA,
        criar=_criar,
        usuario=usuario,
        motivo=motivo,
    )


# --------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------


@transaction.atomic
def criar_recebimento(
    *, usuario, viagem: Trip, linhas: list[dict], date: datetime.date, notes: str = ""
) -> Receiving:
    if not pode_lancar_no_ciclo(usuario):
        raise BusinessError("Você não tem permissão para lançar recebimentos.")
    viagem = Trip.objects.select_for_update().get(pk=viagem.pk)
    exigir_acerto_aberto(viagem.commitment, "lançar um recebimento")
    if viagem.receivings.exclude(status=Status.EXCLUIDA).exists():
        raise BusinessError(
            f"A viagem {viagem.code} já tem recebimento. Corrija o que existe "
            "em vez de lançar outro."
        )
    dados = {"date": date, "notes": notes or ""}
    _validar_recebimento(dados, viagem, usuario=usuario)

    season = Season.objects.select_for_update().get(pk=viagem.commitment.season_id)
    recebimento = Receiving(**dados, trip=viagem, created_by=usuario)
    recebimento.code = proximo_codigo(Receiving, "RB", season)
    recebimento.save()
    _sincronizar_linhas(recebimento, linhas, usuario=usuario)
    return reversible.confirmar(recebimento, usuario=usuario)


@transaction.atomic
def editar_recebimento(
    recebimento: Receiving,
    dados: dict,
    linhas: list[dict] | None,
    *,
    usuario,
    motivo: str,
) -> Receiving:
    if not pode_editar_confirmado(usuario):
        raise BusinessError("Você não tem permissão para editar recebimento.")
    viagem = recebimento.trip
    exigir_acerto_aberto(viagem.commitment, "corrigir o recebimento")
    novos = {
        campo: dados.get(campo, getattr(recebimento, campo))
        for campo in CAMPOS_EDITAVEIS
    }
    _validar_recebimento(novos, viagem, usuario=usuario)
    recebimento = reversible.editar(recebimento, novos, usuario=usuario, motivo=motivo)
    if linhas is not None:
        _sincronizar_linhas(recebimento, linhas, usuario=usuario, motivo=motivo)
    return recebimento


@transaction.atomic
def excluir_recebimento(
    recebimento: Receiving, *, usuario, motivo: str, cascata: bool = False
) -> Receiving:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para excluir recebimento.")
    return reversible.excluir(
        recebimento, usuario=usuario, motivo=motivo, cascata=cascata
    )


@transaction.atomic
def restaurar_recebimento(recebimento: Receiving, *, usuario) -> Receiving:
    if not pode_excluir_confirmado(usuario):
        raise BusinessError("Você não tem permissão para restaurar recebimento.")
    if recebimento.trip.status != Status.CONFIRMADA:
        raise BusinessError(
            f"A viagem {recebimento.trip.code} está excluída: restaure a viagem antes."
        )
    if (
        Receiving.objects.filter(trip=recebimento.trip)
        .exclude(status=Status.EXCLUIDA)
        .exists()
    ):
        raise BusinessError("A viagem já tem outro recebimento.")
    if recebimento.bloqueios():
        raise BlockingDependencyError(
            f"Não é possível restaurar: {recebimento.bloqueios()[0]}"
        )
    return reversible.restaurar(recebimento, usuario=usuario)


def bloqueios_do_recebimento(recebimento: Receiving) -> list:
    bloqueios = []
    compromisso = recebimento.trip.commitment
    if compromisso.season.status == SeasonStatus.ENCERRADA:
        bloqueios.append(
            f"a safra {compromisso.season.name} está encerrada. Peça a um "
            "administrador para reabrir a safra antes de editar ou excluir."
        )
    acerto = selectors.acerto_aprovado(compromisso)
    if acerto is not None:
        bloqueios.append(bloqueio_do_acerto_aprovado(acerto, "mexer no recebimento"))
    return bloqueios
