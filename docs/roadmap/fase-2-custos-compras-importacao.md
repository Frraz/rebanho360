# Fase 2 — Custos, compras e importação

**~57-77h · 15 tarefas · a fase que aposenta a planilha**

Ao fim dela, tudo que a `CONTROLE PASTO` faz, o sistema faz — com saldo que fecha, sem `#DIV/0!`, com várias pessoas ao mesmo tempo e com histórico de quem fez o quê.

## Status (atualizado 2026-10-01)

**F2-01 a F2-14 concluídas; F2-15 não executada** (sem VPS, mesmo bloqueio da F0-17/F0-18/F1-16). **364 testes passando** contra Postgres real (eram 152), `ruff`/`black` limpos, 19 telas verificadas em **360 px e 1280 px** com navegador real (nenhuma com rolagem horizontal). Os importadores foram testados **contra a planilha real** do produtor, não contra fixture inventada.

**O que o importador achou na planilha real** (detalhes em [99-pendencias](../regras-negocio/99-pendencias.md) e [migracao/01](../migracao/01-planilhas-e-importacao.md#decisões-de-implementação-da-fase-2-o-que-a-planilha-real-mostrou)):

1. Os **−140** são duas linhas `TRANSF. S` na aba `GOIANO` (95 + 45), sem entrada em lugar nenhum — [#2](../regras-negocio/99-pendencias.md), agora com os fatos na mão.
2. O **`SALDO ANTERIOR`** (1.503 em São Francisco) está no quadro-resumo que a spec mandava descartar — é dado de entrada; sem ele o saldo fica negativo.
3. As linhas **`COMPRA` das abas duplicam** a aba `COMPRA DE GADO` (828 × 954 cabeças); a diferença é a compra de 126 cabeças de 27/04/2026 — [#10](../regras-negocio/99-pendencias.md). O saldo de São Francisco fecha em **2.080**, não 1.954.
4. **30 custos com ano digitado errado** (`03/01/2025` com `ANO = 2026`) — [#11](../regras-negocio/99-pendencias.md).
5. **Uma linha de custo com R$ 0,00** (234 lançamentos + 1 ignorada = 235; o total R$ 1.046.907,76 bate).
6. A doc errava o exemplo de data serial (`45840` = **02/07**, não 01/07) — corrigida.

**Decisões de modelagem:**

- `CostEntry`, `Purchase` e as FKs adiadas da Fase 1 (`Lot.origin_purchase`, `HerdMovement.origin_purchase`) criados. Lote ganhou o status `EXCLUIDO` (exclusão lógica junto com a compra que o criou).
- **Compra é um `ReversibleModel` cujos efeitos são outros registros** (lote, movimento, custos): editar = desfazer + reaplicar na mesma transação; excluir/restaurar idem, com `cascade_root` compartilhado — a cascata inteira lê-se como **um** ato na auditoria. `reversible.excluir` agora expõe a raiz ao registro.
- Análise de impacto genérica em `apps/core/impact.py` + `ExclusaoComImpactoView` (usada por compras e custos): efeitos, dependentes (cascata explícita) e bloqueios, **antes** de executar.
- `CostAllocationService` (`apps/costs/allocation.py`): rateio pelo **método do maior resto** — a soma das cotas é exatamente o custo, testado como propriedade em 300 casos aleatórios. Critérios `POR_ARROBA_PRODUZIDA` (Fase 3) e `MANUAL` existem; o primeiro recusa com mensagem explicando a dependência. Custo sem animal para ratear vira `sem_base`, nunca some.
- "Média por cabeça" = só os animais ÷ cabeças (a `MÉDIA/CAB` da planilha); o custo de aquisição por cabeça é outro número, mostrado ao lado.
- Importação: `ImportBatch`/`ImportRow` com linha crua, decisão do usuário (`resolution`) e dado derivado (`meta`) em campos separados — **o sistema nunca preenche decisão sozinho**. Sugestão só vale depois que o usuário marca o grupo. Falha no meio desfaz tudo; o lote continua em prévia com a linha e o motivo.
- Tela do lote (F1-13): o bloco Financeiro deixou de ser "—" — aquisição, custos diretos e rateados vêm de `Purchase`/`CostEntry`.
- Telas de movimentação (F1) passaram a buscar o registro dentro do escopo do usuário (`for_user`): antes, um usuário de outra fazenda abria o detalhe em vez de receber 404 — bug da Fase 1 achado aqui. Movimento gerado por compra não se edita direto: a tela leva até a compra (era o que a F1-12 deixou previsto).

**Para rodar o importador de verdade:** custos → compras → movimentações (nessa ordem), depois `python manage.py conferir_importacao`. Hoje ele acusa 2 divergências **reais** (saldo 2.080 × 1.954 e as 2 transferências órfãs) — as duas dependem de resposta do produtor.

> **A F2-12 é a tarefa mais difícil do projeto inteiro.** O importador de movimentações com conciliação de transferências é onde os −140 da aba `GERAL` aparecem. Reserve-a para uma sessão inteira, descansado.

---

## Custos

### ✅ F2-01 · `costs` — Classe e Centro de custo
**Depende de:** F1-02 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/02](../regras-negocio/02-custos-centro-de-custo.md#estrutura-no-sistema)

`CostClass` (CUSTEIO, INVESTIMENTO) e `CostCenter` hierárquico via `parent`. Semear os 11 reais: FUNCIONARIO, PARQUE DE MÁQUINAS, DESPESA GADO, INFRAESTRUTURA, OUTROS, NUTRIÇÃO, PASTAGEM, IMPOSTO E TAXAS, COMISSÃO, SANIDADE, FERPAM.

Subcentro fica disponível e vazio — a coluna existe na planilha e nunca foi usada.

**Pronto quando:** os 11 estão semeados e dá para criar um subcentro sob PARQUE DE MÁQUINAS.

### ✅ F2-02 · `costs` — Lançamento
**Depende de:** F2-01 · **Estimativa:** 4-5h · **Spec:** [regras-negocio/02](../regras-negocio/02-custos-centro-de-custo.md#costentry--lançamento)

`CostEntry` com **fazenda, safra, centro e classe obrigatórios** — mudança consciente em relação à planilha, onde 39% do custo está sem centro. `MÊS` e `ANO` não existem como campo: derivam de `date`.

Implementa `ReversibleAction`.

**Pronto quando:** não dá para salvar lançamento sem centro de custo, e o filtro por safra × centro funciona.

### ✅ F2-03 · `CostAllocationService`
**Depende de:** F2-02 · **Estimativa:** 5-7h · **Spec:** [regras-negocio/05](../regras-negocio/05-indicadores-e-calculos.md#rateio-de-custo-indireto)

Custo direto (com `lot`) vai inteiro ao lote. Indireto rateia por **cabeça-dia**, com os outros critérios selecionáveis por centro. O critério aplicado fica **gravado no resultado**, para o número ser explicável meses depois.

**Pronto quando:** a soma das cotas é exatamente igual ao custo original — sem centavo perdido no arredondamento. É o teste que importa.

---

## Compras

### ✅ F2-04 · `purchases` — modelo e CRUD
**Depende de:** F1-05 · **Estimativa:** 4-5h · **Spec:** [regras-negocio/03](../regras-negocio/03-compra-de-gado.md)

`Purchase` com código `CP-2025/26-0001` gerado por serviço e unique por safra. Estados `RASCUNHO → CONFIRMADA → EXCLUÍDA`. Peso **opcional** — nem toda compra é pesada na entrada.

> **Pendência técnica da F1-05:** `Lot.origin_purchase` (FK para `Purchase`) não pôde ser criado na F1-05 porque `purchases.Purchase` ainda não existia — mesma situação da FK preguiçosa de `Farm` na F0-06. Esta tarefa precisa acrescentar o campo em `apps/livestock/models.py` (migração nova) antes de confirmar que a compra cria/aponta para o lote.

Formulário curto, com custo total e média por cabeça calculados ao digitar.

**Pronto quando:** a compra de 105 bezerros por R$ 260.172,15 mostra R$ 2.477,83/cabeça, batendo com a planilha.

### ✅ F2-05 · Confirmação transacional da compra
**Depende de:** F2-04, F2-02 · **Estimativa:** 4-6h · **Spec:** [regras-negocio/03](../regras-negocio/03-compra-de-gado.md#o-que-a-confirmação-faz)

Em uma transação, sob `select_for_update`: cria ou usa o lote, gera o movimento de entrada no rebanho, e gera um `CostEntry` para cada valor acessório preenchido.

É aqui que o "registrar uma vez, reaproveitar" acontece — na planilha isso é digitado duas vezes, na aba de compras e na aba da fazenda.

**Pronto quando:** teste de confirmação concorrente da mesma compra cria **um** movimento, não dois. O clique duplo é cenário real com a rede da fazenda.

### ✅ F2-06 · `PurchaseCostService`
**Depende de:** F2-05 · **Estimativa:** 2-3h · **Spec:** [regras-negocio/05](../regras-negocio/05-indicadores-e-calculos.md#custo-de-aquisição)

`animais + frete + comissão + impostos`. Custo/@ e custo/kg devolvendo `None` quando não há peso.

**Pronto quando:** compra sem peso mostra "—" em custo/@, nunca `0,00`.

### ✅ F2-07 · Editar e excluir compra, com cascata
**Depende de:** F2-05, F0-10 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md#análise-de-impacto)

`desfazer_efeitos()` da compra: movimento, custos gerados, e o lote se ele não tiver outras entradas. Tela de impacto listando tudo antes.

**Pronto quando:** excluir a compra desfaz os quatro efeitos, e excluir uma cujos animais já foram vendidos é bloqueado com o caminho explicado.

---

## Importação

### ✅ F2-08 · Motor de importação
**Depende de:** F0-10 · **Estimativa:** 6-8h · **Spec:** [migracao/01](../migracao/01-planilhas-e-importacao.md#fluxo-de-importação)

`ImportBatch` e `ImportRow`, e o fluxo `UPLOAD → STAGING → VALIDAÇÃO → PRÉVIA → ERROS POR LINHA → CONFIRMAÇÃO → IMPORTAÇÃO`. Transacional: falhou no meio, nada entrou. `file_hash` impede reimportar sem confirmação.

Cada `ImportRow` guarda a linha crua em JSON e, depois, o objeto que criou — rastreabilidade de qual linha de qual planilha virou qual registro.

**Pronto quando:** a prévia mostra válidas, pendentes e com erro, e cancelar não deixa resíduo.

### ✅ F2-09 · Leitor de planilha
**Depende de:** F2-08 · **Estimativa:** 3-4h · **Spec:** [migracao/01](../migracao/01-planilhas-e-importacao.md)

openpyxl com duas regras que vieram da análise:

- Serial de data do Excel (`45840` = 2025-07-02), origem 1899-12-30
- **`#DIV/0!`, `#N/A` e célula vazia viram pendência tratável, nunca falha**
- **Linha em branco não é lançamento de R$ 0,00** — se não há data nem valor, a linha não existe, mesmo com outras células preenchidas

**Pronto quando:** ler a aba `CUSTOS` devolve 235 lançamentos, não 417.

### ✅ F2-10 · Importador de CUSTOS
**Depende de:** F2-09, F2-02 · **Estimativa:** 5-7h · **Spec:** [migracao/01](../migracao/01-planilhas-e-importacao.md#ordem-dos-importadores)

235 lançamentos reais somando R$ 1.046.907,76. Fazenda escolhida na importação (a planilha não tem a coluna).

Classificação assistida por padrão de texto para os **106 sem centro de custo** (R$ 411.132,64) e os **96 sem descrição** — sugestão com confirmação humana, nunca adivinhação silenciosa.

**Pronto quando:** o total importado é exatamente R$ 1.046.907,76 e os 11 centros somam o mesmo.

### ✅ F2-11 · Importador de COMPRA DE GADO
**Depende de:** F2-09, F2-05 · **Estimativa:** 4-5h · **Spec:** [migracao/01](../migracao/01-planilhas-e-importacao.md)

13 compras, 954 cabeças, R$ 2.457.752,15. Descartar `MÉDIA/CAB` (derivado com `#DIV/0!`). Criar um lote por compra. Importar como `CONFIRMADA`, gerando movimento e custos.

"BEZERROS" mapeia para `Machos Desm. até 12m` — **a confirmar com o produtor**.

**Pronto quando:** 954 cabeças entraram no rebanho e R$ 2.457.752,15 em custos, sem digitação dupla.

### ✅ F2-12 · Importador de movimentações com conciliação
**Depende de:** F2-09, F1-07 · **Estimativa:** 7-10h · **Spec:** [migracao/01](../migracao/01-planilhas-e-importacao.md#ordem-dos-importadores)

A tarefa mais difícil do projeto.

As 5 abas de fazenda têm duas partes: linhas 4-16 são quadro-resumo derivado (**descartar**), linhas 19+ são o lançamento real (**importar**).

O problema: `TRANSF. S` e `TRANSF. E` estão em linhas separadas e precisam virar **um movimento de 2 linhas**. O importador pareia por data, categoria e quantidade. **O que não parear vira pendência na tela, para o usuário decidir — nunca contrapartida inventada.**

É aqui que os 140 aparecem. Com a pendência [#2](../regras-negocio/99-pendencias.md) resolvida, você sabe o que fazer com eles.

Destinos em texto livre ("COPERFRIGU", "CANTINA", "COMPRA GOIANO") viram `Partner` ou `Farm`, com confirmação.

**Pronto quando:** toda transferência pareada virou movimento de soma zero, e as não pareadas estão listadas aguardando decisão — nenhuma importada em silêncio.

---

## Fechamento

### ✅ F2-13 · Relatórios de custo
**Depende de:** F2-03 · **Estimativa:** 4-5h · **Spec:** [relatorios/01](../relatorios/01-catalogo.md#fase-2--custos-e-compras)

Custo por centro, por fazenda, custeio × investimento, compras do período, custo de aquisição por lote. Substituem `DASH FINANCEIRO` e `DASH COMPRAS`.

**Pronto quando:** o relatório por centro reproduz a tabela do `DASH FINANCEIRO`, inclusive os R$ 411.132,64 — agora classificados.

### ✅ F2-14 · Comando `conferir_importacao`
**Depende de:** F2-12 · **Estimativa:** 2-3h · **Spec:** [migracao/01](../migracao/01-planilhas-e-importacao.md#conferência-pós-importação)

Imprime a tabela comparativa sistema × planilha: 235 lançamentos, R$ 1.046.907,76, 954 cabeças, R$ 2.457.752,15, 354 abatidas, saldo 1.954, 11 centros, 11 categorias, e as transferências não pareadas.

**Pronto quando:** roda em um comando e qualquer divergência salta aos olhos.

### ❌ F2-15 · Deploy da Fase 2
**Depende de:** F2-14 · **Estimativa:** 1h

**Pronto quando:** está em produção, pronto para receber o histórico real no marco da virada.

> **Não executada — falta o VPS**, como a F0-17/F0-18/F1-16. Nada no pipeline muda: são migrações novas (`costs` 0002-0004, `purchases` 0001, `imports` 0001, `herd` 0004, `livestock` 0003, `audit` 0003) aplicadas limpas em Postgres 16 real, e o volume `rebanho360_media` (onde ficam as planilhas enviadas) já está no compose e no `backup.sh`. Ao subir: `migrate`, conferir `/health/`, lançar um custo e uma compra pelo celular, e só então importar.

---

## Fase fechada quando

- [x] 235 linhas de custo somando R$ 1.046.907,76 *(234 lançamentos + 1 de R$ 0,00 ignorada)*
- [x] 954 cabeças por R$ 2.457.752,15
- [ ] Saldo 1.954 em São Francisco — **fecha em 2.080** até responder a [#10](../regras-negocio/99-pendencias.md) (compra de 126 cabeças fora da aba)
- [x] Os 11 centros de custo somam o total
- [x] Nenhuma transferência importada sem contrapartida *(as 2 órfãs ficam pendentes, [#2](../regras-negocio/99-pendencias.md))*
- [ ] `conferir_importacao` roda limpo — **roda e acusa as 2 divergências acima**, de propósito
- [x] Rateio de custo não perde centavo
- [x] Confirmação concorrente da mesma compra cria um movimento
- [ ] Está no ar em produção — **falta VPS** (F2-15)

### 🎯 Aqui a planilha pode ser aposentada

Tecnicamente. A aposentadoria de verdade é operacional e tem documento próprio.

> **Resolver antes da carga real:** **[#2]**, **[#5]**, **[#10]**, **[#11]**, e nesta fase também **[#3](../regras-negocio/99-pendencias.md)** (o que é "PARCERIA") e **[#6](../regras-negocio/99-pendencias.md)** (quem é "ONODA"). Ambas afetam a importação.

**Próximo:** [Marco — Virada](marco-virada.md)
