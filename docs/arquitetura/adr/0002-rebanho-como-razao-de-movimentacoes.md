# ADR 0002 — Rebanho como razão de movimentações com partidas dobradas

**Data:** 2026-09-30 · **Status:** Aceita

## Problema

Como representar o saldo do rebanho — quantas cabeças de cada categoria há em cada fazenda e lote?

A planilha atual usa campos somáveis por categoria, com colunas separadas de entrada e saída. O resultado mensurável: na aba `GERAL`, `TRANSF. S = 140` e `TRANSF. E = 0`, deixando o consolidado do grupo em **−140 cabeças**. A aba está oculta e ninguém percebeu.

## Decisão

**O saldo nunca é campo. É sempre a soma dos eventos.**

Duas tabelas:

- `HerdMovement` — o documento do evento, o que o usuário preenche
- `HerdLedgerEntry` — as linhas geradas, com quantidade **com sinal**, nunca editáveis

Movimento simples (compra, nascimento, morte, abate, venda) gera **1 linha**.
Movimento de deslocamento (transferência, evolução de categoria, mudança de lote) gera **2 linhas** — negativa na origem, positiva no destino, **na mesma transação**.

```
saldo(posição, data) = SUM(HerdLedgerEntry.quantidade) até a data
```

## Alternativas descartadas

**Campo de saldo atualizado a cada movimento.** É o que a planilha faz. Rápido de ler e impossível de auditar: se o saldo diverge, não há como saber onde. E a transferência pode sair sem entrar — o bug dos −140.

**Saldo em campo + log de auditoria.** Duas fontes da verdade que divergem sob concorrência. Quando divergem, qual está certa? Auditoria que não é a fonte do número não protege o número.

**Event sourcing completo.** A ideia certa levada longe demais: event store, projeções, replay, versionamento de evento. O razão de movimentações já dá reconstituição e auditoria exatamente onde importam, com uma fração da complexidade.

## Consequências

**Boas:** saldo negativo por transferência perdida vira **impossível de representar** — as duas linhas nascem juntas ou nenhuma nasce. Saldo em qualquer data histórica sai de graça (`WHERE data <= X`). Auditoria natural: todo número tem as linhas que o compõem. Evolução de categoria, transferência entre fazendas e mudança de lote usam o mesmo mecanismo.

**Ruins:** ler saldo é `SUM` em vez de `SELECT` de um campo — resolvido com índice em `(fazenda, categoria, data)` e, se um dia necessário, snapshot mensal como *cache* (nunca como fonte). Escrever é mais caro: duas linhas e uma transação. Correção escreve linhas de compensação em vez de alterar as originais — ver [ADR 0006](0006-tudo-editavel-com-auditoria-imutavel.md).

**A invariante que precisa de cuidado:** saldo não pode ficar negativo. Tem que ser verificada **dentro** da transação, com `select_for_update` na posição afetada. Fora dela, dois lançamentos simultâneos passam na validação e produzem saldo negativo — exatamente o que este ADR existe para impedir.
