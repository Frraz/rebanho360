# Fase 4 — Financeiro

**~35-45h · 10 tarefas**

Títulos e pagamentos. A fase onde o sistema passa a tocar dinheiro que sai de verdade — e onde o cuidado contra duplicidade deixa de ser teórico.

Pode esperar: até aqui os pagamentos continuam sendo controlados fora do sistema, e nada quebra por isso.

---

## Status (atualizado 2026-10-02)

**F4-01 a F4-09 concluídas; F4-10 não executada** (sem VPS, o mesmo bloqueio das fases anteriores). Regra completa em [regras-negocio/07-financeiro](../regras-negocio/07-financeiro.md).

**O que foi construído**

- **F4-01/02** — `Invoice` (título) e `Payment` (baixa) em `apps/finance`. Confirmar compra ou venda **gera os títulos**, idempotente por `(operação, componente)` com `UNIQUE` no banco; testado com duas confirmações simultâneas. Dado bancário vem da `BankAccount` do favorecido; na tela só `ADMIN`/`GESTOR`/`FINANCEIRO` o veem e cada consulta é auditada.
- **F4-03** — programar e aprovar com permissões distintas (`finance.approve_payment` × `finance.execute_payment`); quem aprovou não dá a baixa havendo outro usuário que possa.
- **F4-04** — baixa idempotente por `(título, documento)`, sob `select_for_update`, nunca acima do valor do título. Clique duplo provado por teste com threads.
- **F4-05** — desfazer baixa (`FINANCEIRO`/`ADMIN`, com motivo); enquanto existir, bloqueia a compra, a venda do lote e o próprio título, **com o link para o pagamento**. `bloqueios()` passou a aceitar `Bloqueio(texto, url, rótulo)`.
- **F4-06/07/08** — contas a pagar e a receber (resumo "o que vence esta semana e quanto"), fluxo de caixa projetado (realizado separado do previsto), mapa financeiro e pagamentos realizados. Os cinco também são relatórios (tela, CSV, XLSX, PDF) restritos por papel. Alerta de vencido no painel.
- **F4-09** — TOTP (RFC 6238, sem biblioteca de OTP; QR por `segno`) (hoje opcional e recomendado a todos), códigos de recuperação, limite de tentativas, anti-replay, middleware que cobre **todas** as rotas (inclusive `/admin/`).

**Decisões de modelagem**

- Título tem **dois ciclos**: o do registro (`status`, herdado de `ReversibleModel`: cancelar = excluir) e o do dinheiro (`payment_status`). Não há `CANCELADO` à parte.
- Título **a receber** (venda) usa os mesmos códigos de estado, sem programar nem aprovar; o rótulo muda ("A receber", "Recebido").
- `payment_days` em compra e venda (opcional) dá o vencimento. O histórico importado **não gera título** (`gerar_titulos=False`) — tela "Operações sem título" gera sob demanda.
- Corrigir/excluir/restaurar a operação mexe nos títulos como efeitos dela; valor ou favorecido diferentes anulam a aprovação.
- `Purchase.bloqueios()` olha também os pagamentos da **venda do lote** que a compra criou — o caso do documento.

