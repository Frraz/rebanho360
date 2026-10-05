# Rebanho: movimentações e saldo

> Esta é a regra central do sistema. Se só um documento for lido, que seja este.

## O princípio

**O saldo do rebanho nunca é um campo. É sempre a soma dos eventos.**

```
saldo(fazenda, categoria, lote, data) = SUM(linhas do razão até a data)
```

Ninguém edita "Machos 25-36 = 423". A pessoa registra um abate de 354 cabeças, e o saldo passa a ser 423 porque era 780 e saíram 357 (354 abates + 3 mortes).

## Por que assim

A planilha atual mostra exatamente o que acontece sem essa disciplina. Na aba `GERAL`:

```
Machos Desm. até 12m    TRANSF. S = 140    TRANSF. E = 0    →    FINAL = -140
```

Cento e quarenta cabeças saíram de algum lugar e não chegaram a lugar nenhum. O consolidado do grupo fica negativo. Ninguém percebeu porque a aba está oculta.

Isso não é descuido de quem preenche — é consequência de o saldo ser um campo somável em vez de um saldo derivado. Com o modelo abaixo, esse estado **não pode existir**.

## O modelo: duas tabelas

### `HerdMovement` — o documento do evento

O que o usuário preenche e enxerga. Um movimento.

| Campo | Observação |
|---|---|
| `codigo` | `MV-2025/26-004871`, gerado pelo sistema |
| `data` | Data do fato, não do lançamento |
| `tipo` | Ver tabela de tipos abaixo |
| `safra` | Derivada da data, confirmável pelo usuário |
| `quantidade` | Cabeças, inteiro positivo |
| `peso_total_kg` | Opcional; `Decimal` |
| `fazenda_origem`, `lote_origem`, `categoria_origem` | Preenchidos conforme o tipo |
| `fazenda_destino`, `lote_destino`, `categoria_destino` | Preenchidos conforme o tipo |
| `parceiro` | Fornecedor, comprador, frigorífico — conforme o tipo |
| `documento_origem` | FK opcional para Compra ou Venda que o gerou |
| `motivo`, `observacao` | Texto livre; `motivo` obrigatório em MORTE e AJUSTE |
| `criado_por`, `criado_em` | Auditoria |
| `status` | `ATIVO` ou `EXCLUIDO` (exclusão lógica) |

### `HerdLedgerEntry` — as linhas do razão

O que o sistema gera. Nunca editável diretamente.

| Campo | Observação |
|---|---|
| `movimento` | FK, `on_delete=PROTECT` |
| `data` | Copiada do movimento (índice para saldo por data) |
| `fazenda`, `lote`, `categoria` | A posição afetada |
| `quantidade` | **Com sinal**: positivo entra, negativo sai |
| `peso_kg` | Com o mesmo sinal |
| `safra` | Copiada, para agregação direta |

## Partidas dobradas

O tipo do movimento determina quantas linhas ele gera.

### Movimento simples → 1 linha

Entra ou sai do universo controlado.

```
COMPRA de 133 bezerros para São Francisco
  └─ +133  São Francisco · lote LT-SFR-004 · Machos Desm. até 12m
```

### Movimento de deslocamento → 2 linhas

Não cria nem destrói cabeça alguma; apenas muda a posição. **As duas linhas nascem na mesma transação.**

```
TRANSFERÊNCIA de 140 cabeças de São Francisco para Baixão
  ├─ -140  São Francisco · Machos Desm. até 12m
  └─ +140  Baixão        · Machos Desm. até 12m
                          soma = 0
```

```
EVOLUÇÃO de 60 cabeças que completaram 12 meses
  ├─ -60  São Francisco · Machos Desm. até 12m
  └─ +60  São Francisco · Machos 13 a 24 meses
                          soma = 0
```

A consequência é direta: **a soma de todas as linhas do razão do grupo só muda por entrada ou saída real**. Transferência e evolução somam zero por construção. O `-140` da planilha deixa de ser representável.

## Tipos de movimento

Extraídos do dropdown real das abas de fazenda (`$S$1:$S$9`), mais três que o sistema acrescenta.

