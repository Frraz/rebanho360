"""Regras de Decimal, arredondamento e divisão seguras.

Fonte única da verdade para dinheiro, peso e arroba. `Decimal` sempre,
`float` nunca. Ver ADR 0005.
"""

from decimal import ROUND_HALF_UP, Decimal

KG_PER_ARROBA = Decimal("15")
ROUNDING = ROUND_HALF_UP

MONEY_PLACES = Decimal("0.01")
WEIGHT_PLACES = Decimal("0.001")
ARROBA_PLACES = Decimal("0.01")
PERCENT_PLACES = Decimal("0.0001")


def quantize_money(value: Decimal) -> Decimal:
    """Arredonda para 2 casas, arredondamento comercial brasileiro."""
    return value.quantize(MONEY_PLACES, rounding=ROUNDING)


def quantize_weight(value: Decimal) -> Decimal:
    """Arredonda peso para 3 casas (kg)."""
    return value.quantize(WEIGHT_PLACES, rounding=ROUNDING)


def quantize_arroba(value: Decimal) -> Decimal:
    """Arredonda arroba para 2 casas."""
    return value.quantize(ARROBA_PLACES, rounding=ROUNDING)


def quantize_percent(value: Decimal) -> Decimal:
    """Arredonda percentual para 4 casas internas (2 na tela)."""
    return value.quantize(PERCENT_PLACES, rounding=ROUNDING)


def safe_div(
    numerador: Decimal | int | None, denominador: Decimal | int | None
) -> Decimal | None:
    """Divide sem jamais lançar `ZeroDivisionError` nem devolver `0` mentiroso.

    Falta de dado é estado normal, não defeito: divisor zero (ou None)
    devolve `None`, que a tela mostra como "—" ou "pendente".
    """
    if not denominador:
        return None
    if numerador is None:
        return None
    # int ÷ int em Python é `float`, e float é proibido para valor, peso e
    # arroba (regra 2): o resultado é sempre `Decimal`.
    if isinstance(numerador, int):
        numerador = Decimal(numerador)
    return numerador / denominador


def kg_to_arroba(weight_kg: Decimal) -> Decimal:
    """Converte peso (kg) para arrobas, sem arredondar no meio da conta."""
    return weight_kg / KG_PER_ARROBA
