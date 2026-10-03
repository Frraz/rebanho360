# ADR 0005 — Decimal, arredondamento e divisor zero

**Data:** 2026-09-30 · **Status:** Aceita

## Problema

O sistema movimenta R$ 2,4 milhões em compras e R$ 2,3 milhões em vendas por safra. Como representar valor e peso, como arredondar, e o que fazer quando o divisor é zero?

A planilha responde essas perguntas assim: `float` binário do Excel, arredondamento implícito na exibição, e `#DIV/0!` — que hoje ocupa centenas de linhas das abas `COMPRA DE GADO`, `VENDAS` e `ADF E COMPRAS`.

## Decisão

### `Decimal` sempre. `float` nunca.

Para valor monetário, peso, arroba e percentual. `DecimalField` no banco, `Decimal` em Python, sem exceção.

### Um módulo define as regras

```python
# apps/core/money.py
KG_PER_ARROBA  = Decimal("15")
ROUNDING       = ROUND_HALF_UP       # comercial brasileiro

MONEY_PLACES   = Decimal("0.01")     # R$    2 casas
WEIGHT_PLACES  = Decimal("0.001")    # kg    3 casas
ARROBA_PLACES  = Decimal("0.01")     # @     2 casas
PERCENT_PLACES = Decimal("0.0001")   # %     4 internas, 2 na tela
```

### Arredondar só no fim

Na gravação final e na apresentação. **Nunca** no meio de uma cadeia de cálculo.

### Divisor zero devolve `None`

```python
def safe_div(numerador, denominador):
    if not denominador:
        return None
    return numerador / denominador
```

`None` chega à tela como **"—"** ou **"pendente"**. Nunca `0`, nunca erro.

## Alternativas descartadas

**`float`.** `0.1 + 0.2 != 0.3`. Em um lançamento é invisível; em 235 lançamentos somados e rateados por lote, aparece como centavo perdido no fechamento — e ninguém consegue explicar de onde veio.

**Inteiro em centavos.** Elimina erro de representação, e transfere o problema: peso em gramas, arroba em centésimos, e toda conversão vira oportunidade de erro de escala. `Decimal` já resolve com aritmética legível.

**`ROUND_HALF_EVEN`** (padrão do Python). Estatisticamente melhor, e diverge do que o usuário confere na calculadora. `0,005` tem que virar `0,01` — arredondamento comercial brasileiro.

**Devolver `0` no divisor zero.** O pior dos mundos: silencia o problema e mente. Um custo/@ de `R$ 0,00` parece um resultado excelente. `None` diz a verdade: não há dado.

**Deixar estourar `ZeroDivisionError`.** Reproduz o `#DIV/0!` da planilha em forma de erro 500. Falta de dado é estado normal de uma operação em andamento, não defeito.

## Consequências

**Boas:** valor confere com a calculadora do usuário — condição para ele confiar no sistema. `#DIV/0!` deixa de existir: linha sem dado é linha sem dado. Casas decimais e arredondamento ficam num lugar só, auditável e testável.

**Ruins:** `Decimal` é mais lento que `float` — irrelevante neste volume. Exige disciplina: um `float()` acidental no meio de uma cadeia contamina o resultado em silêncio. Todo consumidor de cálculo precisa tratar `None` — o que é a intenção, já que obriga a decidir como "sem dado" aparece na tela.

**Como sustentar:** lint proibindo `float(` em `services.py` e `models.py`, e teste de arredondamento (`0,005 → 0,01`) e de `safe_div(x, 0) → None` em cada serviço de cálculo.
