# Fase 6 — Avançado

**Esforço aberto · CONDICIONAL**

Nada aqui é dívida. É o que a operação pode vir a pedir, registrado para não se perder e para não ser construído por antecipação.

Antes de puxar qualquer item: **isto resolve uma necessidade real, hoje?** Se a resposta for "seria legal ter", não entra.

---

## Brinco individual · ~40-60h

Entidade `Animal`, com histórico próprio de peso, lote, fazenda e categoria.

**Quando faz sentido:** quando a operação passar a lançar "morreu o animal 1.632" em vez de "12 mortes em outubro". Enquanto o lançamento for agregado, exigir brinco empurra o campo de volta para o WhatsApp — ver [ADR 0004](../arquitetura/adr/0004-lote-agregado-antes-de-brinco.md).

**O caminho já está preparado:**

1. Criar `Animal` com `ear_tag`, `lot`, `category`, `birth_date`, `status`
2. **Popular a partir dos `WeighingAnimal` já importados** — os brincos históricos viram animais reais, com o histórico de peso que a F3-07 preservou
3. Acrescentar `HerdMovementAnimal` (movimento × animal), **opcional** — movimento pode continuar sendo por quantidade
4. Saldo continua saindo do razão: `HerdLedgerEntry` não muda

O que torna isso possível sem reescrita é a decisão do [ADR 0002](../arquitetura/adr/0002-rebanho-como-razao-de-movimentacoes.md): saldo derivado de eventos. Identificação individual vira um detalhamento do evento, não uma nova forma de contar.

---

## Reprodução · ~30-40h

Cobertura, diagnóstico de gestação, parto, desmame. Taxa de prenhez, intervalo entre partos, natalidade.

**Quando faz sentido:** se a operação tiver cria. A planilha tem abas `DADOS REPRODUTIVOS` e `NASCIMENTOS`, ambas ocultas e vazias — hoje a operação é de recria e engorda.

---

## Indicadores zootécnicos avançados · ~25-35h

Da `REPORTAGEM IVAN`, já transcritos em [regras-negocio/05](../regras-negocio/05-indicadores-e-calculos.md#indicadores-avançados-fase-6):

rendimento do ganho · GMD de carcaça/dia · eficiência biológica (kg de MS por @) · consumo % do peso vivo · dias para colocar 1 @ · lotação em UA/ha.

**Quando faz sentido:** quando houver o dado que os alimenta. Hoje não há medição de consumo nem de matéria seca — os indicadores existiriam sem entrada.

---

## Confinamento · ~30-40h

Curral, dieta, curva de consumo, dias de cocho, custo de alimentação por lote.

**Quando faz sentido:** se a operação confinar. Hoje a aba `VENDAS` marca todas as saídas como forma `PASTO`.

---

## Análise gerencial · ~20-30h

Curva ABC, TIR, inventário valorizado com efeito de mercado (R$/@ início × fim de safra), comparação entre safras, benchmark.

**Quando faz sentido:** com pelo menos duas safras completas no sistema. Com uma só, não há o que comparar.

---

## Busca global · ~8-12h

Por código de compra, venda, lote, parceiro e documento.

**Quando faz sentido:** quando o volume tornar a navegação lenta. Com 14 lotes e 13 compras por safra, o menu resolve.

---

## Melhorias de desempenho

Não antecipar. Medir primeiro. Candidatos, na ordem em que provavelmente apertam:

1. `HerdMonthlySnapshot` como cache do saldo histórico — **nunca** como fonte da verdade, e sempre recalculável
2. Materialized view para o dashboard
3. Índices adicionais conforme o log de consultas lenta apontar

Com o volume atual — menos de 10 mil movimentos por safra — nenhum é necessário.

---

**Volta ao início:** [Roadmap](README.md)
