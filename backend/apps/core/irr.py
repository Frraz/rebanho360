"""Taxa interna de retorno (TIR) — `Decimal`, sem `float` (ADR 0005).

A TIR é a taxa `r` que zera o valor presente dos fluxos: `Σ fluxo_t ÷ (1+r)^t = 0`.
Sem inversão de sinal (só saídas, ou só entradas) ela não existe: devolve `None`,
que a tela mostra como "—" (regra 3), nunca `0`.
"""

from decimal import Decimal

ZERO = Decimal("0")
UM = Decimal("1")


def valor_presente(fluxos: list[Decimal], taxa: Decimal) -> Decimal:
    base = UM + taxa
    return sum((f / (base**t) for t, f in enumerate(fluxos)), ZERO)


def taxa_interna_de_retorno(
    fluxos: list[Decimal], *, tolerancia: Decimal = Decimal("0.0000001")
) -> Decimal | None:
    """TIR **por período** (se os fluxos são mensais, é ao mês), por bisecção.

    Procura entre −99% e +10.000% por período. `None` se os fluxos não trocam
    de sinal ou se nenhuma taxa dessa faixa zera o valor presente.
    """
    if not fluxos or not (any(f > 0 for f in fluxos) and any(f < 0 for f in fluxos)):
        return None
    baixo, alto = Decimal("-0.99"), Decimal("100")
    vp_baixo, vp_alto = valor_presente(fluxos, baixo), valor_presente(fluxos, alto)
    if vp_baixo == 0:
        return baixo
    if vp_alto == 0:
        return alto
    if (vp_baixo > 0) == (vp_alto > 0):
        return None
    for _ in range(300):
        meio = (baixo + alto) / 2
        vp_meio = valor_presente(fluxos, meio)
        if abs(alto - baixo) < tolerancia or vp_meio == 0:
            return meio
        if (vp_meio > 0) == (vp_baixo > 0):
            baixo, vp_baixo = meio, vp_meio
        else:
            alto = meio
    return (baixo + alto) / 2


def anualizar(taxa_mensal: Decimal | None) -> Decimal | None:
    """`(1 + r)^12 − 1` — a taxa mensal composta em um ano."""
    if taxa_mensal is None:
        return None
    return (UM + taxa_mensal) ** 12 - UM
