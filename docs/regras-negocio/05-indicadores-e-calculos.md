# Indicadores e cálculos

## As três naturezas de um número

Distinção que precisa estar clara em todo o sistema:

| Natureza | Exemplo | Onde vive |
|---|---|---|
| **Dado informado** | peso total recebido = 27.668 kg | Campo no banco, digitado ou importado |
| **Dado derivado** | peso médio = 27.668 ÷ 133 = 208,03 kg | Calculado na hora, nunca gravado |
| **Regra de negócio** | custo/@ = custo total ÷ arrobas produzidas | Serviço testado |

A planilha mistura as três: peso médio está gravado como valor em algumas linhas e como fórmula em outras, e na aba `VENDAS` os dois discordam. No sistema, derivado é **sempre** calculado.

## Regra de ouro do divisor zero

```python
def safe_div(numerador, denominador):
    """Divisão que devolve None em vez de explodir ou mentir."""
    if not denominador:
        return None
    return numerador / denominador
```

`None` chega à tela como **"—"** ou **"pendente"**, nunca como `0` e nunca como erro.

É isto que elimina os `#DIV/0!` que hoje tomam centenas de linhas das abas `COMPRA DE GADO`, `VENDAS` e `ADF E COMPRAS`. Linha sem dado é linha sem dado, não é linha com defeito.

## Decimal e arredondamento

```python
# apps/core/money.py
KG_PER_ARROBA = Decimal("15")
ROUNDING      = ROUND_HALF_UP   # arredondamento comercial brasileiro

MONEY_PLACES  = Decimal("0.01")     # R$    2 casas
WEIGHT_PLACES = Decimal("0.001")    # kg    3 casas
ARROBA_PLACES = Decimal("0.01")     # @     2 casas
PERCENT_PLACES= Decimal("0.0001")   # %     4 casas internas, 2 na tela
```

**Arredondar só na gravação final e na apresentação.** Nunca no meio de uma cadeia de cálculo — arredondar a cada passo acumula erro que aparece no fechamento da safra.

`float` é proibido para valor e peso. Ver [ADR 0005](../arquitetura/adr/0005-decimal-e-arredondamento.md).

## Conversões

```
arrobas = kg ÷ 15
```

Convenção da pecuária brasileira: a arroba é de **carcaça**, não de peso vivo. Portanto:

- `@ de carcaça` = peso de carcaça ÷ 15 → é esta que vale no preço
- `@ de peso vivo` = peso vivo ÷ 15 → serve só para conferência

Onde o documento disser "@" sem qualificar, é **arroba de carcaça**.

## Rebanho

### Saldo
```
saldo(posição, data) = SUM(HerdLedgerEntry.quantidade) até a data
```
Ver [01-rebanho-movimentacoes](01-rebanho-movimentacoes.md).

### GMD — ganho médio diário
```
GMD (kg/dia) = (peso_final − peso_inicial) ÷ dias
```
De duas pesagens do mesmo lote. Sem pesagem inicial, GMD é `None` — não se estima peso de entrada.

### Arrobas produzidas
```
@ produzida = (peso_carcaça_saída − peso_carcaça_entrada) ÷ 15
```
Com rendimento de entrada estimado quando não houver carcaça medida na entrada — e a estimativa fica **marcada como tal** na tela.

### Taxa de mortalidade
```
mortalidade % = cabeças MORTE no período ÷ saldo médio do período × 100
```

## Carcaça e abate

Conferido contra a aba `VENDAS`, linha do abate de agosto/2025:

```
84 cabeças · 43.540 kg vivo · 22.350,40 kg carcaça · R$ 401.502,68

peso médio vivo    = 43.540 ÷ 84            = 518,33 kg      ✓
carcaça média      = 22.350,40 ÷ 84         = 266,08 kg      ✓
rendimento         = 22.350,40 ÷ 43.540     = 51,33 %        ✓
@ de carcaça       = 22.350,40 ÷ 15         = 1.490,03 @
valor por cabeça   = 401.502,68 ÷ 84        = 4.779,79       ✓
valor por @        = 401.502,68 ÷ 1.490,03  = 269,46         ✓
```

Os seis batem com a planilha. São a especificação do `CarcassService`.

## Custo

### Custo de aquisição
```
custo_aquisicao = valor_animais + frete + comissão + impostos
```
Na compra de 105 bezerros de dezembro: R$ 260.172,15 de animais, demais campos vazios → custo = R$ 260.172,15, média de R$ 2.477,83/cabeça. Confere.

### Custo por cabeça, kg e arroba
```
custo/cabeça = custo_total ÷ cabeças
custo/kg     = custo_total ÷ kg produzidos
custo/@      = custo_total ÷ @ produzidas
```

Onde `custo_total` = custo de aquisição do lote + custos apropriados + custos rateados.

### Rateio de custo indireto

O problema real: dos 235 lançamentos da aba `CUSTOS`, nenhum aponta para um lote. "SALÁRIO ALDEMAR" ou "HERBICIDA" são da fazenda inteira.

Critério padrão: **cabeça-dia**.

```
peso_lote = Σ(cabeças do lote × dias no período)
cota_lote = custo_indireto × peso_lote ÷ Σ(peso de todos os lotes da fazenda)
```

Um lote que passou o mês inteiro com 100 cabeças absorve o dobro de um que passou meio mês com as mesmas 100.

