"""Custo por hora da máquina — **calculado** do que foi lançado (regra 6)."""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from apps.core.money import safe_div
from apps.core.reversible import Status
from apps.infrastructure.models import Machine, MachineLog

ZERO = Decimal("0")


@dataclass(frozen=True)
class CustoHora:
    horas: Decimal
    litros: Decimal | None
    combustivel: Decimal | None
    manutencao: Decimal | None
    consumo_l_h: Decimal | None  # litros por hora
    custo_hora_combustivel: Decimal | None
    custo_hora_manutencao: Decimal | None
    custo_hora: Decimal | None  # combustível + manutenção, por hora

    @property
    def total(self) -> Decimal:
        return (self.combustivel or ZERO) + (self.manutencao or ZERO)


def _soma(qs, campo):
    return qs.aggregate(s=Sum(campo))["s"]


def custo_hora_da_maquina(machine: Machine, *, start=None, end=None) -> CustoHora:
    logs = MachineLog.objects.filter(machine=machine, status=Status.CONFIRMADA)
    if start:
        logs = logs.filter(date__gte=start)
    if end:
        logs = logs.filter(date__lte=end)
    horas = _soma(logs, "hours") or ZERO
    litros = _soma(logs, "fuel_liters")
    combustivel = _soma(logs, "fuel_cost")
    manutencao = _soma(logs, "maintenance_cost")
    gasto = None
    if combustivel is not None or manutencao is not None:
        gasto = (combustivel or ZERO) + (manutencao or ZERO)
    return CustoHora(
        horas=horas,
        litros=litros,
        combustivel=combustivel,
        manutencao=manutencao,
        consumo_l_h=safe_div(litros, horas) if litros is not None else None,
        custo_hora_combustivel=(
            safe_div(combustivel, horas) if combustivel is not None else None
        ),
        custo_hora_manutencao=(
            safe_div(manutencao, horas) if manutencao is not None else None
        ),
        custo_hora=safe_div(gasto, horas) if gasto is not None else None,
    )
