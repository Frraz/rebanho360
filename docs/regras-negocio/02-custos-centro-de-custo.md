# Custos e centro de custo

## O que existe hoje

A aba `CUSTOS` tem **235 lançamentos reais** da safra 25/26, totalizando **R$ 1.046.907,76**, com esta estrutura:

```
DATA | PAGADOR | ITEM | VALOR TOTAL | SUB CENTRO | CENTRO DE CUSTO | CLASSE | MÊS | ANO | SAFRA
```

Funciona, e cinco coisas precisam melhorar:

1. **106 lançamentos sem centro de custo**, somando R$ 411.132,64 — **39% do custo da safra**. É o maior grupo.
2. **156 lançamentos sem classe.** Só 79 estão classificados (78 CUSTEIO, 1 INVESTIMENTO).
3. **96 lançamentos sem descrição.** Há valor, data e centro, mas não se sabe o que foi comprado.
4. **Não há vínculo com lote.** Não dá para saber quanto custou criar um boi específico.
5. **`MÊS` e `ANO` são colunas digitadas**, redundantes com `DATA` e sujeitas a divergir.

> Além disso, **182 linhas têm o pagador "ONODA" preenchido e todo o resto vazio** — arrastado para baixo e nunca usado. O importador precisa reconhecê-las como linhas em branco, não como lançamentos de R$ 0,00.

## Estrutura no sistema

### `CostClass` — Classe
Semear com os dois valores reais: `CUSTEIO` e `INVESTIMENTO`.

Separa o que é gasto da safra do que é imobilizado. Na planilha há 1 lançamento de investimento (câmera de monitoramento, R$ 24.275,19) contra 78 de custeio.

### `CostCenter` — Centro de custo
Hierárquico via auto-relacionamento (`parent`). Semear com os 11 em uso:

| Centro | Lançamentos | Valor na safra |
|---|---|---|
| FUNCIONARIO | 49 | R$ 172.593,34 |
| PARQUE DE MÁQUINAS | 39 | R$ 109.794,93 |
| DESPESA GADO | 13 | R$ 20.776,50 |
| INFRAESTRUTURA | 6 | R$ 27.740,19 |
| OUTROS | 5 | R$ 5.262,00 |
| NUTRIÇÃO | 5 | R$ 136.099,99 |
| PASTAGEM | 4 | R$ 142.323,00 |
| IMPOSTO E TAXAS | 4 | R$ 6.330,77 |
| COMISSÃO | 2 | R$ 2.866,50 |
| SANIDADE | 1 | R$ 11.348,90 |
| FERPAM | 1 | R$ 639,00 |

A coluna `SUB CENTRO` existe na planilha e está **inteiramente vazia**. O modelo suporta subcentro desde já; o cadastro fica opcional, para quando a operação quiser detalhar (ex.: PARQUE DE MÁQUINAS → Combustível / Manutenção / Peças).

### `CostEntry` — Lançamento

| Campo | Obrigatório | Nota |
|---|---|---|
| `date` | sim | Data do fato |
| `season` | sim | Derivada da data, confirmável |
| `farm` | sim | **Mudança em relação à planilha** |
| `cost_center` | sim | **Mudança em relação à planilha** |
| `cost_class` | sim | CUSTEIO ou INVESTIMENTO |
| `amount` | sim | `Decimal`, > 0 |
| `description` | sim | O "ITEM" da planilha |
| `payer` | não | FK para `Partner` |
| `lot` | não | Quando preenchido, custo direto do lote |
| `source_purchase` | não | Preenchido quando o custo nasce de uma compra |
| `notes` | não | |

`MÊS` e `ANO` deixam de existir como campo — são derivados de `date`.

## Custo direto e custo indireto

```
CUSTO DIRETO                      CUSTO INDIRETO
lot preenchido                    lot vazio
────────────────                  ──────────────
Compra dos animais                Salário de funcionário
Frete da compra                   Combustível
Comissão do corretor              Herbicida de pastagem
Vacina de um lote específico      Conserto de trator
Suplemento de um lote             Contador
                                  Imposto
```

O custo direto vai inteiro para o lote. O indireto é rateado — ver [05-indicadores](05-indicadores-e-calculos.md#rateio-de-custo-indireto).

Critério padrão de rateio: **cabeça-dia**, configurável por centro de custo. O critério usado fica gravado junto do resultado, para que o número seja explicável depois.

## Obrigatoriedade de fazenda e centro de custo

Decisão que muda o comportamento em relação à planilha: **os dois passam a ser obrigatórios no lançamento.**

O motivo é o R$ 411 mil sem classificação. Custo sem centro não é analisável, e 39% é grande demais para ser tolerado — inviabiliza qualquer conclusão sobre onde o dinheiro está indo.

Na importação, esses lançamentos **não** são descartados nem empurrados para "OUTROS". Eles entram como pendência:

```
Importação CUSTOS — 417 linhas lidas

  182 linhas em branco (pagador arrastado)  → ignoradas
  235 lançamentos reais

✓ 129 prontos para importar
⚠ 106 precisam de centro de custo  (R$ 411.132,64)

Classificar em lote:
  [ ] linhas "SALÁRIO *"            → sugestão: FUNCIONARIO
  [ ] linhas "POSTO *"              → sugestão: PARQUE DE MÁQUINAS
  [ ] linhas "COMISSÃO CORRETOR"    → sugestão: COMISSÃO
  [ ] 96 sem descrição              → precisam de revisão manual
```

Classificação assistida por padrão de texto, com confirmação humana. Nada é adivinhado em silêncio.

## Relação com compra

Confirmar uma compra gera automaticamente, na mesma transação, um `CostEntry` para cada valor acessório preenchido:

```
Compra CP-2025/26-0014
  animais      R$ 260.172,15  →  CostEntry · DESPESA GADO · lot preenchido
  frete        R$   4.500,00  →  CostEntry · DESPESA GADO · lot preenchido
  comissão     R$   2.600,00  →  CostEntry · COMISSÃO     · lot preenchido
  impostos     R$     780,00  →  CostEntry · IMPOSTO E TAXAS · lot preenchido
```

Isto é o "registrar uma vez, reaproveitar em todo o sistema" na prática: o corretor foi digitado na compra e apareceu no custo do lote sem ninguém redigitar.

Os lançamentos gerados ficam com `source_purchase` preenchido e **não são editáveis diretamente** — corrigir a compra é o caminho, e os custos acompanham. Excluir a compra exclui os custos gerados por ela. Ver [06-edicao-exclusao-e-auditoria](06-edicao-exclusao-e-auditoria.md).

Lançamento de custo avulso (sem `source_purchase`) é editável e excluível normalmente.

## Análises que o modelo entrega

| Pergunta | Corte |
|---|---|
| Onde o dinheiro foi? | centro de custo × safra |
| Qual fazenda consome mais? | fazenda × safra |
| Este lote deu lucro? | lote (direto + rateado) vs. receita |
| Custeio ou investimento? | classe × safra |
| Como está contra a safra passada? | safra × safra |
| Quanto custa manter uma cabeça? | custo ÷ cabeça-dia |

## Pendências

- **#3** — A coluna `PARCERIA` está sempre `-`. Existe operação em parceria ou arrendamento? Muda o rateio de custo e de resultado.
- **#6** — `ONODA` é o pagador em todos os lançamentos. Empresa, sócio ou conta bancária? Define se vira `Company` ou `Partner`.