**Pendências abertas pela fase:** [#16](../regras-negocio/99-pendencias-resolvidas.md) (prazo/parcelas), [#17](../regras-negocio/99-pendencias-resolvidas.md) (a quem vão frete/comissão/impostos; quem aprova e paga), [#18](../regras-negocio/99-pendencias-resolvidas.md) (o histórico), [#19](../regras-negocio/99-pendencias-resolvidas.md) (2FA opcional; troca de celular). Todas respondidas ou com padrão reversível.

**O que não foi feito, e por quê**

- **F4-10 (deploy):** falta o VPS. Há passos novos — **reconstruir a imagem** (`segno`), migrações `accounts` 0002, `audit` 0004, `purchases` 0002, `sales` 0002, `finance` 0001 — e a conferência do 2FA abaixo.
- Sem parcelamento em títulos separados, sem conciliação bancária, sem remessa/arquivo de pagamento: nada disso foi pedido ([#16](../regras-negocio/99-pendencias-resolvidas.md)).

**2FA no deploy (F4-10):** desde 03/10/2026 o segundo fator é **opcional** (não há mais `TWO_FACTOR_ENFORCED`). Rode `docker compose exec web python manage.py conferir_segundo_fator` para ver a **hora do servidor** (confira `timedatectl`: NTP ativo) e quem já usa; recomende a cada um ativar na página *Conta* e guardar os códigos de recuperação. Se alguém perder celular e códigos: `manage.py resetar_segundo_fator <usuário>` (ou outro `ADMIN`, pela tela de usuários).

**Testes:** 782 na suíte completa, todos verdes contra Postgres real (119 do financeiro, 50 de contas — inclui os vetores da RFC 6238); `ruff`/`black` limpos. 8 telas novas verificadas em **360 px e 1366 px** com navegador real, sem rolagem horizontal. Para rodar a suíte inteira use `--create-db`: os testes de concorrência (`transaction=True`) esvaziam as tabelas e um banco reaproveitado fica sujo.

---

### F4-01 · `finance` — Título — ✅ feita
**Depende de:** F2-05, F3-03 · **Estimativa:** 4-5h · **Spec:** [modelo-dados/01](../modelo-dados/01-entidades.md)

`Invoice` com compra/venda de origem, favorecido, documento, emissão, vencimento, valor, dados bancários, status. Estados `A_PAGAR → PROGRAMADO → APROVADO → PAGO`, mais `PARCIAL`.

Dados bancários vêm do `BankAccount` do parceiro — nunca redigitados.

**Pronto quando:** criar título a partir de uma compra confirmada não exige digitar nada que já exista.

### F4-02 · Geração de títulos a partir da operação — ✅ feita
**Depende de:** F4-01 · **Estimativa:** 3-4h · **Spec:** [fluxos/02](../fluxos/02-maquinas-de-estado.md#títulos-financeiros-fase-4)

Confirmar compra ou venda gera as obrigações. **Idempotente:** chave por operação, de modo que confirmar duas vezes não gera dois títulos.

**Pronto quando:** teste de confirmação concorrente gera **um** título, não dois.

### F4-03 · Programar e aprovar — ✅ feita
**Depende de:** F4-01 · **Estimativa:** 3-4h · **Spec:** [fluxos/02](../fluxos/02-maquinas-de-estado.md)

Separação deliberada: **quem aprova não é quem executa**. Permissões distintas (`finance.approve_payment` e `finance.execute_payment`), e o sistema recusa que o mesmo usuário faça as duas no mesmo título quando houver mais de um usuário financeiro.

**Pronto quando:** aprovar exige permissão própria, e a tentativa de pagar sem aprovação é recusada.

### F4-04 · Baixa idempotente — ✅ feita
**Depende de:** F4-03 · **Estimativa:** 4-5h · **Spec:** [seguranca/01](../seguranca/01-seguranca.md#proteção-contra-mau-uso)

Chave de idempotência por `(título, documento de pagamento)`. `select_for_update` na abertura. Baixa parcial somando até o total, nunca ultrapassando.

**Pronto quando:** clique duplo não paga duas vezes, e teste de concorrência prova.

### F4-05 · Desfazer baixa — ✅ feita
**Depende de:** F4-04, F0-10 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md#o-que-bloqueia)

A **única exceção** ao "tudo é editável": desfazer no sistema não desfaz a transferência no banco. Operação de `FINANCEIRO` ou `ADMIN`, com motivo, e enquanto a baixa existir ela **bloqueia a exclusão de tudo a montante** — a compra, a venda, o movimento.

A mensagem de bloqueio precisa dizer o caminho: *"desfaça antes a baixa do pagamento"*, com link.

**Pronto quando:** excluir uma compra cuja venda já foi paga é bloqueado, e o link leva direto ao pagamento.

### F4-06 · Contas a pagar — ✅ feita
**Depende de:** F4-03 · **Estimativa:** 3-4h · **Spec:** [relatorios/01](../relatorios/01-catalogo.md#fase-4--financeiro)

Lista por vencimento, com filtro por favorecido, status e período. Alerta de vencido no dashboard.

**Pronto quando:** dá para responder "o que vence esta semana e quanto" em uma tela.

### F4-07 · Fluxo de caixa projetado — ✅ feita
**Depende de:** F4-06 · **Estimativa:** 4-5h

Entradas previstas de venda contra saídas previstas de título, por período. Substitui a aba `DASH CAIXA`, que está vazia na planilha — nunca chegou a ser usada.

**Pronto quando:** mostra o saldo projetado por mês da safra, com o realizado separado do previsto.

### F4-08 · Mapa financeiro — ✅ feita
**Depende de:** F4-06 · **Estimativa:** 3-4h

Consolidado por favorecido, por tipo e por safra. Pago, a pagar, vencido.

**Pronto quando:** reproduz em uma tela o que hoje exige cruzar três abas.

### F4-09 · 2FA (opcional, recomendado) — ✅ feita
**Depende de:** F4-04 · **Estimativa:** 4-5h · **Spec:** [seguranca/01](../seguranca/01-seguranca.md#autenticação)

TOTP com códigos de recuperação. Nasceu obrigatório para `ADMIN` e `FINANCEIRO`; em 03/10/2026 passou a opcional e recomendado a todos. Adiado até aqui de propósito: antes do módulo financeiro, o risco não justificava o atrito.

**Pronto quando:** quem ativa o segundo fator não entra sem ele, e tem como se recuperar perdendo o celular.

### F4-10 · Deploy da Fase 4 — ⏸️ não executada (sem VPS)
**Depende de:** F4-09 · **Estimativa:** 1h

`deploy.sh`, migração, health check. Conferir o relógio do servidor (`conferir_segundo_fator`): sem a hora certa, os códigos do 2FA não batem.

**Pronto quando:** está em produção e quem ativou o segundo fator entra com ele.

> **Não executada** — ver o status acima. `manage.py conferir_segundo_fator` foi criado para este passo.

---

## Fase fechada quando

- [x] Programar, aprovar e baixar funciona sem duplicar
- [x] Clique duplo não paga duas vezes — provado por teste de concorrência
- [x] Quem aprova não é quem executa
- [x] Baixa existente bloqueia exclusão a montante, com o caminho explicado
- [x] Dados bancários nunca são redigitados
- [x] 2FA opcional (recomendado a todos)
- [x] Nenhum dado bancário aparece em log

---

## Daqui em diante

Com a Fase 4 o sistema está completo para a operação atual. As duas fases seguintes são **condicionais** — só existem se a operação pedir:

- **[Fase 5](fase-5-ciclo-frigorifico.md)** — ciclo de compra de frigorífico. Grande, e com pré-requisito que não se negocia.
- **[Fase 6](fase-6-avancado.md)** — brinco individual, reprodução, indicadores zootécnicos.

Nada aqui deve ser construído por antecipação.
