# Migração das planilhas

## Fluxo de importação

Nunca direto para as tabelas finais.

```
UPLOAD → STAGING → LEITURA → VALIDAÇÃO → PRÉVIA → ERROS POR LINHA
                                                        ↓
                                    IMPORTAÇÃO ← CONFIRMAÇÃO DO USUÁRIO
```

Tudo numa transação. Falhou no meio, nada entrou.

`ImportBatch` guarda o arquivo e o `file_hash`; `ImportRow` guarda cada linha crua em JSON com seu status e seus erros. Rastreabilidade total: meses depois é possível saber de qual linha de qual planilha veio cada registro.

### Prévia

```
Importação: CUSTOS · CONTROLE PASTO 25-26.xlsx

  417 linhas lidas
− 182 em branco (pagador arrastado, sem data nem valor)
─────
  235 lançamentos reais

✓ 129 prontos
⚠ 106 precisam de centro de custo  (R$ 411.132,64)
⚠  96 sem descrição
✗   0 com erro

Linha  32  Fazenda "SÃO FRANCISCO II" não cadastrada
Linha  41  Data inválida: célula vazia
Linha 118  Valor com #DIV/0! — será importado como pendente

        [ Cancelar ]  [ Corrigir e revalidar ]  [ Importar 129 ]
```

Duas regras:

- **`#DIV/0!`, `#N/A` e célula vazia viram pendência tratável, nunca falha.** Linha incompleta é estado normal de planilha viva.
- **Linha em branco não é lançamento de R$ 0,00.** Planilha tem coluna arrastada: se não há data nem valor, a linha não existe, mesmo com outras células preenchidas.

---

## `CONTROLE PASTO … SAFRA 25-26.xlsx` — 17 abas

Fonte primária. Esta é a operação real.

| Aba | Destino | Ação |
|---|---|---|
| `PAINEL ENTRADA` | — | **Descartar.** Só seletor de navegação |
| `SÃO FRANCISCO` | `HerdMovement` | **Importar (3)** — movimentações |
| `GOIANO` | `HerdMovement` | **Importar (3)** |
| `BAIXÃO` | `HerdMovement` | **Importar (3)** |
| `MORADA DO BOI` | `HerdMovement` | **Importar (3)** |
| `SAO JOSE DO GROTAO` | `HerdMovement` | **Importar (3)** |
| `GERAL` | — | **Descartar.** Consolidação derivada — e é a que está em −140 |
| `COMPRA DE GADO` | `Purchase` | **Importar (2)** — 954 cabeças |
| `CUSTOS` | `CostEntry` | **Importar (1)** — 235 lançamentos reais |
| `VENDAS` | `Sale` | **Importar (4)** — 3 abates |
| `DASH VENDAS` | — | **Descartar.** Tabela dinâmica → vira dashboard |
| `DASH COMPRAS` | — | **Descartar.** Serve de **conferência**: 954 / R$ 2.457.752,15 |
| `DASH FINANCEIRO` | — | **Descartar.** Serve de **conferência**: R$ 1.046.907,76 |
| `DASH CAIXA` | — | **Descartar.** Substituída na Fase 4 pelo fluxo de caixa projetado |
| `ADF E COMPRAS` | — | **Referência.** Estrutura de controle de ADF, toda zerada. Ver nota |
| `PESAGENS E CONFERENCIA` | `Weighing` + `WeighingAnimal` | **Importar (5)** |
| `Planilha9` | — | **Descartar.** Resíduo |

