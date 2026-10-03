"""Formatação brasileira de números: milhar com ponto, decimal com vírgula.

Só apresentação. O valor continua `Decimal` até a última linha — arredondar
é o último passo da cadeia (ADR 0005).
"""

from decimal import Decimal

from apps.core.money import quantize_money


def numero_br(valor: Decimal, casas: int = 2) -> str:
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "\0").replace(".", ",").replace("\0", ".")


def dinheiro_br(valor) -> str:
    """`Decimal` → "R$ 1.234,56". `None` → "—": dado faltando nunca vira
    `R$ 0,00` (regra 3 do CLAUDE.md)."""
    if valor is None or valor == "":
        return "—"
    return "R$ " + numero_br(quantize_money(Decimal(valor)), 2)
