# Dashboard analítico

Análise da safra em oito abas: indicadores com comparação, gráficos, tabelas e leituras automáticas. Responde às perguntas de gestão que a planilha só respondia montando tabela dinâmica: o rebanho cresceu quanto e por quê, a que preço se comprou e se vendeu, o boi pagou o que custou criar, quem está atrasado, que lote está ganhando pouco peso.

Tela: **Dashboard**, logo abaixo de **Início** no menu (`/dashboard/` e `/dashboard/<aba>/`). Código em `apps/dashboards/bi/`; desenho em `static/js/dashboard.js` sobre o ECharts hospedado em `static/vendor/`; visual em [`docs/ux/02-design-system.md`](../ux/02-design-system.md#13-dashboard-analítico).

> **O Início responde "o que preciso fazer hoje?". O Dashboard responde "como está a operação e para onde vai?".** As pendências ficam no Início; aqui entram só as leituras que dependem de comparar números.

---

## Princípios

1. **Só lê.** Não grava, não tem modelo, não tem migração. Nenhum derivado é guardado (regra 6).
2. **O mesmo número em qualquer lugar.** Cada indicador vem do **serviço que a tela do registro já usa**; o dashboard só soma, compara e desenha. O que o dashboard mostra e a tela do lote/venda/movimentação mostram é o mesmo, e há teste para isso:

   | Indicador | Serviço |
   |---|---|
   | Saldo do rebanho | razão (`HerdLedgerEntry`, soma com sinal) — mesmo cálculo de `cartao_do_rebanho` |
   | Mortalidade | `herd.mortality.taxa_de_mortalidade` (por fazenda; consolidada pela média **ponderada** dos saldos médios) |
   | Custo de aquisição, custo/cabeça, custo/@ vivo | `purchases.services.calcular_custo_da_compra` |
   | Rendimento, valor/@, peso médio | `sales.carcass` (`indicadores_da_venda`, `agregar`) |
   | Resultado, margem/@ por lote | `sales.result.resultado_do_lote` |
   | Custo/@ dos lotes encerrados | `dashboards.selectors.cartao_da_safra` (o do Início) |
   | GMD, ganho de peso, @ produzida | `herd.weight_gain.desempenho_do_lote` |
   | Custo do lote | `livestock.selectors.financeiro_do_lote` |
   | Custo por cabeça/dia | custos ÷ `costs.allocation.cabecas_dia_por_lote` |
   | Fluxo de caixa, títulos, vencimentos | `finance.selectors` |
   | Etapa do compromisso, quebra, frete | `procurement.selectors`, `receivings.quebra_da_viagem`, `trips.frete_da_viagem` |

3. **Divisor zero devolve `None`, e `None` é "—"** (regra 3). Falta de dado é estado normal: lote com uma pesagem só não tem GMD, venda sem carcaça não tem valor/@, lote sem compra não tem resultado. O painel diz **quantos registros ficaram de fora** (faixa "Leia os números com isto em mente") e nunca estima o que não foi informado.
4. **Escopo por fazenda em toda consulta** (regra 4). Tudo nasce de `Escopo` (`bi/escopo.py`), que usa `for_user()`. Quem só tem a fazenda X não vê um animal, uma compra ou um título da fazenda Y em nenhum gráfico.
5. **Tabela equivalente em todo gráfico.** O tooltip enriquece, nunca é o único caminho: cada cartão tem o botão de tabela, e a cor nunca fala sozinha (todo estado tem ícone e texto; há o modo de texturas).

---

## Recorte e comparação

O recorte é o **topo da tela** — safra e fazenda. Não há segundo filtro para dessincronizar. A data de corte é `min(hoje, fim da safra)`.

**Comparação "no mesmo ponto":** as setas dos indicadores comparam com a **safra anterior até o mesmo número de dias**. Safra atual no dia 91 → anterior também até o dia 91. Comparar safra parcial com safra fechada faria todo indicador de fluxo parecer em queda. Sem safra anterior, ou com base zero, **não há seta** (nunca "+∞" nem "0%").

A seta traz o valor, o sentido e se é favorável ou não (cor + texto): "subiu +12,4% vs. safra anterior no mesmo ponto (favorável)". Em preço de compra a variação é **neutra** — alta de preço não é boa nem má por si: depende da mistura de categorias.

---

## As abas

| Aba | Quem vê | O que responde |
|---|---|---|
| **Visão geral** | todos (campo sem dinheiro) | Os números que importam, **o que merece atenção**, rebanho, dinheiro da safra, resultado e caixa, ciclo, fazenda a fazenda |
| **Rebanho** | todos | Saldo por fazenda, entradas e saídas por tipo, categoria × fazenda, tempo no pasto, fluxo de animais (abertura + entradas = saídas + saldo final), mortes e mortalidade, lotação |
| **Lotes** | todos (campo sem custo) | GMD de cada lote e sua distribuição, curvas de peso, custo × GMD, margem por @, painel de lotes |
| **Compras** | quem vê dinheiro | Investimento por mês, preço (@ vivo e cabeça), acumulado × safra anterior, peso × preço, vendedores, destino |
| **Vendas e resultado** | quem vê dinheiro | Receita, valor/@, rendimento (com a faixa usual), cascata do resultado, resultado por lote, custo/@ × valor/@ |
| **Custos** | quem vê dinheiro | Mês a mês por classe, centro de custo (mapa em árvore e ranking), centro × mês, custo por cabeça/dia, por fazenda |
| **Financeiro** | quem vê títulos | Fluxo de caixa (realizado × previsto), vencimentos a pagar e a receber, etapa de cada real, a quem se deve, calendário, formas de pagamento |
| **Ciclo de compra** | quem vê o ciclo | Compromissos por etapa, contratado × embarcado × recebido, quebra por viagem, frete previsto × realizado |

**Carregamento sob demanda:** a página traz a aba pedida; ao trocar de aba, o HTMX pede só o fragmento (`HX-Request`), com a URL no histórico. Sem JavaScript, as abas são links comuns.

### Decisões de definição

- **Investimento em compras** = custo de aquisição (animais + frete + comissão + impostos) das compras **confirmadas da safra**.
- **Custos da safra** = lançamentos avulsos confirmados, **sem** os que a compra gera (já estão no investimento): o mesmo critério do Início.
- **Custo por cabeça/dia** = custos do período ÷ soma das **cabeças-dia** do razão. Tira o efeito do tamanho do rebanho e permite comparar meses e safras.
- **Custo por @ e peso médio de compra** só consideram compras **com peso informado**; dividir o valor de todas pelo peso de algumas inflaria o preço.
- **Resultado dos lotes vendidos** = soma do resultado dos lotes **com venda na safra** (cada lote por inteiro, com custo pela fração já vendida), ao lado de "N de M lotes com resultado" ([#48](99-pendencias.md#48--🟢-dashboard-quem-vê-dinheiro-limiares-das-leituras-e-o-resultado-da-safra-fase-6)).
- **Posição de contas** (aging, a pagar, a receber) soma os títulos em aberto de **todas as safras**: dívida não tem safra. O **fluxo de caixa** é o da safra escolhida e não tem saldo bancário inicial: o saldo acumulado parte de zero e o painel avisa.
- **Lotação** = cabeças ÷ área de pasto cadastrada, só das fazendas que têm a área; sem ela, "—".
- **Mortalidade consolidada** = mortes ÷ soma dos saldos médios (média ponderada, não média das taxas).

---

## O que merece atenção (leituras automáticas)

Na *Visão geral*, do mais grave para o menos, no máximo oito. Cada leitura cita o valor e leva ao registro para conferir; sem nada a dizer, a lista fica vazia e o painel não inventa aviso.

Mortalidade acima do limite do sistema · lotes no prejuízo · contas a pagar vencidas · compras concentradas em um vendedor (> 40%) · preço de compra (custo/@) que oscilou mais de 10% de um mês com compra para o seguinte · custo por cabeça/dia que subiu mais de 15% (só entre meses fechados) · lote ganhando menos da metade do GMD médio · um centro com mais de 35% do custo · rendimento de carcaça que mudou mais de 1 ponto contra a safra anterior · safra no lucro.

Os limiares são **leitura, não regra**: constantes nomeadas em `bi/insights.py`, `bi/compras.py` e `bi/custos.py` ([#48](99-pendencias.md#48--🟢-dashboard-quem-vê-dinheiro-limiares-das-leituras-e-o-resultado-da-safra-fase-6)). Quem não vê dinheiro não recebe leitura de dinheiro.

---

## Permissões

O papel define **o quê**; o escopo de fazenda, **onde** (ADR 0003).

- Qualquer usuário autenticado entra no Dashboard.
- `CAMPO` vê *Visão geral* (sem KPIs de dinheiro), *Rebanho* e *Lotes* (sem custo e resultado). Compras, Vendas, Custos, Financeiro e Ciclo dão **403** — preço, custo e comissão são dado comercial (pendência #48).
- *Financeiro* exige `pode_ver_titulos`; *Ciclo*, `pode_ver_o_ciclo` (as mesmas permissões das telas de origem).
- Aba que não existe dá 404.

---

## Desempenho

Cada aba é calculada na hora (sem cache: um número defasado contradiria a tela do registro). O que é caro — desempenho, custo e resultado **por lote** — é calculado **em lote**: `desempenho_dos_lotes`, `financeiro_dos_lotes` e `resultados_dos_lotes` leem o necessário com um número fixo de consultas, e o rateio de custo lê o razão e os custos indiretos **uma vez por fazenda** (`BaseDeRateio`), não uma vez por lote e por centro. A versão de um lote (`desempenho_do_lote`, `financeiro_do_lote`, `resultado_do_lote`) é o caso de uma posição da versão em lote: tela do lote e dashboard dão o mesmo número pelo mesmo código. O que é pedido por mais de uma aba vive em `Escopo.memo` e é calculado uma vez por requisição.

**O que isso garante:** o número de consultas de uma aba **não cresce com a quantidade de lotes** (testado em `dashboards/tests/test_desempenho.py`); o tempo cresce de forma aproximadamente linear, pelo trabalho em Python de montar tabelas e gráficos. Medidas e como repetir: [operacao/02-desempenho](../operacao/02-desempenho.md). O tempo de cada aba aparece no rodapé dela.

Cache de resultado (Redis) ficou **de fora de propósito**: só entra se, com as consultas corrigidas, alguma aba ainda passar de ~1 s, e então com chave versionada e invalidação a cada escrita — nunca por tempo.

---

## Dados de demonstração

`python manage.py seed_demo_bi` (depois de `seed_demo`) cria três safras de histórico — compras, pesagens, mortes, abates, custos, títulos, baixas e compromissos em todas as etapas — **pelos serviços do sistema**, então todo número nasce pelas regras de produção. Determinístico, idempotente e **recusa `DEBUG=False`**. Nunca rodar em produção.

---

## Testes

`apps/dashboards/tests/test_dashboard_bi.py`: recorte e safra anterior no mesmo ponto · variação sem base (`None`, nunca ∞) · `ROUND_HALF_UP` na fronteira `Decimal → float` · grade que nunca deixa buraco · **cada indicador igual ao do serviço de origem** · escopo por fazenda (quem só tem a fazenda X não vê Y) · `403` por papel · fragmento HTMX · falta de dado como "—" · leituras automáticas · todo tipo de gráfico tem desenhista no JavaScript · template não calcula.
