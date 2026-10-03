# Roadmap

**Fatias verticais funcionais.** Cada fase deixa uma parte real do sistema em uso, não uma camada técnica pronta.

Não construir 80 telas antes de qualquer uma servir.

---

## As fases

| | Etapa | Esforço | Tarefas | Entrega |
|---|---|---|---|---|
| **0** | [Fundação e produção](fase-0-fundacao.md) | 55-76h | 18 | Sistema **no ar no VPS**, com login, auditoria e backup restaurado |
| **1** | [Cadastros e rebanho](fase-1-cadastros-e-rebanho.md) | 55-74h | 16 | O núcleo: saldo que fecha, lançamento pelo celular |
| **2** | [Custos, compras e importação](fase-2-custos-compras-importacao.md) | 57-77h | 15 | O histórico importado e conferido |
| **★** | [**Marco — Virada**](marco-virada.md) | 15-25h + 30 dias | 8 | **A planilha é aposentada** |
| **3** | [Vendas, abates e indicadores](fase-3-vendas-e-indicadores.md) | 45-58h | 13 | O ciclo fecha: comprar → engordar → abater → resultado |
| **4** | [Financeiro](fase-4-financeiro.md) | 32-41h | 10 | Títulos e pagamentos sem duplicar — *F4-01 a F4-09 feitas; deploy pendente* |
| 5 | [Ciclo de compra](fase-5-ciclo-frigorifico.md) | ~125h | 20 | Compromisso → viagem → recebimento → romaneio → acerto, sem tocar o núcleo — *escopo principal desde 2026-10-02; F5-01 a F5-19 feitas; deploy pendente. Lacunas contra o documento funcional: [matriz](../fluxos/04-alinhamento-ao-doc-funcional.md)* |
| 6 | [Avançado](fase-6-avancado.md) | aberto | — | *Condicional* |

| Até onde | Horas |
|---|---|
| **Até aposentar a planilha** (0+1+2+Virada) | **~180-250** |
| **Até o sistema completo** (+3+4) | **~260-350** |