Alternativas previstas, selecionáveis por centro de custo: `POR_CABECA_DIA` (padrão), `POR_ARROBA_PRODUZIDA`, `POR_CABECA_SIMPLES`, `MANUAL`. O critério aplicado fica **gravado no resultado**, para que o número seja explicável meses depois.

### Custo por centro de custo

Da aba `DASH FINANCEIRO`, safra 25/26 — serve de caso de teste da importação:

| Centro de custo | Valor |
|---|---|
| (sem centro) | R$ 411.132,64 |
| FUNCIONARIO | R$ 172.593,34 |
| PASTAGEM | R$ 142.323,00 |
| NUTRIÇÃO | R$ 136.099,99 |
| PARQUE DE MÁQUINAS | R$ 109.794,93 |
| INFRAESTRUTURA | R$ 27.740,19 |
| DESPESA GADO | R$ 20.776,50 |
| SANIDADE | R$ 11.348,90 |
| IMPOSTO E TAXAS | R$ 6.330,77 |
| OUTROS | R$ 5.262,00 |
| COMISSÃO | R$ 2.866,50 |
| FERPAM | R$ 639,00 |
| **Total** | **R$ 1.046.907,76** |

> R$ 411.132,64 — 39% do custo da safra — estão **sem centro de custo**. É o maior grupo. No sistema, centro de custo é obrigatório no lançamento; na importação, esses viram pendência a classificar, não são descartados nem jogados em "OUTROS".

## Resultado

### Resultado do lote
```
resultado = receita_venda − custo_aquisicao − custos_apropriados − custos_rateados
```

### Margem por arroba
```
margem/@ = (valor recebido por @) − (custo por @)
```

O indicador que responde à pergunta central do negócio: *o boi pagou o que custou criar?*

## Indicadores avançados (Fase 6)

Da REPORTAGEM IVAN, para quando houver dado de confinamento e reprodução:

| Indicador | Fórmula |
|---|---|
| Rendimento do ganho | ganho de carcaça ÷ ganho de peso vivo |
| GMD de carcaça/dia | ganho de carcaça ÷ dias |
| Eficiência biológica | kg de matéria seca consumida ÷ @ produzida |
| Consumo % do PV | consumo de MS ÷ peso vivo médio |
| Dias para 1 @ | 15 ÷ (GMD de carcaça) |
| Lotação | UA ÷ hectare |

Documentados aqui para não se perderem. Não construir antes de existir o dado que os alimenta.

## Decisões de implementação da Fase 3

Onde a fórmula acima era ambígua ou faltava dado. Todas isoladas em um módulo, para ajustar sem tocar no resto (#14 e #15 em [99-pendencias](99-pendencias.md)):

| Indicador | Serviço | Decisão |
|---|---|---|
| Os 6 do abate | `apps/sales/carcass.py` | Rendimento devolvido em **%** (51,33), não fração. Agregar vendas só considera as que **têm carcaça** no rendimento e no valor/@ — somar o peso vivo de todas e dividir pela carcaça de algumas mentiria. |
| Resultado e margem/@ | `apps/sales/result.py` | `custo/@` = custo do lote ÷ @ de carcaça **vendida** (não "produzida"): assim `resultado = margem/@ × @ vendidas` fecha exato. Lote com animais mostra resultado **parcial**, com o custo rateado pela fração `vendidas ÷ (vendidas + saldo)`; com saldo zero a fração é 1. Sem custo de aquisição → sem resultado, com o motivo. Nada é gravado: "congelar" é o período terminar na `exit_date`. |
| GMD | `apps/herd/weight_gain.py` | Do primeiro ao último ponto de peso do lote; sem **duas pesagens em datas diferentes** é `None` com o motivo. Sem pesagem de entrada o GMD existe mas diz que cobre só o período pesado. O peso de entrada **nunca é estimado**; o peso informado na compra serve de entrada só se **todas** as compras do lote têm peso. O **peso inicial** do relatório "Desempenho do lote" é esse peso de entrada e aparece mesmo antes de haver GMD (uma compra com peso e nenhuma pesagem em outro dia mostra o peso inicial e o GMD em "—", com o motivo). Também há o GMD de cada trecho. |
| @ produzida | idem | `(carcaça de saída − carcaça de entrada) ÷ 15`, sobre os animais abatidos. A carcaça de entrada = `peso médio de entrada × cabeças × rendimento de entrada`. **Sem rendimento informado, `None`**; com ele, marcada como **estimativa**. |
| Mortalidade | `apps/herd/mortality.py` | Mortes ÷ **saldo médio diário** (cabeça-dia ÷ dias) × 100. Sem animal no período, `None` — não "0%". |
| Custo/@ do painel | `apps/dashboards/selectors.py` | O dos lotes **encerrados na safra** (mesmo serviço do resultado). "Custos" do painel exclui o que a compra gera, que já está em "Comprado". |

`safe_div` agora devolve **sempre `Decimal`**: com dois inteiros, Python devolve `float`, o que a regra nº 2 proíbe.

## Testes obrigatórios

Nenhum cálculo entra sem teste. No mínimo:

1. Os seis números do abate de agosto/2025 acima
2. `safe_div` com denominador zero → `None`, em todos os serviços
3. Arredondamento: `ROUND_HALF_UP` em `0,005` → `0,01`
4. Soma de linhas de transferência = 0
5. Saldo após sequência de movimentos conhecida
6. Rateio: soma das cotas = custo original, sem centavo perdido
7. Total dos 11 centros de custo = R$ 1.046.907,76