| Tipo | Linhas | Sinal | Origem do dado |
|---|---|---|---|
| `SALDO_INICIAL` | 1 | + | Abertura da safra ou implantação |
| `COMPRA` | 1 | + | Gerado por uma Compra |
| `NASCIMENTO` | 1 | + | Lançamento manual |
| `TRANSFERENCIA` | **2** | −/+ | Entre fazendas ou entre lotes |
| `EVOLUCAO` | **2** | −/+ | Mudança de categoria por idade |
| `RECLASSIFICACAO` | **2** | −/+ | Correção de categoria lançada errada |
| `ABATE` | 1 | − | Gerado por uma Venda do tipo abate |
| `VENDA` | 1 | − | Gerado por uma Venda |
| `MORTE` | 1 | − | Lançamento manual, **motivo obrigatório** |
| `CONSUMO_DOACAO` | 1 | − | Consumo interno ou doação |
| `AJUSTE_INVENTARIO` | 1 | ± | **Permissão restrita**, motivo obrigatório |

Sobre `TRANSFERENCIA` e `EVOLUCAO`: na planilha eles aparecem como colunas separadas de entrada (`TRANSF. E`) e saída (`TRANSF. S`). No sistema são **um único movimento com duas linhas** — é justamente isso que impede a entrada e a saída de se descolarem.

## Categorias animais

Parametrizáveis. Semeadas com as 11 reais da planilha (`$A$5:$A$15`), nesta ordem de apresentação:

| # | Categoria | Sexo | Ordem etária |
|---|---|---|---|
| 1 | Fêmeas + 36 meses | F | 5 |
| 2 | Fêmeas 25 a 36 meses | F | 4 |
| 3 | Fêmeas 13 a 24 meses | F | 3 |
| 4 | Fêmeas Desm. até 12m | F | 2 |
| 5 | Bezerras Mamando | F | 1 |
| 6 | Bezerros Mamando | M | 1 |
| 7 | Machos Desm. até 12m | M | 2 |
| 8 | Machos 13 a 24 meses | M | 3 |
| 9 | Machos 25 a 36 meses | M | 4 |
| 10 | Touros | M | 5 |
| 11 | Tropa | — | — |

O campo `ordem_etaria` existe para o sistema poder **sugerir** a evolução (categoria seguinte de mesmo sexo). A sugestão nunca é automática: evolução é um lançamento consciente, com data escolhida por quem entende do rebanho.

## Saldo

### Como calcular

```python
# apps/herd/services.py
def saldo(*, fazenda=None, lote=None, categoria=None, safra=None, ate=None):
    qs = HerdLedgerEntry.objects.all()
    if fazenda:   qs = qs.filter(fazenda=fazenda)
    if lote:      qs = qs.filter(lote=lote)
    if categoria: qs = qs.filter(categoria=categoria)
    if safra:     qs = qs.filter(safra=safra)
    if ate:       qs = qs.filter(data__lte=ate)
    return qs.aggregate(
        cabecas=Coalesce(Sum("quantidade"), 0),
        peso_kg=Coalesce(Sum("peso_kg"), Decimal("0")),
    )
```

Índice composto em `(fazenda, categoria, data)` e em `(lote, data)`.

### Fechamento mensal

`HerdMonthlySnapshot` guarda o saldo por `(fazenda, categoria, lote, mês)` — **apenas como cache de desempenho**. Nunca é fonte da verdade: é sempre recalculável a partir do razão, e existe um comando `recalcular_snapshots` que o reconstrói do zero. Se snapshot e razão divergirem, o razão está certo.

Com o volume atual (menos de 10 mil movimentos por safra), o snapshot ainda não é necessário. Entra quando o saldo histórico ficar lento.

## Invariantes

Garantidas por `CheckConstraint` no banco, não só por validação em Python:

1. `quantidade > 0` em `HerdMovement`
2. `quantidade != 0` em `HerdLedgerEntry`
3. Tipo de 2 linhas exige origem **e** destino preenchidos, e eles devem diferir em pelo menos um campo
4. Tipo de 1 linha exige origem **ou** destino, nunca ambos
5. `peso_kg >= 0` em valor absoluto
6. Soma das linhas de um movimento de deslocamento = 0

Validadas por serviço e por teste:

7. **Saldo não pode ficar negativo** em nenhuma posição `(fazenda, lote, categoria)`. Uma saída maior que o saldo é bloqueada com mensagem clara: *"Saldo insuficiente: há 12 cabeças de Machos 13 a 24 meses no Baixão, foram informadas 20."*
8. Movimento com data futura é bloqueado.
9. Movimento em safra encerrada exige permissão específica.

> A invariante 7 é a que impede o `-140`. Ela tem que ser verificada **dentro** da transação, com `select_for_update` na posição afetada, ou dois lançamentos simultâneos passam pela validação e produzem saldo negativo.