> **Dashboard analítico (03/10/2026), sem tarefa numerada.** Pedido de Warley depois da Fase 5: tela de análise com KPIs, gráficos e leituras automáticas, logo abaixo de *Início*. Só leitura (nenhum modelo novo), sobre os serviços que já existem. Regra em [11-dashboard-analitico](../regras-negocio/11-dashboard-analitico.md); pendência [#48](../regras-negocio/99-pendencias.md#48--🟢-dashboard-quem-vê-dinheiro-limiares-das-leituras-e-o-resultado-da-safra-fase-6). Deploy pendente, como as demais fases.

> **Intermezzo — redesenho da interface (01/10/2026), entre a Fase 3 e a Fase 4.** Só frontend, sem tarefa nova de negócio: shell, componentes, todas as telas e design system. Ver [Fase 3](fase-3-vendas-e-indicadores.md#pós-fase-redesenho-da-interface-2026-10-01), [design system](../ux/02-design-system.md) e [ADR 0007](../arquitetura/adr/0007-design-system-proprio-sobre-tailwind.md). Toda tela das Fases 4 em diante nasce dos componentes dele.

**100 tarefas** até a Fase 5, cada uma com dependência, estimativa, link para a regra e critério de pronto. **Situação:** Fases 0 a 5 com código pronto; faltam só as tarefas de deploy (F0-17/18, F1-16, F2-15, F3-13, F4-10, F5-20), que dependem de um servidor real.

Sem datas, por decisão — a dedicação varia. A conversão para calendário é sua.

E mais um documento, que vale para tudo: **[Definition of Done](definition-of-done.md)**.

---

## Duas decisões que moldam o roadmap

**Produção já na Fase 0.** O sistema sobe vazio — login, health check, backup — e **cada fase seguinte vai para produção**. Deploy vira rotina de cinco minutos em vez de evento arriscado na semana 10. Problema de infraestrutura aparece na primeira semana, quando custa pouco.

**Trinta dias de paralelo antes de aposentar a planilha.** Custa retrabalho temporário e compra a única coisa que importa: descobrir um erro grave enquanto ainda há para onde voltar. A Fase 3 é desenvolvida durante esse tempo.

---

## Como executar

O desenvolvimento é feito com Claude Code. O roadmap foi escrito para isso.

**Uma tarefa por sessão.** Abra dizendo o ID e o link da spec: *"Faça a F1-07. A regra está em docs/regras-negocio/01-rebanho-movimentacoes.md."* O agente lê a especificação que já existe em vez de reinventá-la.

**A ordem importa.** Cada tarefa declara de qual depende. Furar a ordem gera retrabalho — a F0-06 antes da F0-05 não compila, e a F2-12 antes da pendência #2 importa dado errado.

**O agente não decide regra de negócio.** Se a spec não cobre o caso, isso é uma pendência: vai para [99-pendencias](../regras-negocio/99-pendencias.md), não para o código. Regra inventada em silêncio é o pior defeito possível neste projeto.

**Feche pelo "Pronto quando", não pela sensação.** Toda tarefa tem um critério verificável, quase sempre um teste. Se o critério não foi atingido, a tarefa não acabou — mesmo que a tela apareça.

**Deploy no fim de cada fase**, não no fim do projeto.

### Formato das tarefas

```
### FN-NN · Título curto da tarefa
Depende de: FN-NN · Estimativa: Xh · Spec: link para o documento da regra

[o que construir, em duas ou três linhas]

Pronto quando: [critério verificável, de preferência um teste]
```

---

## Pendências como item de roadmap

As [45 pendências](../regras-negocio/99-pendencias.md) não são nota de rodapé. Cada uma tem a fase em que precisa ser respondida:

| Antes de | Resolver |
|---|---|
| Carga histórica (Fase 2) | **#5** 🔴 — São Francisco e São Francisco II são a mesma fazenda? Adiada em 2026-10-01 com padrão reversível — não bloqueia mais a Fase 1, só a importação real |
| ~~Fase 1~~ | ~~**#1** evolução de categoria~~ — ✅ confirmada em 2026-10-01 (2 linhas) |
| Importador da Fase 2 | **#2** 🟡 os −140 da aba `GERAL` — adiada em 2026-10-01 com padrão reversível (transferência sempre interna) |
| Fase 2 | **#3** o que é "PARCERIA" · **#6** quem é "ONODA" · **#10** compra de 126 cabeças fora da aba · **#11** 30 custos com ano errado |
| Fase 3 | **#7** rendimento de carcaça: informado ou calculado? *(construída como calculado; segue aberta)* · **#12** pesos de saída divergem entre as abas · **#13** abate sem carcaça confirma? · **#14** margem por @ e lote parcial · **#15** rendimento de entrada e mortalidade normal |
| Fase 4 | **#16** prazo e parcelamento · **#17** a quem vão frete/comissão/impostos, e quem aprova e paga · **#18** o histórico gera título? · **#19** 2FA: adotar ou não, troca de celular *(#19 respondida: opcional para todos; as demais construídas com padrão reversível)* |
| Fase 5 | **#4** base da comissão · **#8** faixas de preço *(a fase foi construída sem as respostas, com padrão reversível)* · **#20** faixa por linha · **#21** 🔴 tributos, com o contador, **antes de usar o acerto** · **#22** rateio · **#23** quebra · **#24** quando o gado entra no saldo · **#25** quem aprova · **#26** base do preço |
| Antes de gerar contrato de verdade | **#27** dados bancários no contrato: o documento funcional pede, o sistema omite |
| Qualquer momento | **#9** quem pode excluir registro confirmado *(só permissão)* |

**#5** e **#2** mexem na carga histórica. Resolver depois significa reprocessar todo o razão.

---

## Começar

A primeira sessão é a **[F0-01](fase-0-fundacao.md#f0-01--projeto-django-e-estrutura-de-apps)** — projeto Django e estrutura de apps.

Antes dela, vale ler, nesta ordem: [visão geral](../00-visao-geral.md), [arquitetura](../arquitetura/01-arquitetura.md) e [rebanho por movimentações](../regras-negocio/01-rebanho-movimentacoes.md). Uns 20 minutos, e evitam retrabalho de semanas.
