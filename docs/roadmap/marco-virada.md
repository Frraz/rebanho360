# Marco — Virada

**~15-25h de trabalho + 30 dias corridos de paralelo**

Não é desenvolvimento. É operação — e é aqui que projetos assim costumam falhar, com o sistema pronto e ninguém usando.

Acontece entre a Fase 2 e a Fase 3. A **Fase 3 é desenvolvida durante o paralelo**: os 30 dias de espera não são ociosos.

---

## Por que paralelo, e não virada seca

Por 30 dias, cada lançamento é feito **nos dois** — planilha e sistema. No fim do mês, os números são comparados.

Custa retrabalho temporário. Compra a única coisa que importa aqui: descobrir um erro grave **enquanto a planilha ainda está viva**. Virada seca que dá errado deixa a operação sem controle nenhum, no meio da safra, com animais no pasto e dinheiro a pagar.

Trinta dias é o suficiente para atravessar um ciclo completo de fechamento: compra, movimentação, custo do mês, e pelo menos uma conferência.

---

### V-01 · Resolver as pendências com o produtor
**Estimativa:** variável · **Spec:** [99-pendencias](../regras-negocio/99-pendencias.md)

Sentar com o produtor, com a planilha aberta, e fechar:

| Pendência | Pergunta | Bloqueia |
|---|---|---|
| **#5** | São Francisco e São Francisco II: uma fazenda ou duas? | A importação inteira |
| **#2** | Os −140: erro de preenchimento ou saída do grupo? | A conciliação de transferências |
| **#3** | "PARCERIA" sempre `-`: existe operação em parceria? | O rateio de custo e resultado |
| **#6** | "ONODA": empresa, sócio ou conta? | O cadastro de pagador |
| **#9** | `ESCRITORIO` pode excluir, ou só editar? | As permissões reais |

Registrar a resposta **no próprio documento**, com data e quem respondeu. A pergunta fica junto — apagá-la é perder o motivo da regra.

**Pronto quando:** as cinco estão marcadas ✅ com a resposta escrita.

### V-02 · Importar o histórico em produção
**Depende de:** V-01 · **Estimativa:** 4-6h · **Spec:** [migracao/01](../migracao/01-planilhas-e-importacao.md)

Backup antes. Rodar os três importadores em produção, na ordem: custos, compras, movimentações. Resolver as transferências não pareadas conforme a decisão da #2.

Rodar `conferir_importacao` e comparar linha a linha com a planilha.

**Pronto quando:** os oito números de conferência batem. **Divergência de um centavo é investigada**, não arredondada.

### V-03 · Usuários e escopos reais
**Depende de:** V-02 · **Estimativa:** 2h · **Spec:** [ADR 0003](../arquitetura/adr/0003-escopo-por-fazenda-desde-a-fase-0.md)

Criar as contas reais com papel e `UserFarmAccess`. Senha inicial trocada no primeiro acesso. Nenhuma conta compartilhada — auditoria com login compartilhado não serve para nada.

**Pronto quando:** cada pessoa tem conta própria e enxerga só as fazendas que lhe cabem.

### V-04 · Treinamento
**Depende de:** V-03 · **Estimativa:** 3-4h

Dois públicos, duas conversas:

**Campo, no celular, no curral.** Lançar morte, pesagem e transferência. Mostrar que o rascunho sobrevive à queda de sinal. Quinze minutos por pessoa, no local de trabalho — não em sala.

**Escritório, no navegador.** Custo, compra, venda, relatórios. E as três coisas que mudam o hábito: motivo obrigatório ao corrigir, análise de impacto antes de excluir, e indicador "—" significando dado faltando, não zero.

Deixar um guia de uma página por público. Uma página, não um manual.

**Pronto quando:** cada pessoa fez um lançamento real sozinha, sem ajuda.

### V-05 · Paralelo — 30 dias
**Depende de:** V-04 · **Duração:** 30 dias corridos

Lançar nos dois. Conferir semanalmente, não só no fim:

- Semana 1: saldo por fazenda bate?
- Semana 2: custos do período batem?
- Semana 3: alguém está deixando de lançar no sistema? *(o sinal mais importante)*
- Semana 4: preparar o fechamento

Se alguém parou de lançar no sistema, o problema não é disciplina — é que alguma tela está difícil. Investigar e corrigir antes de virar.

**Pronto quando:** 30 dias cumpridos com lançamento nos dois, sem lacuna.

### V-06 · Conferência de fechamento
**Depende de:** V-05 · **Estimativa:** 3-4h

O exame final. Comparar planilha × sistema:

- [ ] Saldo por fazenda e por categoria
- [ ] Entradas e saídas do mês, por tipo
- [ ] Custo total e por centro
- [ ] Compras: quantidade, cabeças, valor
- [ ] Vendas e abates: cabeças, peso, carcaça, valor
- [ ] Transferências: todas pareadas

**Toda divergência é investigada até a causa.** Quase sempre o sistema está certo e a planilha não — mas a direção da conclusão tem que vir da investigação, não da torcida.

**Pronto quando:** não há divergência inexplicada.

### V-07 · Aposentar a planilha
**Depende de:** V-06 · **Estimativa:** 1h

- Congelar em somente-leitura
- Arquivar com a data da virada no nome
- Guardar cópia junto com os backups
- Comunicar: a partir de hoje, só o sistema

**Pronto quando:** ninguém mais lança na planilha, e ela está preservada para consulta.

### V-08 · Rotina pós-produção
**Depende de:** V-07 · **Estimativa:** 2h para montar

A parte que não termina:

| Quando | O quê |
|---|---|
| Diário | Backup roda sozinho; alerta se falhar |
| Semanal | Conferir que o backup externo chegou; olhar o painel de pendências |
| Mensal | **Restaurar um backup** e anotar em `deploy/restore-log.md`; revisar a auditoria; conferir disco |
| Por safra | Fechar a safra; comparar com a anterior |

A restauração mensal é a única que prova que o backup existe de verdade. Backup nunca restaurado é hipótese.

**Pronto quando:** está na agenda de alguém, com responsável e dia.

---

## Marco fechado quando

- [ ] As 5 pendências respondidas e registradas
- [ ] Histórico importado em produção, com os 8 números conferindo
- [ ] Cada pessoa com conta própria e escopo correto
- [ ] Todos treinados, cada um com um lançamento real feito sozinho
- [ ] 30 dias de paralelo cumpridos
- [ ] Fechamento sem divergência inexplicada
- [ ] Planilha congelada e arquivada
- [ ] Rotina pós-produção com responsável e dia

## Se der errado

O paralelo existe para que "dar errado" seja barato. Rotas de volta:

**Divergência que não se explica** → não virar. Investigar, corrigir, estender o paralelo mais um mês. O custo é lançar duas vezes; o benefício é não perder o controle da operação.

**Ninguém está usando** → problema de tela, não de pessoa. Achar qual passo é penoso e consertar antes de insistir.

**Bug grave em produção** → a planilha ainda está viva. Volta para ela, corrige, reimporta o período.

**Depois de virada** → o backup diário e a auditoria completa permitem reconstruir qualquer estado. É para isso que o F0-18 existe.

**Próxima:** [Fase 3 — Vendas, abates e indicadores](fase-3-vendas-e-indicadores.md) *(desenvolvida durante o paralelo)*
