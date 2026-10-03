# ADR 0006 — Tudo editável e excluível, com auditoria imutável

**Data:** 2026-09-30 · **Status:** Aceita · **Substitui** parte da [ADR 0002](0002-rebanho-como-razao-de-movimentacoes.md)

## Problema

O sistema terá mais de 10 usuários entre campo e escritório. Erro de lançamento é rotina, não exceção: contagem errada no curral, valor trocado, compra duplicada, categoria equivocada.

Como corrigir?

A primeira versão desta documentação respondia "estorno, nunca edição". O produtor decidiu diferente: **toda ação deve ser editável e excluível, com todos os efeitos desfeitos, e tudo registrado em auditoria visível ao administrador.**

## Decisão

**Editar e excluir são operações de primeira classe em todo registro transacional.** Desfazer uma ação desfaz os efeitos que ela produziu, na mesma transação.

Quatro mecanismos sustentam isso:

**1. Exclusão lógica.** Nenhuma linha sai do banco. `EXCLUÍDA` é estado, e é restaurável.

**2. Efeitos declarados.** Cada ação sabe o que produziu (via FKs que já existem: `documento_origem`, `source_purchase`, `origin_purchase`) e sabe desfazer.

**3. Razão append-only com data do fato.** No rebanho, desfazer escreve linhas de compensação datadas no **fato original**, não na correção. O saldo histórico reflete a correção; `created_at` guarda quando ela foi feita.

**4. Auditoria imutável, inclusive para o `ADMIN`.** Sem tela, sem método de serviço, sem `UPDATE`/`DELETE` no papel de banco da aplicação.

Regra completa em [regras-negocio/06](../../regras-negocio/06-edicao-exclusao-e-auditoria.md).

## Alternativas descartadas

**Estorno, nunca edição** — a decisão anterior. Mais rigorosa: o histórico é estritamente append-only e nada é ambíguo. Descartada por dois motivos.

O prático: corrigir um erro de digitação exige duas operações e três registros, e o usuário passa a ver na tela três lançamentos onde houve um fato. Numa operação com dezenas de lançamentos por semana e correções rotineiras, isso enche a tela de ruído e leva a pessoa a evitar corrigir.

O conceitual, que é o mais forte: estorno é a ferramenta certa para **um fato que mudou** (a compra foi cancelada de verdade) e a ferramenta errada para **um registro que estava errado** (a compra sempre foi de 120, alguém digitou 126). O segundo caso é o comum, e tratá-lo como estorno grava no histórico um evento que nunca aconteceu.

**Edição direta, sem desfazer efeitos.** O caminho ingênuo: alterar o registro e pronto. Deixa saldo e custo dessincronizados do documento que os gerou. É a doença que a planilha tem.

**Exclusão física.** Some com a linha. Torna a auditoria a única prova, sem nada para restaurar, e quebra qualquer FK apontando para o registro.

**Versionamento em tabela separada** (`PurchaseVersion`, `SaleVersion`…). Uma tabela de histórico por modelo. Duplica esquema, e o `AuditEvent` com `before`/`after` em JSON já entrega o mesmo, num lugar só.

## Consequências

**Boas:** a correção acompanha como as pessoas realmente trabalham — vê o erro, corrige o erro. Uma única mecânica para todos os modelos, aprendida uma vez. Saldo histórico fica verdadeiro, porque a compensação leva a data do fato. A análise de impacto, que a regra obriga, mostra ao usuário a rede de dependências que a planilha nunca mostrou.

**Ruins, e precisam de atenção:**

*A auditoria vira o único guardião.* Se ela falhar, não há segunda fonte. Por isso é imutável em nível de permissão de banco, gravada na mesma transação da ação, e conferida por teste que garante inexistência de caminho de escrita.

*Desfazer pode cascatear.* Excluir uma compra cujos animais foram vendidos toca vários registros. Mitigado por análise de impacto obrigatória, cascata explícita confirmada pelo usuário, e bloqueio quando o efeito é irreversível no mundo real (pagamento já baixado).

*Alguém pode reescrever a história sem que ninguém perceba.* A auditoria registra, mas registro que ninguém lê não protege. Por isso o console de auditoria entra já na **Fase 0**, com filtro e exportação — e não como tela adiada para o fim.

*Mais código.* Cada serviço precisa implementar `desfazer_efeitos()` e `dependentes()`, não só `aplicar_efeitos()`. É o custo real desta decisão, e é o que a torna confiável.

## Pendência

**#9** — Quem pode excluir registro confirmado? Adotado `GESTOR` e `ADMIN`, com motivo obrigatório. A definir se `ESCRITORIO` também exclui ou apenas edita.
