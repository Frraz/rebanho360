"""Funções pequenas de apoio ao seed: datas, Decimal sem `float` e os preços.

Nenhum valor monetário, de peso ou percentual passa por `float` (ADR 0005):
os números aleatórios saem de `random.Random.randint` sobre inteiros escalados.
"""

import datetime
from decimal import ROUND_HALF_UP, Decimal

D = Decimal

#: Referência da @ do boi gordo (R$/@ de carcaça) ao longo do período simulado.
#: Fictícia, mas com a forma do mercado: alta firme entre as safras.
PONTOS_DA_ARROBA = [
    (datetime.date(2024, 7, 1), D("235")),
    (datetime.date(2025, 1, 1), D("252")),
    (datetime.date(2025, 7, 1), D("298")),
    (datetime.date(2026, 1, 1), D("322")),
    (datetime.date(2026, 10, 1), D("338")),
]


def q2(valor) -> Decimal:
    return Decimal(valor).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def q3(valor) -> Decimal:
    return Decimal(valor).quantize(D("0.001"), rounding=ROUND_HALF_UP)


def mes_mais(data: datetime.date, n: int) -> datetime.date:
    """Primeiro dia do mês `n` meses depois de `data`."""
    total = data.year * 12 + data.month - 1 + n
    return datetime.date(total // 12, total % 12 + 1, 1)


def fim_do_mes(data: datetime.date) -> datetime.date:
    return mes_mais(data, 1) - datetime.timedelta(days=1)


def dias(n: int) -> datetime.timedelta:
    return datetime.timedelta(days=n)


def decimal_entre(rnd, minimo, maximo, escala: int = 100) -> Decimal:
    """Decimal uniforme entre `minimo` e `maximo`, em passos de `1/escala`."""
    inferior = int(D(minimo) * escala)
    superior = int(D(maximo) * escala)
    return D(rnd.randint(inferior, superior)) / D(escala)


def arroba_em(data: datetime.date) -> Decimal:
    """R$/@ na data, por interpolação linear entre os pontos de referência."""
    pontos = PONTOS_DA_ARROBA
    if data <= pontos[0][0]:
        return pontos[0][1]
    if data >= pontos[-1][0]:
        return pontos[-1][1]
    for (d0, v0), (d1, v1) in zip(pontos, pontos[1:], strict=False):
        if d0 <= data <= d1:
            fracao = D((data - d0).days) / D((d1 - d0).days)
            return v0 + (v1 - v0) * fracao
    return pontos[-1][1]


def fator_de_preco(data: datetime.date) -> Decimal:
    """Quanto o preço do gado magro acompanha a @ (1,00 = @ a R$ 250)."""
    return arroba_em(data) / D("250")


def inteiro_proporcional(total: int, pesos: list[int]) -> list[int]:
    """Reparte `total` (inteiro) na proporção dos `pesos`, sem perder cabeça."""
    soma = sum(pesos)
    if soma <= 0 or total <= 0:
        return [0] * len(pesos)
    partes = [total * p // soma for p in pesos]
    resto = total - sum(partes)
    # O resto vai para as maiores frações, para não depender da ordem da lista.
    ordem = sorted(
        range(len(pesos)), key=lambda i: (total * pesos[i]) % soma, reverse=True
    )
    for i in ordem[:resto]:
        partes[i] += 1
    return partes
