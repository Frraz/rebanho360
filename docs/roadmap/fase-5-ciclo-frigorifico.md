# Fase 5 — Ciclo de compra

**~125h · 20 tarefas · construída antecipadamente, por decisão do produtor** — *F5-01 a F5-19 feitas; deploy pendente*

> **Escopo principal desde 2026-10-02.** O documento funcional (`docs/fontes/Sistema_Gestao_Pasto_Compra_Gado_Estrutura_Funcional.md`) trata a compra como parte integrada da gestão a pasto. Os conceitos vêm do SisAtak (frigorífico Boi Brasil), documentado em [fluxos/03](../fluxos/03-fluxo-compra-frigorifico.md). A modelagem do núcleo comporta o ciclo, e nada do que já funcionava foi alterado. O que ainda falta contra o documento funcional: [matriz de alinhamento](../fluxos/04-alinhamento-ao-doc-funcional.md).

---

## Status (atualizado 2026-10-02)

**Fase aprovada por Warley (dono do produto) em 2026-10-02.** Depois, no mesmo dia, ele fixou o documento funcional como fonte principal do escopo — o gatilho abaixo deixou de ser pré-requisito. O roadmap original dizia "só se e quando a operação exigir" e listava três pré-requisitos. A decisão de construir antes foi consciente, e o estado deles é este:

