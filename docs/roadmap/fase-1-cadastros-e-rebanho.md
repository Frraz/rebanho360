# Fase 1 — Cadastros e rebanho

**~55-75h · 16 tarefas · a partir daqui o sistema tem valor**

O núcleo. Da F1-06 à F1-09 está a decisão mais importante do projeto: o saldo do rebanho como razão de partidas dobradas ([ADR 0002](../arquitetura/adr/0002-rebanho-como-razao-de-movimentacoes.md)).

> **Pendência [#5](../regras-negocio/99-pendencias-resolvidas.md) decidida em 2026-10-01:** sem resposta ainda sobre São Francisco/São Francisco II, seguindo com padrão reversível (duas fazendas distintas, como já estava no `seed_demo`). Não bloqueia mais a F1-02 — mas continua bloqueando a carga histórica real da Fase 2.

---

## Status (atualizado 2026-10-01)

**F1-01 a F1-15 concluídas e testadas contra Postgres real** (ver
[fase-0](fase-0-fundacao.md#atualização-2026-10-01-início-da-fase-1) —
o pacote `pgserver` resolveu a falta de Docker nesta sessão). **156
testes passando** (0 pulados fora de Postgres). **F1-16 não executada**
— depende do mesmo VPS que falta para F0-17/F0-18.

- `ruff`/`black` limpos; verificação visual real em 360×800 com
  Playwright nas telas novas (posição, lançamento, lote, pesagem,
  movimentações, conciliação) — sem rolagem horizontal em nenhuma.
- **Quatro bugs reais encontrados e corrigidos no caminho**, nenhum
  pelo código desta fase propriamente — todos em mecanismos herdados
  da F0 que esta foi a primeira sessão a exercitar contra Postgres
  de verdade ou navegador real:
  1. `[x-cloak]` não tinha regra CSS (`display:none`) — o atributo
     sozinho não escondia nada antes do Alpine inicializar. Afetava o
     menu mobile da F0-12 também, silenciosamente. Corrigido em
     `static/css/input.css`.
  2. `<input type="date">` com locale pt-br: o `DateInput` padrão
     renderiza `value="18/09/2025"`, formato que o HTML5 date input
     não reconhece — o campo aparenta preenchido no HTML mas o
     navegador mostra vazio. Afetava também `SeasonForm` (F1-01) e
     `LotForm` (F1-05). Corrigido forçando `format="%Y-%m-%d"` nos
     três.
  3. `Weighing` (F1-14) ficou sem `objects = ScopedManager()` — só o
     `SCOPE_FARM_FIELD` foi declarado. A lista de pesagens quebrava
     com 500 para qualquer usuário. Só apareceu ao testar no
     navegador; nenhum teste automatizado chamava `.for_user()`
     direto no manager. Corrigido, com teste de regressão.
  4. (Fase 0, achado nesta sessão) trigger de imutabilidade do
     `AuditEvent` tinha `%` literal num `RAISE EXCEPTION`, que o
     psycopg interpreta como placeholder — `migrate` falhava sempre
     contra Postgres real. Ver nota na Fase 0.
- **Decisão de modelagem registrada:** a invariante 6
  (`regras-negocio/01#invariantes` — soma de deslocamento = 0) não é
  expressável como `CheckConstraint` de linha única; implementada como
  *constraint trigger* `DEFERRABLE INITIALLY DEFERRED` em
  `herd/migrations/0002_herd_invariantes_banco.py`, que avalia no
  commit, depois que as duas linhas da transação já existem. Testada
  inclusive via SQL cru. A invariante das 2/1 linhas (itens 3-4) é uma
  `CHECK` de verdade, também via SQL direto na migração (Django não
  expressa `IS DISTINCT FROM` de tuplas via `Q()`).
- **F1-07 vai além da spec num ponto:** `AJUSTE_INVENTARIO` ganhou
  permissão restrita (`ADMIN`/`GESTOR`) além do motivo obrigatório —
  a spec já dizia "permissão restrita" mas não detalhava quem; decisão
  de uma linha em `apps/herd/permissions.py`, documentada no código.
- **Campo adiado, não pendência de negócio:** `Lot.origin_purchase` e
  `HerdMovement.origin_purchase/origin_sale` (FK para `Purchase`/`Sale`)
  não puderam ser criados — esses modelos só nascem na Fase 2/3. Mesma
  estratégia da FK preguiçosa de `Farm` na F0-06; nota deixada em
  [fase-2](fase-2-custos-compras-importacao.md#f2-04--purchases--modelo-e-crud)
  para não esquecer.
- **Ambiente de desenvolvimento desta sessão:** Postgres 16.2 real via
  `pgserver` (sem Docker/root disponíveis), `seed_demo` populado,
  `DATABASE_URL` exportado por variável de ambiente — não por `.env`
  (decouple prioriza `.env` sobre o default de `dj_database_url`,
  o que quebrava 3 testes de `test_settings_prod.py`; ver nota no
  arquivo se isso se repetir).

---

## Cadastros

### ✅ F1-01 · `organizations` — Empresa, Unidade, Safra
**Depende de:** F0-15 · **Estimativa:** 3-4h · **Spec:** [modelo-dados/01](../modelo-dados/01-entidades.md#espinha-organizacional)

CRUD das três. Safra com constraint impedindo sobreposição na mesma empresa, e `is_current`. O seletor de safra no topo passa a funcionar de verdade.

**Pronto quando:** criar safra 2026/2027 sobreposta à 2025/2026 é recusado pelo banco, não só pelo formulário.

> **Feito:** sem `btree_gist` disponível (extensão não vem no Postgres
> embutido usado nesta sessão), a não-sobreposição é um *trigger*
> `BEFORE INSERT OR UPDATE`, não um `ExclusionConstraint` — mesmo
> espírito do ADR 0006. `is_current` único por empresa é um
> `UniqueConstraint` condicional de verdade. Contexto fixo: safra
> selecionável no topo, persistida na sessão; `encerrar`/`reabrir`
> com auditoria (`reabrir` restrito a `ADMIN`). 14 testes.

### ✅ F1-02 · `properties` — Fazenda e Pasto
**Depende de:** F1-01 · **Estimativa:** 3-4h · **Spec:** [modelo-dados/01](../modelo-dados/01-entidades.md#espinha-organizacional)

`Farm` e `Paddock` com os tipos da aba `TABELA DE ÁREAS` (pastagem, silagem, benfeitoria, reserva/APP, arrendamento). A FK preguiçosa da F0-06 passa a resolver.

**Pronto quando:** o `ScopedManager` filtra fazenda de verdade, e o teste da F0-06 roda contra o modelo real.

> **Feito:** `Paddock` ganhou `objects = ScopedManager()` (só tinha o
> `SCOPE_FARM_FIELD` desde a F0-15/F1-02). Seletor de fazenda real no
> contexto fixo, filtrando pela sessão. CRUD de fazenda restrito a
> `ADMIN`/`GESTOR`; lista de pasto é escopada para todos. 8 testes.

### ✅ F1-03 · `partners` — Parceiro multi-papel
**Depende de:** F1-01 · **Estimativa:** 4-5h · **Spec:** [modelo-dados/01](../modelo-dados/01-entidades.md#pessoas-e-acesso)

`Partner`, `PartnerRole` (unique em `partner+role`), `BankAccount`. Autocomplete via HTMX mostrando nome, documento e cidade — nunca select gigante ([ux/01](../ux/01-navegacao-e-ui.md#autocomplete-nunca-select-gigante)).

Alteração de dado bancário é evento de auditoria de severidade alta.

**Pronto quando:** o mesmo parceiro exerce `PRODUTOR` e `COMPRADOR` sem cadastro duplicado, e mudar a conta bancária aparece no console de auditoria.

> **Feito:** papéis via checkboxes no próprio formulário do parceiro —
> sincroniza `PartnerRole` (cria/remove) sem tela separada. Busca
> HTMX por nome/documento/cidade devolvendo fragmento (`_resultado_busca.html`),
> reutilizável por outros formulários mais adiante. Conta bancária
> exige motivo só na edição (criação não); toda alteração audita com
> `reason`. 10 testes.

### ✅ F1-04 · `livestock` — Categoria e Raça
**Depende de:** F1-01 · **Estimativa:** 2-3h · **Spec:** [regras-negocio/01](../regras-negocio/01-rebanho-movimentacoes.md#categorias-animais)

As 11 categorias reais semeadas, com `sex`, `age_order` e `display_order`. Raça com Nelore.

`age_order` alimenta a **sugestão** de evolução — sugestão, nunca automação.

**Pronto quando:** as 11 aparecem na ordem da planilha, e a categoria seguinte de "Machos Desm. até 12m" é sugerida como "Machos 13 a 24 meses".

> **Feito:** as 11 já vinham do `seed_demo` (F0-15); esta tarefa
> acrescentou CRUD e `sugerir_proxima_categoria()` (mesmo sexo, próxima
> `age_order`) + endpoint JSON para a sugestão. Nunca atravessa sexo;
> categoria de topo (Touros) e sem ordem etária (Tropa) não sugerem
> nada. 8 testes.

### ✅ F1-05 · `livestock` — Lote
**Depende de:** F1-02, F1-04 · **Estimativa:** 3-4h · **Spec:** [modelo-dados/01](../modelo-dados/01-entidades.md#rebanho)

`Lot` com código, fazenda, origem, datas, centro de custo e safra. Quantidade, peso e categoria **não são campos** — saem do razão.

**Pronto quando:** não existe campo de quantidade no modelo. Se existir, o desenho está errado.

> **Feito:** código `LT-{fazenda}-{sequência}` gerado por serviço,
> sequência por fazenda (não global) — bate com `LT-SFR-004`/`LT-SFR-014`
> da planilha. `origin_purchase` adiado para a Fase 2 (nota na seção
> Status). 6 testes, incluindo um que lê `Lot._meta.get_fields()` e
> confirma a ausência de `head_count`/`quantity`/`weight`/`category`.

---

## Rebanho — o núcleo

### ✅ F1-06 · `HerdMovement` e `HerdLedgerEntry`
**Depende de:** F1-05 · **Estimativa:** 5-6h · **Spec:** [regras-negocio/01](../regras-negocio/01-rebanho-movimentacoes.md) · [ADR 0002](../arquitetura/adr/0002-rebanho-como-razao-de-movimentacoes.md)

Os dois modelos, os 11 tipos de movimento, e as constraints de banco: quantidade positiva, linha do razão diferente de zero, tipo de 2 linhas exigindo origem **e** destino distintos, tipo de 1 linha exigindo um só.

`HerdLedgerEntry` com os dois tempos — `date` (o fato, alimenta saldo) e `created_at` (o registro, alimenta auditoria) — mais `reverses_entry`.

Índices em `(farm, category, date)` e `(lot, date)`.

**Pronto quando:** tentar gravar uma transferência sem destino falha **no banco**, não só na validação Python.

> **Feito, e mais rígido que a spec num ponto:** a constraint de
> 2-linhas/1-linha é uma `CHECK` real (via SQL direto na migração — ver
> nota em Status). `HerdLedgerEntry` ganhou imutabilidade de três
> camadas, igual ao `AuditEvent` do ADR 0006 — `save()`/`delete()`
> recusam em Python, manager bloqueia `update()`/`delete()` em massa, e
> um trigger de banco recusa mesmo via SQL direto. Nenhuma dessas três
> camadas estava pedida explicitamente na spec para o razão (só para o
> `AuditEvent`); decisão de estender o mesmo padrão, já que o razão é
> tão ou mais crítico.

### ✅ F1-07 · Serviço de movimentação com partidas dobradas
**Depende de:** F1-06 · **Estimativa:** 4-6h · **Spec:** [regras-negocio/01](../regras-negocio/01-rebanho-movimentacoes.md#partidas-dobradas)

`registrar_movimento()`: tipo simples gera 1 linha, tipo de deslocamento (transferência, evolução, reclassificação) gera **2 linhas na mesma transação**, negativa na origem e positiva no destino.

Implementa `ReversibleAction` da F0-10. Desfazer escreve linhas de compensação com **a data do fato original**, nunca apaga linha.

**Pronto quando:** a soma das linhas de qualquer transferência é exatamente zero, e o teste prova que o `-140` da aba `GERAL` é impossível de representar.

> **Feito:** `registrar_movimento()` cobre todos os 11 tipos (incluindo
> `AJUSTE_INVENTARIO` com permissão restrita — ver Status) e reaproveita
> `confirmar()`/`editar()`/`excluir()`/`restaurar()` da F0-10 por inteiro
> — `HerdMovement` é um `ReversibleModel` normal, só com
> `aplicar_efeitos`/`desfazer_efeitos` escrevendo linhas no razão. Teste
> dedicado prova que uma transferência sem destino falha no banco com o
> cenário exato do `-140`. 19 testes.

### ✅ F1-08 · `HerdBalanceService`
**Depende de:** F1-07 · **Estimativa:** 4-5h · **Spec:** [regras-negocio/01](../regras-negocio/01-rebanho-movimentacoes.md#saldo)

Saldo por fazenda, lote, categoria e data. `SUM` sobre `date`, nunca campo gravado.

**Pronto quando:** o saldo em 30/09 permanece correto depois de uma correção feita em 14/10 sobre um fato de setembro — porque a compensação leva a data do fato.

> **Feito e testado de ponta a ponta:** `saldo()` em
> `apps/herd/services.py`, assinatura igual à da spec (`farm`/`lot`/
> `category`/`season`/`until`). O teste da correção retroativa cria um
> `SALDO_INICIAL` de 126 em 18/09, edita para 120 via `reversible.editar()`,
> e confirma que `saldo(..., until=30/09)` já mostra 120 — com as 3
> linhas (`+126`, `-126` compensação, `+120`) todas datadas de 18/09.

### ✅ F1-09 · Invariante de saldo não negativo
**Depende de:** F1-08 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/01](../regras-negocio/01-rebanho-movimentacoes.md#invariantes)

Verificação **dentro** da transação, com `select_for_update` na posição afetada. Mensagem específica: *"Saldo insuficiente: há 12 cabeças de Machos 13 a 24 meses no Baixão, foram informadas 20."*

**Pronto quando:** teste de concorrência com duas saídas simultâneas da mesma posição deixa uma passar e barra a outra. Fora da transação as duas passariam — é exatamente esse o teste.

> **Feito e confirmado contra Postgres real** (não pulado — ver Status
> da Fase 0): `select_for_update()` trava todas as linhas de
> `(farm, lot, category)` antes de somar; duas threads vendendo da
> mesma posição ao mesmo tempo, uma recebe `BusinessError` com a
> mensagem exata do exemplo da spec, a outra passa. A sequência do
> código do movimento (`gerar_codigo_movimento`) também trava a safra —
> sem isso, duas inserções concorrentes geravam o mesmo código antes de
> qualquer uma comitar (bug real visto no primeiro teste de concorrência).

---

## Telas

### ✅ F1-10 · Posição do rebanho
**Depende de:** F1-08 · **Estimativa:** 4-6h · **Spec:** [fluxos/01](../fluxos/01-fluxo-fazenda-a-pasto.md)

Substitui o quadro-resumo das 5 abas de fazenda. Categorias nas linhas, entradas/saídas/posição nas colunas, filtro por fazenda, safra e data. Consolidado de todas as fazendas — o que a aba `GERAL` tentava ser.

**Pronto quando:** o consolidado **nunca** mostra número negativo, porque não há como produzi-lo.

> **Feito:** tabela categoria × entradas/saídas/posição, filtro por
> fazenda (ou consolidado) e data; escopada por usuário (`for_user`).
> Relatório denso: `overflow-x: auto` conscientemente, não rolagem de
> página (exceção documentada no `ux/01`). 3 testes (de
> `test_screens.py`, que soma 7 com a F1-11 — ver abaixo), incluindo que
> o consolidado soma certo e que o escopo filtra.

### ✅ F1-11 · Lançamento de movimentação
**Depende de:** F1-09 · **Estimativa:** 5-7h · **Spec:** [ux/01](../ux/01-navegacao-e-ui.md#formulário-de-campo)

A tela mais usada do sistema, e a que decide se ele é adotado. Desenhada **para o celular primeiro**: uma coluna, botão de 44 px, teclado numérico, ação fixa no rodapé, rascunho em `localStorage` para sinal caindo não apagar o preenchido.

Motivo obrigatório em `MORTE` e `AJUSTE_INVENTARIO`.

**Pronto quando:** dá para lançar uma morte em 360 px, em pé, com a rede oscilando, sem perder o que foi digitado.

> **Feito e verificado em navegador real a 360×800** (Playwright,
> não suposição): um formulário só, com Alpine.js mostrando/escondendo
> origem e destino conforme o tipo (`x-show`, sem recarregar a página).
> Fazenda → lote é *cascading select* via HTMX. Rascunho salvo em
> `localStorage` a cada alteração, restaurado ao reabrir a tela, limpo
> só depois de um envio bem-sucedido (`?ok=1`). Achou e corrigiu dois
> bugs reais — ver Status (`x-cloak` sem CSS, `<input type="date">`
> com formato pt-br). 4 testes (mesmo arquivo da F1-10, 7 no total).

### ✅ F1-12 · Editar, excluir e restaurar movimentação
**Depende de:** F1-11 · **Estimativa:** 4-5h · **Spec:** [regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md)

Usa os serviços genéricos da F0-10. Tela de análise de impacto com a lista do que será desfeito — nunca um "Tem certeza?" genérico. Motivo obrigatório. Registro editado mostra "Editada (v3)" com histórico.

Movimento gerado por compra ou venda não se edita direto: a tela mostra a origem e leva até ela.

**Pronto quando:** excluir um movimento cujos animais já saíram é bloqueado, e a mensagem diz **o que desfazer primeiro**.

> **Feito, reaproveitando a F0-10 por inteiro:** editar pede um motivo
> de correção **diferente** do `reason` do próprio movimento (ex.:
> motivo da morte vs. motivo da correção) — dois campos, dois
> propósitos. Excluir que deixaria alguma posição negativa é bloqueado
> automaticamente: `_criar_linha()` roda a mesma checagem de saldo
> tanto ao aplicar quanto ao desfazer efeitos, sem código extra.
> "Editada (v2)" aparece na lista e no detalhe. `dependentes()` fica
> vazio por ora — não há ainda nada que dependa de um movimento
> (Purchase/Sale, que gerariam o bloqueio "edite a compra, não o
> movimento", são Fase 2/3). 9 testes.

### ✅ F1-13 · Tela do lote
**Depende de:** F1-08 · **Estimativa:** 4-6h · **Spec:** [fluxos/01](../fluxos/01-fluxo-fazenda-a-pasto.md#a-tela-central-o-lote)

O centro do sistema, como a compra é no do frigorífico. Posição, desempenho, financeiro, linha do tempo, e os **avisos de dado faltando** — "@ produzida indisponível: falta peso de carcaça" em vez de zero.

**Pronto quando:** indicador sem dado aparece como "—" com o motivo ao lado, nunca como `0`.

> **Feito, com Financeiro inteiro em "—" por desenho:** aquisição e
> custo dependem de `Purchase`/`CostEntry` (Fase 2) — mostrar "—" aqui
> não é um placeholder tosco, é a aplicação literal da regra
> "indicador sem dado é '—', nunca 0". Desempenho usa pesagens reais
> (peso médio, GMD via `calcular_gmd`); `@` produzida fica "—" sempre
> na Fase 1 (depende de peso de carcaça na venda, Fase 3) — exatamente
> como o mockup do `fluxos/01` já mostrava. Avisos dinâmicos: sem
> pesagem, pesagem antiga (>90 dias). `WeighingAnimal` (brinco) existe
> no modelo, mas sem tela própria ainda — a F3-07 é quem vai
> popular isso de verdade. 6 testes.

### ✅ F1-14 · Pesagem
**Depende de:** F1-05 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/01](../regras-negocio/01-rebanho-movimentacoes.md#pesagem)

`Weighing` (não altera saldo) e `WeighingAnimal` com `ear_tag` — a tabela que vai receber os brincos da planilha na F3-07, ainda **sem entidade `Animal`** ([ADR 0004](../arquitetura/adr/0004-lote-agregado-antes-de-brinco.md)).

**Pronto quando:** registrar pesagem não muda o saldo do lote, e o peso médio é calculado, não digitado.

> **Bug real encontrado e corrigido:** `Weighing` ficou sem
> `objects = ScopedManager()` — só o `SCOPE_FARM_FIELD` foi declarado,
> então a lista de pesagens quebrava com 500 (`'Manager' object has no
> attribute 'for_user'`) para qualquer usuário. Nenhum teste chamava
> `.for_user()` direto no manager; só apareceu ao verificar a tela no
> navegador. Corrigido, com teste de regressão (ver Status). 7 testes.

### ✅ F1-15 · Conciliação de transferências
**Depende de:** F1-08 · **Estimativa:** 3-4h · **Spec:** [relatorios/01](../relatorios/01-catalogo.md#fase-1--rebanho)

O relatório que a planilha nunca teve: toda saída sem entrada correspondente. Numa operação saudável vem vazio — e é isso que prova que o modelo está fechando.

Alimenta o painel de pendências.

**Pronto quando:** vem vazio com os dados de teste, e listaria os 140 se eles fossem importados como estão na planilha.

> **Feito, com o teste mais revelador da fase:** o trigger da F1-06
> torna o desbalanceamento impossível por qualquer caminho normal —
> então "vem vazio" é garantido por construção, não por sorte. Para
> provar a segunda parte do critério, o teste desliga o trigger só
> dentro da própria transação (`ALTER TABLE ... DISABLE TRIGGER`, DDL
> transacional — o rollback do pytest desfaz sozinho), insere a linha
> órfã de -140 sem contrapartida, e confirma que o relatório encontra
> exatamente esse movimento. Alimenta o painel de pendências (ainda
> sem tela de pendências consolidada — fica para quando a tela
> inicial ganhar conteúdo de verdade). 3 testes.

### ❌ F1-16 · Deploy da Fase 1
**Depende de:** F1-15 · **Estimativa:** 1h

`deploy.sh`. Migração, conferência do health check, teste de fumaça no celular.

**Pronto quando:** está no ar e alguém consegue lançar uma movimentação em produção.

> **Não executada — mesmo motivo da F0-17/F0-18: falta um VPS real.**
> O pipeline de deploy (`deploy/deploy.sh`, `docker-compose.prod.yml`)
> já criado na Fase 0 não muda nada para a Fase 1 — é só mais
> `apps`/migrações no mesmo projeto Django. O que dá para confirmar
> sem VPS já foi confirmado nesta sessão: `manage.py migrate` aplica
> todas as 7 migrações novas (`organizations`, `properties`,
> `partners`, `livestock`, `herd`) limpo em Postgres 16 real, e a
> suíte inteira (156 testes) passa. Falta: rodar `deploy.sh` de
> verdade e lançar uma movimentação em produção pelo celular.

---

## Fase fechada quando

- [x] Registra compra, morte, transferência e evolução
- [x] O saldo bate, e o consolidado nunca fica negativo
- [x] Transferência sem contrapartida é **impossível de representar**
- [x] Correção de fato antigo conserta o saldo **daquela data**
- [x] Duas saídas simultâneas não furam o saldo — confirmado contra Postgres real
- [x] O campo lança do celular, em 360 px, sem perder o preenchido — verificado com Playwright
- [x] Excluir com dependente mostra o impacto e diz o caminho
- [x] A conciliação de transferências vem vazia
- [ ] Está no ar em produção — **falta VPS** (F1-16, mesmo bloqueio da F0-17/F0-18)

> **[#1](../regras-negocio/99-pendencias-resolvidas.md) confirmada em 2026-10-01** (evolução = 2 linhas). **[#2](../regras-negocio/99-pendencias-resolvidas.md)** (os −140 da aba `GERAL`) segue aberta por decisão explícita — padrão reversível (transferência sempre interna), a resolver antes do importador da Fase 2.

**Próxima:** [Fase 2 — Custos, compras e importação](fase-2-custos-compras-importacao.md)