## Correção de erro: editar ou excluir

Movimento lançado **pode ser editado e pode ser excluído**, com motivo obrigatório e registro completo em auditoria. Regra geral em [06-edicao-exclusao-e-auditoria](06-edicao-exclusao-e-auditoria.md).

O que muda aqui é **como** o razão absorve isso.

### O razão é append-only

Editar ou excluir um movimento **não apaga linha do razão**. Escreve linhas de compensação — e elas levam **a data do fato original**, não a data da correção:

```
20/09  registrado    entry #801   data 18/09   +126   movimento original
14/10  corrigido     entry #1150  data 18/09   −126   reverte #801
                     entry #1151  data 18/09   +120   valor correto
```

Por que a data do fato: se a contagem errada foi digitada em setembro, o saldo de setembro **nunca foi** 126 — foi 120. A correção precisa valer para trás.

Isso exige dois tempos distintos em `HerdLedgerEntry`:

| Campo | Significado | Usado para |
|---|---|---|
| `date` | Quando o fato aconteceu | **Cálculo de saldo** |
| `created_at` | Quando foi registrado | **Auditoria** |
| `reverses_entry` | FK para a linha compensada | Rastreio |

Saldo consulta `date`. Auditoria consulta `created_at`. As duas perguntas têm resposta:

- *"Quantas cabeças havia em 30/09?"* → 120. Sempre foi.
- *"O que o sistema mostrava em 30/09?"* → 126, até a correção de 14/10 feita pela Maria.

### Invariante continua valendo

Editar ou excluir **não pode deixar saldo negativo em nenhuma posição, em nenhuma data**. A verificação roda dentro da transação, com a posição travada.

Excluir uma entrada cujos animais já saíram é bloqueado, com explicação do que desfazer primeiro. Ver [análise de impacto](06-edicao-exclusao-e-auditoria.md#análise-de-impacto).

### Movimento gerado por outro documento

Movimento criado por uma compra ou venda não se edita direto — edita-se a compra ou a venda, e o movimento acompanha. A tela mostra a origem e leva até ela.

## Relação com lote

Todo movimento aponta para um lote, sempre. Lote é a unidade de custeio e de análise de desempenho.

- Uma compra cria um lote novo, ou entra em lote existente (escolha do usuário)
- Transferência entre fazendas pode manter o lote ou criar outro — decisão de quem lança
- Um lote vive em uma fazenda por vez
- Lote com saldo zero é encerrado automaticamente, com `data_saida` preenchida

O lote é o que liga o rebanho ao custo: é por ele que `CostAllocationService` chega a custo por cabeça e custo por arroba.

## Pesagem

Evento separado, que **não** altera saldo — só peso.

`Pesagem`: data, fazenda, lote, motivo (`CONFERENCIA`, `COMPRA`, `ABATE`, `VACINA`, `VENDA`), cabeças pesadas, peso total, peso médio *(calculado)*.

`PesagemAnimal`: linhas opcionais `(brinco, peso_kg)`. Guardam os dados individuais da aba `PESAGENS E CONFERENCIA` sem que exista ainda uma entidade `Animal` — ver [ADR 0004](../arquitetura/adr/0004-lote-agregado-antes-de-brinco.md).

`WeightGainService` usa pesagens sucessivas do mesmo lote para calcular GMD e @ produzida.

**Corrigir e excluir pesagem.** Como todo registro confirmado ([06](06-edicao-exclusao-e-auditoria.md)), a pesagem tem detalhe, **editar** (data, motivo, cabeças e peso, com o motivo da correção), **excluir** (lógico, com motivo) e **restaurar**. Valem as regras do lançamento: data futura é recusada e é preciso permissão de escrita na fazenda; fazenda e lote não mudam (lote errado = excluir e lançar de novo). Pesagem excluída sai do cálculo do GMD. Editar a data é o que desfaz o caso de duas pesagens no mesmo dia (GMD em "—"). Editar e excluir: `ESCRITORIO`, `GESTOR` e `ADMIN`; excluir e restaurar: `GESTOR` e `ADMIN`.

## Pendências

Duas perguntas em aberto sobre este documento, registradas em [99-pendencias](99-pendencias.md):

- **#1** — A EVOLUÇÃO é mesmo reclassificação por idade? Implementado como movimento de 2 linhas, que é reversível se a resposta for outra.
- **#2** — O `-140` da aba `GERAL` é erro de planilha ou transferência para fora do grupo de fazendas? Se for a segunda, o destino precisa virar cadastro.