| Pré-requisito | Estado |
|---|---|
| **Gatilho** (comprar para terceiros, ser comprador comissionado ou vender por faixa) | ➖ superado: o ciclo de compra é escopo principal, não opção |
| **Regra tributária confirmada com o contador** | ❌ não confirmada. **Nenhuma alíquota, base ou fórmula foi implementada**: tributos são valores digitados ([#21](../regras-negocio/99-pendencias.md)) |
| **Pendências #4 e #8** | ❌ abertas. Construído com padrão reversível: comissão configurável com snapshot ([#4](../regras-negocio/99-pendencias.md)) e faixa só na compra ([#8](../regras-negocio/99-pendencias.md)) |
| **Reler os 5 relatórios legados** | ✅ relidos em 2026-10-02; são a especificação dos relatórios F5-14 a F5-17 |

**Antes de usar de verdade:** responder #21 com o contador, e #24 e #25 com o produtor. As demais pendências (#20 a #26) têm padrão reversível e podem esperar.

Decisões de modelagem em [ADR 0008](../arquitetura/adr/0008-ciclo-de-compra-por-composicao.md). Regra completa em [regras-negocio/08-ciclo-de-compra](../regras-negocio/08-ciclo-de-compra.md).

---

## Como encaixa sem quebrar o que existe

O modelo do núcleo **não muda**. Duas apps novas — `commercial` (cadastros) e `procurement` (o ciclo) — e **nenhuma coluna nova** em `Purchase`, `Lot`, `CostEntry`, `HerdMovement` ou `Invoice`.

```
Commitment ─┬─ CommitmentItem ──(acerto aprovado)──> Purchase ──> rebanho + custos + títulos
            ├─ Commission (snapshot da regra)         └ a mesma compra de sempre
            ├─ Trip ── TripLoad ── Receiving ── ReceivingLine
            ├─ CommitmentItem ── GradingLine (romaneio valorizado)
            └─ Settlement ── SettlementLine · FiscalNote
```

Hoje a compra é `RASCUNHO → CONFIRMADA`. O ciclo acrescenta as etapas **antes**; `CONFIRMADA` é alcançada depois do acerto aprovado. A compra direta (tela de Compras) continua existindo e funcionando igual.

A **etapa** do compromisso (negociação · aprovado · em viagem · recebido · em acerto · acerto aprovado) **não é campo**: é derivada do que existe. A **trava de fechamento** do acerto é `bloqueios()`, não estado.

---

**O que foi construído** (resumo; regra completa em [08](../regras-negocio/08-ciclo-de-compra.md))

- Duas apps novas, `commercial` e `procurement`, com **13 tabelas** e nenhuma coluna nova no núcleo. Cada item do compromisso gera uma `Purchase` na aprovação do acerto; a etapa é derivada.
- **Defeito do núcleo encontrado e corrigido:** `Purchase.dependentes()` listava o movimento de saída que uma venda gerou, e não a `Sale`. Excluir a compra em cascata deixaria a venda confirmada sem saída no rebanho. Agora lista a venda, que se desfaz pelo próprio documento. Vale para a compra direta também.
- Ajuste mínimo em `ExclusaoComImpactoView` (`pode_excluir(registro)`) e gancho em `finance` (favorecido e valor líquido; `{}` para compra direta).
- Contrato PDF (`contrato-v1`), sete relatórios, três pendências no painel, menu "Ciclo de compra".
- **Testes:** **1.210 testes na suíte completa, todos verdes** contra Postgres real (32 em `commercial`, 382 em `procurement`); `ruff`/`black` limpos; telas verificadas em **360 px e 1366 px** com navegador real (44 páginas, sem rolagem horizontal). A verificação visual achou dois defeitos que os testes não pegaram: valores cortados no cartão do celular e a base da comissão em branco.
- **Não feito:** F5-20 (sem VPS). Venda por faixa (#8) e parcelamento ficaram de fora.

## Dois pontos de cuidado

**Snapshot de regra comercial.** Se a comissão era 1% em janeiro e alguém muda o cadastro para 1,5% em março, a operação de janeiro **não pode** passar a mostrar 1,5%. A regra aplicada é copiada para o compromisso quando ele é aprovado.

**Trava de fechamento.** Acerto aprovado impede edição dos valores consolidados. Corrigir exige reabertura formal, com registro de quem, quando e por quê, e recálculo das obrigações ligadas: as compras saem em cascata, e baixa de título já feita **bloqueia** a reabertura, com o link para o pagamento.

---

## Tarefas

### F5-01 · Pendências, ADR e regra de negócio — ✅ feita
**Depende de:** — · **Estimativa:** 2h · **Spec:** [ADR 0008](../arquitetura/adr/0008-ciclo-de-compra-por-composicao.md)

Registrar #20 a #26, o ADR do desenho por composição e a regra [08](../regras-negocio/08-ciclo-de-compra.md).

**Pronto quando:** toda regra inventada pela fase está em `99-pendencias.md`, com pergunta, padrão e custo de mudar.

### F5-02 · `commercial` — Classes de carcaça — ✅ feita
**Depende de:** — · **Estimativa:** 4h · **Spec:** [fluxos/03](../fluxos/03-fluxo-compra-frigorifico.md#classificação-de-carcaça)

`CarcassClass` (código, nome, ordem, `default_band` opcional, ativo), com as seis do legado semeadas (Magro, Gordura Ausente, Escassa, Mediana, Uniforme, Lesão Traumática). Cadastro com tela. **Parametrizável, nunca fixo no código.**

**Pronto quando:** acrescentar uma classificação nova é só cadastro, e nenhuma classe aparece escrita no código fora do seed.

### F5-03 · `commercial` — Tipos de tributo, taxa e desconto — ✅ feita
**Depende de:** — · **Estimativa:** 3h · **Spec:** [#21](../regras-negocio/99-pendencias.md)

`TaxType` (nome, natureza `TRIBUTO`/`TAXA`/`DESCONTO`/`ADIANTAMENTO`/`CREDITO`, ativo), com os nove nomes do legado semeados. **Sem alíquota, sem base, sem fórmula.**

**Pronto quando:** não há campo de percentual nem de base de cálculo em `TaxType`, e há teste que trava isso.

### F5-04 · `commercial` — Regra de comissão e `CommissionService` — ✅ feita
**Depende de:** — · **Estimativa:** 7h · **Spec:** [#4](../regras-negocio/99-pendencias.md)

`CommissionRule` (comissionado, categoria, tipo, base, valor, vigência). `escolher_regra()` pela mais específica vigente. `calcular_comissao()` isolada em `apps/commercial/commission.py`: percentual sobre bruto **ou** líquido, ou valor por cabeça. `Decimal`, `ROUND_HALF_UP` só no fim, divisor zero devolve `None`.

**Pronto quando:** testes de bruto × líquido, por cabeça, vigência, especificidade e arredondamento em `0,005` passam.

### F5-05 · `procurement` — Compromisso e itens — ✅ feita
**Depende de:** F5-02, F5-04 · **Estimativa:** 10h · **Spec:** [fluxos/03](../fluxos/03-fluxo-compra-frigorifico.md)

`Commitment` e `CommitmentItem` (categoria, cabeças, peso médio previsto, preço por faixa 1–5 **ou** por cabeça). Rascunho → **aprovado** (`confirmar`) → excluído, com impacto e motivo. Aprovar **copia a regra de comissão** para `Commission`. `etapa_do_compromisso()` derivada. Programação (retirada, abate, caminhões, distância) são campos do compromisso. Tela mobile, escopo por fazenda, auditoria.

**Pronto quando:** mudar a regra de comissão depois da aprovação **não** muda a comissão do compromisso (teste), e a etapa recua sozinha ao excluir uma peça.

### F5-06 · Contrato em PDF — ✅ feita
**Depende de:** F5-05 · **Estimativa:** 6h · **Spec:** [relatorios/01](../relatorios/01-catalogo.md#documentos-gerados)

Documento de compromisso (referência: `02_Contrato_Compra_Animais`), pelo `GeneratedDocument`, com `template_version`. O arquivo guardado é a reprodução exata, mesmo que o layout mude. Dado bancário **não** vai no contrato.

**Pronto quando:** gerar duas vezes grava dois documentos com hash, e o PDF só é servido por view autenticada e com escopo.

### F5-07 · Viagem, embarque e frete — ✅ feita
**Depende de:** F5-05 · **Estimativa:** 10h · **Spec:** [fluxos/03](../fluxos/03-fluxo-compra-frigorifico.md)

`Trip` (transportador, motorista, placa, distância) e `TripLoad` (programado × embarcado, peso de origem). Frete na viagem: critério (cabeça, km, kg, viagem), tarifa, **previsto calculado** e **realizado digitado**. Uma compra pode ter várias viagens.

**Pronto quando:** o frete previsto de cada critério confere com conta feita à mão, e embarcar acima do compromisso avisa.

### F5-08 · Recebimento e quebra de viagem — ✅ feita
**Depende de:** F5-07 · **Estimativa:** 9h · **Spec:** [#23](../regras-negocio/99-pendencias.md)

`Receiving` por viagem, com cabeças e peso recebidos, categoria recebida e ocorrências. **Quebra** = `(origem − recebido) ÷ origem`, calculada, com alerta acima do limite. Diferença de quantidade e de peso sempre visível.

**Pronto quando:** peso de origem zero devolve "—" (não `0%`) e a quebra não desconta nada do valor.

### F5-09 · Classificação de carcaça e romaneio valorizado — ✅ feita
**Depende de:** F5-02, F5-05 · **Estimativa:** 9h · **Spec:** [relatorios/01](../relatorios/01-catalogo.md#04_conferencia_do_acertopng)

`GradingLine`: item, classificação, **faixa**, cabeças, peso de carcaça, preço da @ (copiado da faixa, editável), % de desconto. Derivados — média @, valor bruto, valor/kg, valor líquido — saem de um serviço, nunca de campo.

**Pronto quando:** o romaneio do legado (111 cabeças, 24.071,50 kg) é reproduzido por teste: cabeças, peso e média @ exatos; o valor, dentro de R$ 0,15 por linha — o legado imprime o preço da @ arredondado e arredonda por conta própria.

### F5-10 · Acerto — previsto × realizado — ✅ feita
**Depende de:** F5-08, F5-09 · **Estimativa:** 10h · **Spec:** [fluxos/03](../fluxos/03-fluxo-compra-frigorifico.md#acerto-final)

`Settlement` e `calcular_acerto()`: quantidade, peso, categoria, preço, valor, frete, comissão e datas — **previsto × realizado**. Tudo derivado; o que impede aprovar (item sem recebimento, item por @ sem romaneio) aparece como **pendência com o motivo**.

**Pronto quando:** compromisso sem romaneio mostra "—" e diz por quê; nenhum total é gravado.

### F5-11 · Acerto — tributos, taxas, descontos, adiantamentos e notas fiscais — ✅ feita
**Depende de:** F5-03, F5-10 · **Estimativa:** 6h · **Spec:** [#21](../regras-negocio/99-pendencias.md)

`SettlementLine` (valor digitado por `TaxType`) e `FiscalNote` (número, série, data, valor). Efeito de cada natureza em uma tabela única.

**Pronto quando:** tributo soma ao custo, desconto reduz o animal, adiantamento e crédito reduzem só o líquido a pagar; nota fiscal registrada **bloqueia** reabrir o acerto, com o caminho.

### F5-12 · Aprovar o acerto: compras, rateio e títulos — ✅ feita
**Depende de:** F5-11 · **Estimativa:** 12h · **Spec:** [ADR 0008](../arquitetura/adr/0008-ciclo-de-compra-por-composicao.md)

Aprovar = **uma transação**: cria e confirma **uma `Purchase` por item**, com os valores consolidados; rateia frete, comissão e tributos por cabeça recebida (`ratear_em_centavos`); gera os títulos com **favorecido** (transportador no frete, comissionado na comissão) e o líquido do produtor. **Trava de fechamento** por `bloqueios()`. Compra nascida do acerto não se edita direto.

**Pronto quando:** aprovar duas vezes (ou duas pessoas ao mesmo tempo) gera **uma** compra por item e **um** título por componente; a soma dos rateios é exatamente o total; com o acerto aprovado, tudo que alimenta o valor recusa edição e diz "reabra o acerto".

### F5-13 · Reabrir, excluir e restaurar o acerto — ✅ feita
**Depende de:** F5-12 · **Estimativa:** 6h · **Spec:** [regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md)

**Reabertura formal**: motivo obrigatório, quem e quando na auditoria, efeitos desfeitos em cascata (compras, movimento, custos, títulos). Baixa de título e safra encerrada bloqueiam, com link.

**Pronto quando:** reabrir desfaz tudo ou nada, o saldo do rebanho volta ao que era **na data original**, e baixa feita bloqueia com o link para o pagamento.

### F5-14 · Relatórios — programação de embarque e de abate — ✅ feita
**Depende de:** F5-07 · **Estimativa:** 5h · **Spec:** [`03_Relatorio_Programacao_de_Abate`](../relatorios/01-catalogo.md#03_relatorio_programacao_de_abatepng)

No catálogo de relatórios, com tela, CSV, XLSX e PDF. Filtros impressos.

**Pronto quando:** saem do mesmo serviço que a tela, com escopo e papel, e há teste que troca o serviço por um falso.

### F5-15 · Conferência do acerto — ✅ feita
**Depende de:** F5-12 · **Estimativa:** 6h · **Spec:** [`04_Conferencia_do_Acerto`](../relatorios/01-catalogo.md#04_conferencia_do_acertopng)

Resumo financeiro e tributário, detalhamento dos títulos e romaneio valorizado, em tela e PDF.

**Pronto quando:** os totais do PDF são os da tela, que são os de `calcular_acerto()`.

### F5-16 · Relatórios — comissão por comprador, fretes e quebra de viagem — ✅ feita
**Depende de:** F5-12 · **Estimativa:** 6h · **Spec:** [`05_Relatorio_Comissao_por_Comprador`](../relatorios/01-catalogo.md#05_relatorio_comissao_por_compradorpng)

Comissão (machos, fêmeas, cabeças, regra, valor), fretes previsto × realizado, quebra por viagem.

**Pronto quando:** a comissão do relatório é a **gravada na operação** (snapshot), não a do cadastro de hoje.

### F5-17 · Relatórios — histórico por pecuarista e programado × realizado — ✅ feita
**Depende de:** F5-12 · **Estimativa:** 6h · **Spec:** [`06_Historico_de_Abate_por_Pecuarista`](../relatorios/01-catalogo.md#06_historico_de_abate_por_pecuaristapng)

Histórico por pecuarista (cabeças, @, valor, comissão, frete, distância, R$/@, custo/@) e o relatório **programado × realizado** que a Fase 3 deixou de fora por falta de fonte.

**Pronto quando:** "—" onde falta dado, com a coluna "Por que há —".

### F5-18 · Menu, painel e pendências do ciclo — ✅ feita
**Depende de:** F5-12 · **Estimativa:** 4h

Menu "Ciclo de compra", painel com **recebido aguardando acerto**, **acerto aguardando aprovação** e **quebra acima do limite**.

**Pronto quando:** o painel responde "o que falta fechar" em uma tela, sem entrar em cada compromisso.

### F5-19 · Teste ponta a ponta e verificação em 360 px — ✅ feita
**Depende de:** F5-18 · **Estimativa:** 5h

Um compromisso do começo ao fim: aprovar → viagem → recebimento → romaneio → acerto → compras → títulos → reabrir. Todas as telas novas verificadas em **360 px e 1366 px** no navegador.

**Pronto quando:** o roteiro passa, e nenhuma tela tem rolagem horizontal no celular.

### F5-20 · Deploy da Fase 5 — ⏸️ não executada (sem VPS)
**Depende de:** F5-19 · **Estimativa:** 1h

Migrações de `commercial` e `procurement`, `seed` das classes e dos tipos, health check.

**Pronto quando:** está em produção.

---

## Fase fechada quando

- [ ] O ciclo roda do compromisso ao título sem redigitar nada
- [ ] Mudar a regra de comissão depois não altera operação aprovada
- [ ] Acerto aprovado trava o que alimenta o valor, e reabrir exige motivo e desfaz tudo ou nada
- [ ] Nenhuma alíquota ou fórmula tributária no código
- [ ] Compra direta, importadores e relatórios antigos continuam iguais
- [ ] Todas as telas verificadas em 360 px

---

**Próxima:** [Fase 6 — Avançado](fase-6-avancado.md)