> **Sobre `ADF E COMPRAS`:** controla ADF (autorização de compra) com status `PAGO/PENDENTE` e viagens `CONCLUIDA/PENDENTE`. Está inteiramente zerada — estrutura pronta, nunca usada. Não importar; é evidência de que a operação já sentiu falta de controlar programação e pagamento de compra, o que reforçou a Fase 4 — que agora existe. **A carga histórica não gera título** (já foi paga fora do sistema); o que ainda estiver em aberto se gera sob demanda em *Financeiro → Operações sem título* ([#18](../regras-negocio/99-pendencias.md)).

### Decisões de implementação da Fase 2 (o que a planilha real mostrou)

Estas decisões não estavam na spec original; vieram de rodar o importador contra `CONTROLE PASTO…xlsx`.

- **`SALDO ANTERIOR` é dado, não derivado.** O quadro-resumo das abas de fazenda (linhas 4-16) é "descartar" — menos a coluna `SALDO ANTERIOR` (São Francisco: 552 + 171 + 780 = 1.503). Ela vira `SALDO_INICIAL`, datado na abertura da safra. Sem ela, mortes e abates deixam o saldo negativo.
- **`COMPRA` das abas de fazenda não é importada.** A compra entra uma vez, pela aba `COMPRA DE GADO` (importe as compras **antes** das movimentações). As linhas `COMPRA` ficam como "ignoradas", com o motivo. A prévia compara os totais e avisa a diferença ([#10](../regras-negocio/99-pendencias.md)).
- **A planilha não diz de qual lote saiu cada animal.** Saídas e transferências são debitadas de um lote "saldo anterior" por fazenda, criado na importação. A prévia simula o saldo e marca como erro, com a mensagem específica, a saída que deixaria o saldo negativo.
- **Linha de custo com valor R$ 0,00 existe** (a "COMISSÃO CORRETOR" da linha 17) — o modelo exige valor > 0. Fica pendente; o usuário corrige o valor ou **ignora a linha**. Das 235 linhas reais, 234 viram lançamento; o total continua R$ 1.046.907,76.
- **Prévia real de CUSTOS:** 128 prontas, 106 sem centro (R$ 411.132,64), 1 de valor zero — e, dentro das 106, 30 com ano digitado errado ([#11](../regras-negocio/99-pendencias.md)).
- **Os −140** são 2 linhas `TRANSF. S` na aba `GOIANO`, sem `TRANSF. E` ([#2](../regras-negocio/99-pendencias.md)). Pareamento por data + categoria + quantidade, em abas diferentes; o que sobra é pendência — *ignorar* ou *definir origem e destino*.
- **Serial de data:** `45840` = **2025-07-02** (a doc dizia 07-01). Origem 1899-12-30 está certa.
- **Classe padrão:** 156 lançamentos vêm sem classe, e ela é obrigatória. A importação exige que o usuário **escolha** a classe padrão (e o lote guarda a escolha); sem escolher, essas linhas ficam pendentes. Nada é assumido em silêncio.
- **`MÉDIA/CAB`, `MÊS` e `PESO MÉDIO` não são lidos.** O `ANO` é lido só para apontar data suspeita.

### Ordem dos importadores

**1. `CUSTOS`** — 235 lançamentos reais (em 417 linhas), R$ 1.046.907,76. O mais direto e o que já entrega dashboard financeiro real.

```
DATA → date          PAGADOR → payer (pendência #6)    ITEM → description
VALOR TOTAL → amount            CENTRO DE CUSTO → cost_center
CLASSE → cost_class             SAFRA → season
SUB CENTRO → (vazia, ignorar)   MÊS, ANO → (derivar de date)
```

Tratamentos: **descartar as 182 linhas em branco** (pagador arrastado, sem data nem valor) · datas são serial Excel (`45840` = 2025-07-02), converter com origem 1899-12-30 · sem coluna de fazenda, **exige escolher a fazenda na importação** · **106 lançamentos sem centro de custo** (R$ 411.132,64, 39% do total) e **96 sem descrição** entram como pendência, com classificação assistida por padrão de texto — nunca adivinhada · **156 sem classe**, que passa a ser obrigatória.

**2. `COMPRA DE GADO`** — 13 compras, 954 cabeças, R$ 2.457.752,15.

```
DATA → date                QUANT. → head_count
NOVILHAS/BOIS → category   VALOR TOTAL → animal_value
FAZENDA → destination_farm SAFRA → season
FRETE, COMISSÃO, IMPOSTOS → freight/commission/tax (todos "-" hoje → 0)
PARCERIA → partnership (pendência #3)
MÉDIA/CAB → descartar (derivado, com #DIV/0!)
```

Tratamentos: ignorar linhas onde só há `#DIV/0!` — são fórmulas sem dado · "BEZERROS" mapeia para `Machos Desm. até 12m`, **a confirmar** · criar um lote por compra, com código sugerido · importar como `CONFIRMADA`, gerando movimento de entrada e custos.

**3. Abas de fazenda** — as movimentações.

Cada aba tem duas partes. **Linhas 4-16** são o quadro-resumo por categoria (derivado) → descartar. **Linhas 19+** são o lançamento real → importar:

```
DATA | MÊS | CATEGORIA | TIPO | QUANTIDADE | SAIDA | DESTINO | PESO TOTAL | PESO MÉDIO
```

Tratamentos: `TIPO` mapeia para `MovementType` (`COMPRA`, `MORTE`, `ABATE`, `VENDA`, `TRANSF. E`, `TRANSF. S`, `NASC.`, `EVOLUÇ`) · **`TRANSF. S` e `TRANSF. E` precisam ser pareadas em movimento único de 2 linhas** — é aqui que o `-140` aparece e vira pendência explícita de conciliação · `MÊS` e `PESO MÉDIO` são derivados, descartar · `DESTINO` com texto livre ("COPERFRIGU", "CANTINA", "COMPRA GOIANO") vira `Partner` ou `Farm`, com confirmação.

> **O ponto crítico.** Na importação, as transferências das 5 abas são conciliadas: cada `TRANSF. S` procura sua `TRANSF. E` correspondente por data, categoria e quantidade. As que não parearem aparecem na tela como pendência, com a decisão nas mãos do usuário — não se inventa a contrapartida. Ver pendência #2.

**4. `VENDAS`** — 3 abates, 354 cabeças.

```
DATA → date              TIPO DE VENDA → type       CATEGORIA → category
ANIMAIS → head_count     PESO TOTAL → total_weight_kg
CARCAÇA TOTAL → carcass_weight_kg    VALOR TOTAL → total_value
COMPRADOR → buyer        FORMA → sale_form          FAZENDA → farm
descartar: PESO MÉDIO, CARCAÇA MÉDIA, RENDIMENTO %, VALOR CABEÇA,
           VALOR POR @, MÊS, ANO, SOMA RENDIMENTO   (todos derivados)
```

Após importar, `CarcassService` recalcula os derivados e **compara com o que estava na planilha**. Divergência vira aviso, não erro — foi assim que a pendência #7 apareceu.

**O que a planilha real mostrou (Fase 3).** A aba `SÃO FRANCISCO` **já registra os 3 abates** (84 + 189 + 81 = 354, `Machos 25 a 36 meses`, datas iguais ou a 1 dia), e a importação de movimentações os traz como saída no rebanho. Importar `VENDAS` por cima debitaria as 354 cabeças **duas vezes**. Por isso, antes de criar uma saída nova, o importador procura a que já existe — mesma categoria e quantidade, data a até 3 dias — e **propõe vincular**: a venda passa a ser o documento de origem do movimento, sem debitar de novo. É sugestão em grupo ("Sugestões do sistema"): só vale depois de o usuário marcar a caixa. Sem candidata, ou se o usuário escolher "criar uma saída nova", pede fazenda e lote. Importe as vendas **depois** das movimentações.

Outros tratamentos: `MACHOS 25 - 36` mapeia para a categoria `Machos 25 a 36 meses` (nas opções); o comprador `COPERFRIGU` — que a importação de movimentações cria **sem papel** — recebe o papel Frigorífico ou Comprador **por escolha do usuário**; `FAZENDA` (`SÃO FRANCISCO II`) fica só na observação quando a venda é vinculada (pendência #5); os pesos da venda × do movimento × das pesagens divergem e viram aviso (pendência #12); o `SOMA RENDIMENTO` (43,12) aparece no relatório de divergência e **não é importado** (pendência #7).

**5. `PESAGENS E CONFERENCIA`** — o desempilhamento.

Oito blocos paralelos de colunas, cada um `(DATA, BRINCO, PESO, MOVIMENTAÇÃO)`:

```
B,C,D,E │ G,H,I,J │ L,M,N,O │ Q,R,S,T │ V,W,X,Y │ AA,AB,AC,AD │ AF,AG,AH,AI │ AK,AL,AM,AN
```

O importador lê os oito e empilha em uma tabela só. Agrupa por `(data, motivo)` criando uma `Weighing`, e cada linha vira `WeighingAnimal(ear_tag, weight_kg)`. Motivos: `CONFERENCIA`, `ABATE`, `COMPRA`, `VACINA COFERENCIA` *(grafado assim na planilha)*, `COMPRA GOIANO`.

Sem entidade `Animal` — [ADR 0004](../arquitetura/adr/0004-lote-agregado-antes-de-brinco.md).

**O que a planilha real mostrou (Fase 3):**

- **São 9 blocos, não 8** (o nono, `AP-AS`, tem 268 pesagens de 27/04/2026 sem motivo). O leitor acha os blocos **pelo cabeçalho** `(DATA, BRINCO, PESO, MOVIMENTAÇÃO)`, não por letras fixas. 4.058 animais pesados em 9 grupos `(data, motivo)`.
- **`SB` é "sem brinco"**, não um brinco repetido: 18 animais, mais 591 nos 3 blocos que não têm coluna de brinco. Entram com o brinco em branco.
- **20 brincos se repetem com pesos diferentes no mesmo dia** (o 1759 aparece 3 vezes em 16/12/2025) — não é o mesmo animal pesado duas vezes. Todos são importados; vira aviso. "Nenhum brinco se perdeu" é o critério.
- **A planilha não diz de qual lote é cada pesagem.** Lote e motivo de cada grupo são decisão do usuário, nas opções, com sugestão preenchida (a venda ou a compra que casa com a data e o tamanho do grupo) — **que só vale depois de salvar**. Sem decidir, não importa.
- `VACINA COFERENCIA` (sic) é sugerida como `VACINA`; `COMPRA GOIANO` como `COMPRA`; o bloco sem motivo, como `COMPRA` quando há compra no mesmo dia.
- Os pesos de `ABATE` de 03/08/2025 (84 animais) somam **exatamente os 43.540 kg** da venda; os de 23/04/2026 somam 47.878 kg, não os 45.000 de `VENDAS` — pendência #12.

---

## `REPORTAGEM IVAN.xlsx` — 44 abas

**Não importar nada.** É análise de consultoria de outra fazenda (Katuete), não a operação do produtor.

Valor do arquivo: mostrar **onde os indicadores podem chegar** quando houver dado.

| Aba | Serve para |
|---|---|
| `RESUMO DESEMPENHO LOTE` | Especificação de desempenho por lote: GMD, carcaça, @ produzida, eficiência biológica, dias para 1 @ |
| `RESUMO DESEMPENHO FINACEIRO` | Estrutura de resultado financeiro por lote |
| `INVENTARIO` | Inventário valorizado com efeito de mercado (R$/@ início × fim de safra) |
| `TABELA DE ÁREAS` | Tipos de área: benfeitoria, silagem, pastagem, reserva/APP, arrendamento → `Paddock.type`. Não há histórico mensal de área |
| `RESUMO DE INFRAESTRTURA` | **Infraestrutura de verdade**: curral, m², cocho (m), bebedouro e parâmetros por animal. Sem modelo — Fase 6 |
| `CURVA DE CONSUMO`, `CONFINAMENTO` | Fase 6, se houver confinamento |
| `DADOS REPRODUTIVOS`, `NASCIMENTOS` | Fase 6, se houver cria |
| `EQUIPE` | Função, quantidade e salário por frente de trabalho. **Sem equivalente** no CONTROLE PASTO e sem modelo (só o centro de custo `FUNCIONARIO`) — Fase 6 |
| `MORTES`, `Planilha4` | Mortalidade jovem × adulto por mês e **causa da morte** (onça, picada de cobra, acidente…). O sistema guarda só `reason` em texto livre |
| `ESTOQUE` | Saldo inicial/final, variação, desfrute. O sistema tem a posição por categoria, sem UA, @ e R$ |
| `PARQUE DE MÁQUINAS` (4 abas) | Custo/hora de máquina — fora do escopo atual |
| `RESUMO DESEMPENHO *`, `PLACAR`, `ANÁLISE PECUÁRIA`, `PERFIL FINANCEIRO PECUÁRIA` | **Os indicadores-alvo**: GMD, @ produzida, rendimento do ganho, dias para 1 @, mortalidade, custeio e desembolso por @ e por cabeça/mês. Parte já calculada por lote; a visão da fazenda inteira falta |
| `TIR`, `PERFIL ABC PECUÁRIA`, `INVENTARIO` | Análise gerencial (TIR, curva ABC, inventário valorizado com efeito de mercado) — Fase 6, com duas safras de dado |
| `ANÁLISE AGRICULTURA/GLOBAL/CONTÁBIL`, `CLASSIFICAÇÃO FAZENDA`, `TABELA PARA CONSOLIDAÇÃO` | Fora do escopo (agricultura, contabilidade, benchmark) |
| `CHUVAS` | Precipitação mensal por safra. Sem modelo |

Fórmulas transcritas em [regras-negocio/05](../regras-negocio/05-indicadores-e-calculos.md#indicadores-avançados-fase-6).

---

## Relatórios legados (5 PNGs)

Sistema SisAtak do frigorífico Boi Brasil. Conceitos e números do ciclo de compra (Fase 5).

Analisados em [relatorios/01-catalogo.md](../relatorios/01-catalogo.md).

---

## Conferência pós-importação

A importação só é aceita se estes números baterem:

| Verificação | Esperado |
|---|---|
| Lançamentos de custo importados | 235 (nunca 417) |
| Total de custos da safra | R$ 1.046.907,76 |
| Soma dos 11 centros + sem centro | R$ 1.046.907,76 |
| Lançamentos sem centro de custo | 106 · R$ 411.132,64 |
| Compras | 13 · 954 cabeças · R$ 2.457.752,15 |
| Vendas/abates | 3 · 354 cabeças · R$ 2.298.586,23 |
| Cabeças abatidas (movimentos) | 354 — **não 708**: as vendas adotam a saída que a aba da fazenda já registrou |
| Animais pesados | 4.058 — nenhum brinco perdido |
| Saldo São Francisco | 1.954 |
| Categorias animais | 11 |
| Transferências não pareadas | listadas como pendência, **nunca importadas em silêncio** |

Todos conferidos contra a planilha em 30/09/2026. Dois números dependem de decisão do produtor e **divergem de propósito** até lá: o saldo de São Francisco (2.080 contra 1.954 — [#10](../regras-negocio/99-pendencias.md)) e as transferências não pareadas (2 — [#2](../regras-negocio/99-pendencias.md)).

Comando `python manage.py conferir_importacao` roda e imprime a tabela comparativa (16 verificações); sai com erro se qualquer número divergir. Ordem da carga: custos → compras → movimentações → **vendas** → **pesagens**.
