# Fase 3 — Vendas, abates e indicadores

**~45-60h · 13 tarefas · aqui o ciclo fecha**

Comprar, engordar, abater, ver o resultado. Desenvolvida **durante os 30 dias de paralelo** do [marco da virada](marco-virada.md).

---

## Status (atualizado 2026-10-02)

**F3-01 a F3-12 concluídas; F3-13 não executada** (sem VPS, o mesmo bloqueio da F0-17/F0-18/F1-16/F2-15). **610 testes passando** contra Postgres real (eram 369), contra a **planilha real** do produtor (não contra fixture inventada), `ruff`/`black` limpos. 16 telas verificadas em **360 px e 1280 px** com navegador real: nenhuma com rolagem horizontal, nenhum alvo de toque abaixo de 44 px, nenhum erro de JS.

**O que a planilha real mostrou** — a spec não previa nenhum destes (detalhes em [99-pendencias](../regras-negocio/99-pendencias.md) e [migracao/01](../migracao/01-planilhas-e-importacao.md)):

1. **A aba `SÃO FRANCISCO` já contém os 3 abates** (84 + 189 + 81 = 354) e o importador de movimentações da Fase 2 já os importa como saída. Importar `VENDAS` por cima **debitaria as 354 cabeças duas vezes**. A venda agora **adota** a saída que já existe (vínculo com decisão do usuário) em vez de debitar de novo; o saldo de São Francisco não muda ao importar as vendas — está num teste. Também reforça a [#5](../regras-negocio/99-pendencias-resolvidas.md): "São Francisco II" de `VENDAS` parece ser a mesma fazenda.
2. **O peso vivo de saída diverge entre as abas** — `VENDAS`, aba da fazenda e `PESAGENS` dão pesos diferentes para os mesmos abates (abril: 45.000 × 47.878 kg, rendimento 56,79% × 53,37%). Nada é corrigido em silêncio: vira aviso. [#12](../regras-negocio/99-pendencias-resolvidas.md).
3. **`PESAGENS E CONFERENCIA` tem 9 blocos, não 8** (4.058 animais pesados). `SB` é *sem brinco* (591 + 18 animais), não um brinco repetido. 20 brincos se repetem com pesos diferentes no mesmo dia — todos importados, nenhum descartado.
4. **A compra de 126 cabeças de 27/04/2026 não tem pesagem de entrada**, enquanto as outras três do mesmo dia (268 cabeças) têm — indício a favor da aba da fazenda, no [#10](../regras-negocio/99-pendencias-resolvidas.md). Só indício.
5. **A `COPERFRIGU` criada pela importação de movimentações não tem papel nenhum**, e a venda exige Frigorífico ou Comprador. O importador de vendas acrescenta o papel **por escolha do usuário**, nunca em silêncio.
6. **`WeasyPrint 62.3` quebrava com a `pydyf` instalada (0.12.1)** — o PDF não gerava. Fixada `pydyf==0.10.0` em `requirements/base.txt`. Teria quebrado em produção.

**Decisões de modelagem:**

- `Sale` é um `ReversibleModel` cujos efeitos são outros registros, como a compra: o movimento de saída e o encerramento do lote. Editar = desfazer + reaplicar na mesma transação; excluir devolve as cabeças **na data original** (linhas de compensação) e reabre o lote. `HerdMovement.origin_sale` criado; movimento gerado por venda não se edita direto.
- Constraints no banco: carcaça só em `ABATE`, carcaça < peso vivo, quantidade, peso e valor > 0.
- **Os derivados vivem em três serviços, e cada tela, relatório e o painel chamam o mesmo:** `CarcassService` (`apps/sales/carcass.py`), `SaleResultService` (`apps/sales/result.py`) e `WeightGainService` (`apps/herd/weight_gain.py`). Há testes que **trocam o serviço por um falso** e provam que o relatório mostra o valor do serviço — nenhum reimplementa uma conta.
- **Peso de entrada nunca é estimado.** Sem duas pesagens em datas diferentes, GMD é `None` e a tela diz por quê. A @ produzida pede um rendimento de entrada que ninguém informou — sem ele é "—"; com ele, vem marcada como **estimativa** ([#15](../regras-negocio/99-pendencias-resolvidas.md)).
- Resultado do lote: custo/@ sobre a @ **vendida** (a conta fecha: `resultado = margem/@ × @`), lote aberto = resultado **parcial**, lote sem custo de aquisição = sem resultado ([#14](../regras-negocio/99-pendencias.md)).
- Abate **confirma sem carcaça** (as cabeças já saíram) e vira pendência no painel ([#13](../regras-negocio/99-pendencias.md)).
- `safe_div(int, int)` devolvia `float` — o oposto da regra nº 2. Agora devolve sempre `Decimal` (achado ao escrever o teste do resultado parcial).
- Painel: "Custos" **exclui** o que a compra gera (senão a aquisição aparecia duas vezes: em "Comprado" e em "Custos"); "Custo/@" é o dos lotes encerrados na safra, vindo do mesmo serviço da tela do lote.
- `Relatorio` ganhou `filtros` estruturados. O CSV, o XLSX e o PDF os levam **dentro do arquivo**. O XLSX grava números como números (com formato de moeda e %), não texto.
- PDF: modelo `GeneratedDocument` (`document_id`, `template_version`, quem gerou, quando, hash, filtros e parâmetros), arquivo guardado, servido só por view autenticada (404 para quem não gerou). Relatório pesado vai para o Celery; a tela de documento atualiza sozinha por HTMX.

**Para rodar de verdade:** custos → compras → movimentações → **vendas** → **pesagens**, depois `python manage.py conferir_importacao`, que agora tem 16 verificações. Ele continua acusando só as 2 divergências **reais** (saldo 2.080 × 1.954 e as 2 transferências órfãs) — nenhuma criada pelas vendas.

**O que não foi feito, e por quê:**

- **F3-13 (deploy):** falta o VPS. Migrações novas: `sales` 0001, `herd` 0005, `imports` 0002, `documents` 0001. Há um passo novo no build: `pydyf` fixada — **a imagem precisa ser reconstruída**.
- **"Programado × realizado"** (F3-10): não existe fonte do "programado" — a programação de abate é da Fase 5. Construir o relatório agora seria inventar um modelo de planejamento. Fica para quando houver o dado.
- **Gráfico no painel:** o roadmap diz "só se mudar decisão", e nenhum mudou. Não foi feito.
- **Rateio `POR_ARROBA_PRODUZIDA`** continua recusado (a mensagem diz isso): depende de um rendimento de entrada que ninguém definiu ([#15](../regras-negocio/99-pendencias-resolvidas.md)).
- **Mortalidade "acima do normal":** o limite de 2% por safra e fazenda é palpite do desenvolvimento (`MORTALIDADE_LIMITE_PERCENTUAL`), registrado no [#15](../regras-negocio/99-pendencias-resolvidas.md).

---

## Vendas e abate

### ✅ F3-01 · `sales` — modelo e CRUD
**Depende de:** F1-05 · **Estimativa:** 4-5h · **Spec:** [regras-negocio/04](../regras-negocio/04-venda-e-abate.md)

`Sale` serve para abate **e** venda de animal vivo — a diferença está no campo `type`, não em duas tabelas. Código `VD-2025/26-0003`. Carcaça obrigatória só em `ABATE`.

Nenhum derivado é campo: peso médio, carcaça média, rendimento, valor/cabeça e valor/@ ficam fora do modelo.

**Pronto quando:** o modelo não tem nenhum dos sete campos derivados que a planilha grava.

### ✅ F3-02 · `CarcassService`
**Depende de:** F3-01 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/04](../regras-negocio/04-venda-e-abate.md#derivados--carcassservice)

Os seis cálculos, com `safe_div` em todos.

O teste é dado: o abate de ago/2025 — 84 cabeças, 43.540 kg vivo, 22.350,40 kg carcaça, R$ 401.502,68 — tem que produzir 518,33 / 266,08 / 51,33% / 1.490,03@ / 4.779,79 / 269,46. Os seis já foram conferidos contra a planilha.

**Pronto quando:** os seis batem casa a casa, e venda sem carcaça devolve `None` nos indicadores de carcaça.

### ✅ F3-03 · Confirmação de venda
**Depende de:** F3-02, F1-09 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/04](../regras-negocio/04-venda-e-abate.md#confirmação)

Verificação de saldo **dentro da transação, com a posição travada**, antes de gerar o movimento de saída. Fora da transação, duas vendas simultâneas furam o saldo.

Alerta (não bloqueio) para rendimento fora de 40%–65%: valor atípico deve ser conferido por gente, não recusado pela máquina.

**Pronto quando:** teste de concorrência com duas vendas da mesma posição deixa uma passar e barra a outra com mensagem específica.

### ✅ F3-04 · Editar e excluir venda
**Depende de:** F3-03, F0-10 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md)

`desfazer_efeitos()` devolve as cabeças ao lote. Bloqueio quando o lote já foi usado em algo posterior, ou quando o pagamento da venda já foi baixado (Fase 4).

**Pronto quando:** excluir venda reabre o lote encerrado e restaura o saldo na data original.

### ✅ F3-05 · `SaleResultService`
**Depende de:** F3-02, F2-03 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/05](../regras-negocio/05-indicadores-e-calculos.md#resultado)

`receita − aquisição − custos diretos − custos rateados`. Margem por @ — o indicador que responde à pergunta central: *o boi pagou o que custou criar?*

Com o lote a saldo zero, encerra e congela o resultado.

**Pronto quando:** um lote completo do histórico importado mostra resultado e margem/@ coerentes.

---

## Desempenho

### ✅ F3-06 · `WeightGainService`
**Depende de:** F1-14 · **Estimativa:** 4-5h · **Spec:** [regras-negocio/05](../regras-negocio/05-indicadores-e-calculos.md#rebanho)

GMD e @ produzida de pesagens sucessivas do mesmo lote. Sem pesagem inicial, GMD é `None` — **não se estima peso de entrada**. Quando o rendimento de entrada for estimado, a tela marca como estimativa.

**Pronto quando:** lote sem pesagem inicial mostra "—" com o motivo, não um GMD inventado.

### ✅ F3-07 · Importador de PESAGENS E CONFERENCIA
**Depende de:** F2-09, F1-14 · **Estimativa:** 5-6h · **Spec:** [migracao/01](../migracao/01-planilhas-e-importacao.md)

O desempilhamento. Oito blocos paralelos de `(DATA, BRINCO, PESO, MOVIMENTAÇÃO)` nas colunas `B-E`, `G-J`, `L-O`, `Q-T`, `V-Y`, `AA-AD`, `AF-AI`, `AK-AN` viram uma tabela só.

Agrupa por `(data, motivo)` criando `Weighing`, e cada linha vira `WeighingAnimal(ear_tag, weight_kg)` — **sem entidade `Animal`** ([ADR 0004](../arquitetura/adr/0004-lote-agregado-antes-de-brinco.md)). Motivos incluem `VACINA COFERENCIA`, grafado assim na planilha.

**Pronto quando:** os oito blocos viraram uma tabela, nenhum brinco se perdeu, e nenhuma entidade `Animal` foi criada.

### ✅ F3-08 · Importador de VENDAS
**Depende de:** F2-09, F3-02 · **Estimativa:** 3-4h · **Spec:** [migracao/01](../migracao/01-planilhas-e-importacao.md)

3 abates, 354 cabeças, R$ 2.298.586,23. Descartar os sete derivados.

Depois de importar, `CarcassService` recalcula e **compara com o que estava na planilha**. Divergência vira aviso — foi assim que a pendência [#7](../regras-negocio/99-pendencias.md) apareceu.

**Pronto quando:** os 3 abates estão importados e o relatório de divergência mostra o caso do `SOMA RENDIMENTO`.

---

## Visualização

### ✅ F3-09 · Dashboard
**Depende de:** F3-05 · **Estimativa:** 5-7h · **Spec:** [ux/01](../ux/01-navegacao-e-ui.md#tela-inicial)

**Pendências em primeiro lugar**, gráfico depois — e só se mudar decisão.

Regras de pendência: transferência sem contrapartida · custo sem centro · lote sem pesagem há 90 dias · venda sem carcaça · lote a saldo zero ainda aberto · mortalidade acima do normal · rendimento fora da faixa.

**Pronto quando:** abrir o sistema responde "o que preciso fazer hoje?", e indicador sem dado aparece como "—".

### ✅ F3-10 · Relatórios de desempenho e resultado *(4 de 5)*
**Depende de:** F3-05, F3-06 · **Estimativa:** 4-5h · **Spec:** [relatorios/01](../relatorios/01-catalogo.md#fase-3--vendas-e-desempenho)

Vendas e abates · desempenho do lote (GMD, @ produzida, dias, rendimento) · resultado do lote · programado × realizado · pesagens.

Referência de layout: o relatório legado `06_Historico_de_Abate_por_Pecuarista`, cujo bloco final (`R$ @`, `Custo @`) é quase o que precisamos.

**Pronto quando:** todos chamam os serviços de cálculo — nenhum reimplementa uma conta.

> **Entregues 4 dos 5:** vendas e abates (com "por mês" e "por comprador", que substituem o `DASH VENDAS`), desempenho do lote, resultado do lote e pesagens. **Falta "Programado × realizado"**: não existe fonte do "programado" — a programação de abate é da Fase 5. Construir agora seria inventar um modelo de planejamento.

### ✅ F3-11 · Exportação CSV e XLSX
**Depende de:** F3-10 · **Estimativa:** 3-4h · **Spec:** [relatorios/01](../relatorios/01-catalogo.md#formatos)

Não subestimar: hoje tudo é planilha, e tirar essa saída é tirar autonomia de quem analisa por fora.

**Pronto quando:** qualquer relatório exporta com os filtros aplicados preservados no arquivo.

### ✅ F3-12 · PDF com WeasyPrint
**Depende de:** F3-10 · **Estimativa:** 4-5h · **Spec:** [relatorios/01](../relatorios/01-catalogo.md#documentos-gerados)

Cabeçalho com sistema, relatório, emissão, **filtros aplicados** e paginação. Sem os filtros impressos, papel na mesa não diz a que se refere — é a falha mais comum, e os legados acertam nela.

Registrar `document_id`, `template_version`, quem gerou, quando e hash. Relatório pesado em Celery.

**Pronto quando:** o PDF sai com os filtros no cabeçalho e fica registrado para reprodução futura.

### ❌ F3-13 · Deploy da Fase 3
**Depende de:** F3-12 · **Estimativa:** 1h

`deploy.sh`, migração, health check, teste de fumaça no celular.

**Pronto quando:** está em produção e o dashboard carrega com os dados reais já importados.

> **Não executada — falta o VPS.** Ao subir: **reconstruir a imagem** (`pydyf` fixada), `migrate` (`sales` 0001, `herd` 0005, `imports` 0002, `documents` 0001), conferir `/health/`, abrir o painel e o resultado de um lote no celular, gerar um PDF, e só então importar vendas e pesagens.

---

## Fase fechada quando

- [x] Os 6 números do abate de ago/2025 batem casa a casa — no serviço **e** no importador contra a planilha real
- [x] Venda maior que o saldo é recusada, inclusive sob concorrência
- [x] O ciclo fecha: comprar → engordar → abater → resultado do lote
- [x] Os blocos de pesagem viraram uma tabela, sem perder brinco *(eram 9, não 8: 4.058 animais, todos importados)*
- [x] O dashboard mostra pendências antes de gráfico
- [x] Indicador sem dado é "—" com motivo, nunca `0`
- [x] Relatório e dashboard mostram o mesmo número para o mesmo indicador
- [x] PDF sai com os filtros no cabeçalho
- [ ] Está no ar em produção — **falta VPS** (F3-13)

> **Resolver nesta fase:** **[#7](../regras-negocio/99-pendencias.md)** — rendimento de carcaça é informado pelo frigorífico ou calculado? E o que mede o `SOMA RENDIMENTO`? *(Construída com o padrão reversível — calculado; o `SOMA RENDIMENTO` aparece no relatório de divergência da importação. A pergunta segue aberta.)*
>
> **Nasceram desta fase:** [#12](../regras-negocio/99-pendencias-resolvidas.md) (pesos de saída divergem entre as abas), [#13](../regras-negocio/99-pendencias.md) (abate sem carcaça confirma?), [#14](../regras-negocio/99-pendencias.md) (margem por @: denominador e lote parcial), [#15](../regras-negocio/99-pendencias-resolvidas.md) (rendimento de entrada e mortalidade normal).

## Pós-fase: redesenho da interface (2026-10-01)

Feito com a Fase 3 fechada e antes de começar a Fase 4, para que as telas novas já nasçam do design final. **Só frontend** — regras, rotas, modelos, permissões, auditoria e contratos ficaram como estavam.

**Entregue**

- Shell novo: menu lateral escuro com ícones (fixo ≥ 1024 px, gaveta abaixo), barra superior com Empresa · Safra · Fazenda sempre visíveis (painel inferior no celular — antes o contexto não aparecia no celular), menu do usuário, avisos redesenhados, login em duas colunas.
- Design system em `static/css/input.css` + tokens em `tailwind.config.js` (paleta do logotipo), partials de template (`_field`, `_form_page`, `_empty`, `_pagination`, `_errors`), ícones em sprite SVG, fontes IBM Plex locais. Documentado em [design system](../ux/02-design-system.md); decisão em [ADR 0007](../arquitetura/adr/0007-design-system-proprio-sobre-tailwind.md).
- As ~70 telas (listas como tabela/cartão, detalhes, formulários em seções, exclusão com análise de impacto, relatórios, documentos, importação, auditoria) refeitas sobre os mesmos componentes. Sem emoji.
- `./deploy/local.sh` e os scripts de `deploy/` atualizados (ver [infra](../arquitetura/02-infra-e-deploy.md#deploy)): healthcheck compatível com `SECURE_SSL_REDIRECT`, backup que acha o volume certo, rollback por imagem etiquetada, publicação dos estáticos para o Nginx, `restore-check.sql`.

**Achados do processo**

- Em produção o Django não serve `/static/`: sem o passo de publicar estáticos e o bloco no Nginx, o sistema abre sem estilo.
- O healthcheck antigo falharia em produção (400 por Host inválido) e faria o deploy dar rollback sempre.
- A paginação da lista de custos gerava `??page=2`; corrigida.
- O `output.css` não é versionado: o que o desenvolvedor vê depende de ter compilado o CSS.

**Verificação:** suíte de testes (exceto a bateria de importação contra a planilha real), `ruff` e `black` limpos; todas as rotas do menu e dos formulários em 360×800 e 1366×768 no Chromium, sem rolagem horizontal e sem erro de console. **Não verificado:** aparelho real; geração do PDF depois da troca de cores do template; viewport de tablet além da captura.

**Ainda pendente:** páginas 403/404/500 próprias (hoje as do Django); `healthcheck` do container `web` no `docker-compose.prod.yml` (ver [infra](../arquitetura/02-infra-e-deploy.md#pendências-conhecidas)); os itens de [ux/01](../ux/01-navegacao-e-ui.md#implementação-do-redesign-01102026) que a especificação previa e ainda não existem (combobox com busca, máscara de dinheiro, filtros em drawer).

**Próxima:** [Fase 4 — Financeiro](fase-4-financeiro.md)
