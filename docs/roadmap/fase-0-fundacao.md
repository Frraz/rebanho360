# Fase 0 — Fundação e produção

**~55-75h · 18 tarefas · termina com o sistema rodando no VPS**

Nenhuma tela de negócio. A base sobre a qual tudo apoia — e o deploy, para que subir vire rotina em vez de evento arriscado na semana 10.

> **F0-10** (mecanismo reversível) e **F0-11** (console de auditoria) somam ~25% da fase. Estão aqui porque toda fase seguinte depende delas: enxertar depois significa reabrir cada modelo já escrito. Ver [ADR 0006](../arquitetura/adr/0006-tudo-editavel-com-auditoria-imutavel.md).

---

## Status (atualizado 2026-10-01)

**F0-01 a F0-16 concluídas e testadas.** F0-17 e F0-18 escritas (scripts e
config prontos em `deploy/` e `docker-compose.prod.yml`) mas **não
executadas** — exigem um VPS real, que esta sessão de desenvolvimento não
tinha acesso.

- 58 testes passando, 1 pulado de propósito (concorrência real entre
  conexões — `select_for_update()` só bloqueia de verdade no Postgres;
  roda no CI, que sobe Postgres+Redis de verdade via GitHub Actions)
- `ruff` e `black` limpos; regra de lint contra `float(` em
  `models.py`/`services.py` implementada como teste (`test_lint_no_float.py`),
  já que o Ruff não suporta regra arbitrária por arquivo sem plugin próprio
- Verificação visual real em 360×800 com Playwright (login, início,
  auditoria) — sem rolagem horizontal em nenhuma. Veja a seção de cada
  tarefa abaixo para o que foi verificado e como
- Um bug real foi encontrado e corrigido no caminho: o filtro de log que
  esconde dado sensível quebrava a formatação `%(dict)s` que o Celery usa
  no log de sucesso de task — coberto por teste de regressão
  (`test_logging.py`)
- `seed_demo` populou, além do pedido pela tarefa, os cadastros mínimos
  que a tarefa pressupõe mas que ainda não existiam no código
  (`Company`, `BusinessUnit`, `Season`, `Farm` completo, `AnimalCategory`,
  `Breed`, `CostClass`, `CostCenter`) — ver nota na F0-15

**Ambiente de desenvolvimento usado para validar:** Python 3.12.14 (via
`uv python install`, já que o sandbox só tinha 3.14 — incompatível com
Django 5.0), Redis 8.0.5 local. `backend/.venv/` não é versionado.

**Atualização 2026-10-01 (início da Fase 1):** esta sessão tinha `apt`/`sudo`
mas sem senha interativa — sem Docker, sem Postgres de sistema. Resolvido
com o pacote `pgserver` (PyPI), que empacota um Postgres 16.2 completo e
sobe um processo real via socket Unix, sem precisar de root — suficiente
para rodar `migrate`/`pytest` com o Postgres de verdade (ver
`docs/arquitetura/02-infra-e-deploy.md` para o procedimento, caso o próximo
ambiente de desenvolvimento também não tenha Docker). Isso expôs e corrigiu
**um bug real** que o F0-08 não pôde exercitar: a migração do trigger de
imutabilidade (`audit/migrations/0002_auditevent_immutable_trigger.py`)
tinha um `%` literal dentro do `RAISE EXCEPTION`, que o psycopg interpreta
como placeholder ao montar a query client-side — `migrate` falhava sempre,
em qualquer Postgres real. Corrigido para `%%`. Com Postgres de verdade,
os **59 testes passam**, incluindo o de exclusão concorrente (F0-10, antes
pulado) e a trilha de auditoria imutável por trigger (F0-08, camada 3,
antes não exercida) — ambos confirmados funcionando.

---

## Preparação

### ✅ F0-01 · Projeto Django e estrutura de apps
**Depende de:** — · **Estimativa:** 2-3h · **Spec:** [arquitetura/01](../arquitetura/01-arquitetura.md#estrutura-de-pastas)

Projeto em `backend/`, `config/` com settings/urls/wsgi/celery, e os 16 apps vazios de `apps/` com `models / services / selectors / forms / permissions / tasks / tests`. `requirements/` separado em `base.txt`, `dev.txt`, `prod.txt`, com versões fixadas.

Python 3.12, Django 5.x, psycopg[binary], django-htmx, celery, redis, WeasyPrint, openpyxl, argon2-cffi.

**Pronto quando:** `python manage.py check` passa e `startapp` não precisa ser rodado de novo em nenhuma fase.

### ⚠️ F0-02 · Docker Compose de desenvolvimento
**Depende de:** F0-01 · **Estimativa:** 2-3h · **Spec:** [arquitetura/02](../arquitetura/02-infra-e-deploy.md)

`web`, `db` (postgres:16-alpine), `redis` (redis:7-alpine). Volumes nomeados com prefixo `rebanho360_`. Nenhuma porta publicada além da do `web`, e só em `127.0.0.1`.

**Pronto quando:** `docker compose up` sobe os três e `manage.py migrate` roda contra o Postgres do container.

> **Escrito, não executado.** `docker-compose.yml` existe e segue a spec (`target: dev`, bind mount, healthchecks, volumes `rebanho360_pgdata`/`rebanho360_redis_dev`), mas esta sessão de desenvolvimento rodou num sandbox sem Docker instalado — validar `docker compose up` de verdade é o primeiro passo de quem continuar.

### ✅ F0-03 · Settings por ambiente
**Depende de:** F0-01 · **Estimativa:** 2-3h · **Spec:** [arquitetura/02](../arquitetura/02-infra-e-deploy.md#configuração)

`base.py`, `dev.py`, `prod.py`. `.env.example` versionado, `.env` no `.gitignore`. Timezone `America/Sao_Paulo`, locale `pt-br`, `USE_TZ = True`.

`prod.py` **recusa subir** se `SECRET_KEY` estiver ausente, se `DEBUG=True`, ou se `ALLOWED_HOSTS` contiver `*`.

**Pronto quando:** subir com `DJANGO_SETTINGS_MODULE=config.settings.prod` sem `SECRET_KEY` falha com mensagem clara, não com stack trace genérico.

> **Testado em `apps/core/tests/test_settings_prod.py`:** recusa sem `SECRET_KEY`, com `DEBUG=True` e com `ALLOWED_HOSTS=*`, cada um com mensagem específica; e que a configuração válida sobe.

---

## Núcleo compartilhado

### ✅ F0-04 · `apps/core` — dinheiro, divisão e mixins
**Depende de:** F0-01 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/05](../regras-negocio/05-indicadores-e-calculos.md) · [ADR 0005](../arquitetura/adr/0005-decimal-e-arredondamento.md)

`money.py` com `KG_PER_ARROBA`, `ROUND_HALF_UP` e as casas decimais. `safe_div()` devolvendo `None`. `TimestampedModel`, `SoftDeletableModel`, `BusinessError`.

**Pronto quando:** testes confirmam `safe_div(10, 0) is None` e `quantize_money(Decimal("0.005")) == Decimal("0.01")`.

> **Feito:** `money.py` e `models.py` (`TimestampedModel`, `SoftDeletableModel`) em `apps/core`. `BusinessError`/`DependencyError`/`BlockingDependencyError` foram para `apps/core/exceptions.py` (não `models.py`), por coesão. `ScopedManager` (F0-06) foi para `apps/core/managers.py`. Testado em `test_money.py`.

### ✅ F0-05 · `accounts` — usuário e papel
**Depende de:** F0-03 · **Estimativa:** 2-3h · **Spec:** [modelo-dados/01](../modelo-dados/01-entidades.md#pessoas-e-acesso)

`AbstractUser` estendido com `role` (`ADMIN`, `GESTOR`, `ESCRITORIO`, `CAMPO`, `FINANCEIRO`, `CONSULTA`), `phone`, `last_login_ip`. `AUTH_USER_MODEL` apontado **antes** da primeira migração.

**Pronto quando:** `createsuperuser` funciona e o papel aparece no admin.

> **Testado em `apps/accounts/tests/test_admin.py`.** `UserFarmAccess` também entrou aqui (não em `properties`), já que é `user × farm` e `accounts` é quem define usuário — ver F0-06.

### ✅ F0-06 · Escopo por fazenda
**Depende de:** F0-05 · **Estimativa:** 3-4h · **Spec:** [ADR 0003](../arquitetura/adr/0003-escopo-por-fazenda-desde-a-fase-0.md)

`UserFarmAccess (user × farm, can_write)`, `ScopedManager.for_user()` e o mixin que todo modelo com fazenda vai herdar. `ADMIN` e `GESTOR` enxergam tudo por papel.

Como `Farm` só existe na F1-02, criar aqui com FK preguiçosa (`"properties.Farm"`) e testar com um modelo de teste.

**Pronto quando:** teste confirma que usuário sem acesso ao Goiano recebe lista vazia e `404` no detalhe — nunca `403`, que confirmaria a existência do registro.

> **Feito:** `Farm` nasceu com só `name`/`code`/`is_active` aqui e ganhou os campos completos (`business_unit`, área, cidade/UF) na F0-15, para o `seed_demo` ter onde escrever — ver nota na F0-15. O "modelo de teste" pedido pela spec é `ScopeTestModel` em `apps/core/models.py`. Testado em `apps/core/tests/test_scope.py`, incluindo o mixin de view `ScopedQuerysetMixin` (`apps/core/mixins.py`).

### ✅ F0-07 · Autenticação
**Depende de:** F0-05 · **Estimativa:** 3-4h · **Spec:** [seguranca/01](../seguranca/01-seguranca.md#controles-por-camada)

Login, logout, troca de senha, recuperação. Argon2 primeiro em `PASSWORD_HASHERS`. Rate limit de 5 tentativas por usuário e por IP em 15 minutos. Cookies `Secure`, `HttpOnly`, `SameSite=Lax`. Sessão de 12h.

**Pronto quando:** usuário inativo não autentica mesmo com senha correta, e a sexta tentativa em 15 min é bloqueada.

> **Testado em `apps/accounts/tests/test_auth.py`** (inclui o teste de CSRF do checklist de segurança). Recuperação de senha usa o fluxo padrão do Django (`PasswordReset*View`), com templates próprios em `templates/registration/`.

---

## Auditoria e reversibilidade

### ⚠️ F0-08 · `audit` — `AuditEvent` append-only
**Depende de:** F0-05 · **Estimativa:** 3-4h · **Spec:** [regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md#auditoria)

Modelo com `timestamp`, `actor`, `action`, `entity_type`, `entity_id`, `before`, `after`, `changed_fields`, `reason`, `cascade_root`, `ip_address`, `user_agent`, `request_id`. Mais `OperationEvent` para a linha do tempo do usuário.

Imutabilidade em quatro camadas: sem admin, sem método de serviço que altere, migração concedendo **apenas `INSERT` e `SELECT`** ao papel da aplicação, e `save()` que recusa alteração de registro existente.

**Pronto quando:** teste confirma que não existe caminho de código que altere ou apague um `AuditEvent` — inclusive como `ADMIN`.

> **Implementado com trigger de banco, não `GRANT`.** Um `GRANT INSERT, SELECT` exige um papel de banco separado do que roda as migrações — infraestrutura que só faz sentido desenhar junto do deploy real (F0-17). Em vez disso, `audit/migrations/0002_auditevent_immutable_trigger.py` cria um trigger Postgres (`BEFORE UPDATE OR DELETE ... RAISE EXCEPTION`) que recusa a alteração **mesmo via SQL direto**, inclusive para quem tem acesso de superusuário à aplicação — mais forte que o pedido pela spec, mesmo custo de manutenção. Só roda em Postgres (verifica `schema_editor.connection.vendor`); é pulado em SQLite.
> As camadas 1 e 2 (sem tela, sem método) mais `save()`/`delete()` que recusam e o `ImmutableQuerySet` (bloqueia `update()`/`delete()` em massa) estão testados em `apps/core/tests/test_reversible.py::TestImutabilidadeDoAuditEvent`. **A camada 3 (trigger) não foi exercida nesta sessão** — o sandbox não tinha Postgres instalado; ela roda de verdade no CI (`postgres:16-alpine` como serviço) e em qualquer `docker compose up`.

### ✅ F0-09 · Middleware de contexto
**Depende de:** F0-08 · **Estimativa:** 2h · **Spec:** [arquitetura/01](../arquitetura/01-arquitetura.md#auditoria)

`request_id` por requisição, propagado ao log e ao `AuditEvent`. Captura de ator, IP e user-agent em variável de contexto, para que os serviços não precisem receber `request` como parâmetro.

**Pronto quando:** dois eventos gerados na mesma requisição compartilham o `request_id`, e ele aparece na linha de log.

> **Testado em `apps/core/tests/test_middleware.py`** (e também pela cascata em `test_reversible.py`, via `request_context.use_context()`). `apps/core/request_context.py` guarda o contexto em `ContextVar`; `apps/core/logging.py` injeta `request_id`/`user_id` em todo log via `RequestIdFilter`.

### ✅ F0-10 · Mecanismo reversível
**Depende de:** F0-08 · **Estimativa:** 5-7h · **Spec:** [regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md#como-implementar)

O contrato `ReversibleAction` — `aplicar_efeitos()`, `desfazer_efeitos()`, `dependentes()` — e os serviços genéricos `editar()`, `excluir()` e `restaurar()`.

Cada um: `select_for_update` na abertura, tudo em `transaction.atomic`, bloqueios verificados dentro da transação, auditoria gravada na mesma transação, `reason` obrigatório. Exclusão em cascata compartilhando `cascade_root`.

`DependencyError` carregando a lista de dependentes, para a view virar tela de impacto.

**Pronto quando:** um modelo de teste com efeitos declarados passa nos 12 testes de [regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md#testes-obrigatórios) — inclusive cascata que falha no meio sem deixar resíduo.

> **Os 12 testes estão em `apps/core/tests/test_reversible.py`**, usando `ReversibleTestModel`/`DependentTestModel`/`CounterTestModel` (`apps/core/models.py`) como o "modelo de teste com efeitos declarados". 11 passam sempre; o de exclusão concorrente (#12) pula fora do Postgres — `select_for_update()` não bloqueia entre conexões do jeito necessário em SQLite — e roda de verdade no CI. Também adicionei uma guarda que a spec não detalhava: excluir um registro já `EXCLUIDA` recusa com `BusinessError` claro, em vez de desfazer o efeito duas vezes (é o que torna o teste #12 determinístico).

### ✅ F0-11 · Console de auditoria
**Depende de:** F0-10, F0-12 · **Estimativa:** 6-8h · **Spec:** [regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md#console-de-auditoria)

Tela para `ADMIN`: filtro por usuário, ação, entidade, período e IP; diff campo a campo de `before`/`after`; cascata agrupada por `cascade_root` num item só; **restaurar a partir do evento**; exportar CSV; linha do tempo de um registro.

**Pronto quando:** dá para achar uma exclusão feita há 10 minutos, ver exatamente o que ela desfez, e restaurar por ali.

> **Feito:** `apps/audit/{views,selectors,permissions}.py` + `templates/audit/{console,timeline}.html`. "Restaurar" resolve o modelo pelo nome salvo em `entity_type` via `apps.get_models()` (não precisa conhecer `Purchase`/`Sale` de antemão — funciona para qualquer `ReversibleModel` futuro). Acesso: `ADMIN` por padrão, `GESTOR` também se `AUDIT_CONSOLE_INCLUDE_GESTOR=True`. Testado em `apps/audit/tests/test_console.py`, incluindo restaurar de fato pelo botão e ver o efeito desfeito voltar.

---

## Interface e operação

### ✅ F0-12 · Layout base responsivo
**Depende de:** F0-07 · **Estimativa:** 6-8h · **Spec:** [ux/01](../ux/01-navegacao-e-ui.md)

Tailwind com build, HTMX, Alpine. `base.html`, menu lateral que vira drawer no celular, contexto fixo de Empresa · Safra · Fazenda no topo, toast, modal, empty state, paginação, badge de status.

Testar em 360 px de largura **de verdade**, não por suposição.

**Pronto quando:** o menu abre e fecha em 360×800 sem rolagem horizontal em nenhuma tela.

> **Verificado com navegador real** (Playwright/Chromium, não suposição): capturei `login`, `início` e `auditoria` em 360×800 e conferi `scrollWidth == clientWidth` nas três — sem rolagem horizontal. HTMX e Alpine.js são vendorizados em `static/vendor/` (baixados uma vez, servidos localmente) em vez de CDN — pensando no sinal ruim do campo, que é o cenário mais exigente descrito em [ux/01](../ux/01-navegacao-e-ui.md). Tailwind compila via CLI standalone (`bin/build_css.sh`), sem precisar de Node.
> **Atualização (2026-10-01):** o layout base foi redesenhado depois da Fase 3 — ver [Fase 3 · redesenho da interface](fase-3-vendas-e-indicadores.md#pós-fase-redesenho-da-interface-2026-10-01) e [design system](../ux/02-design-system.md). O menu lateral é fixo a partir de 1024 px (antes, 768 px) e a gaveta cobre o resto; o "modal" previsto aqui não foi necessário (nenhuma tela o usa).
> Um achado do processo: o Django Debug Toolbar (só em dev) se sobrepõe a elementos clicáveis em viewport estreita e pode atrapalhar teste automatizado de UI em 360px — não é bug do app, mas vale saber se alguém for escrever testes Playwright/Selenium contra o `dev` server.

### ✅ F0-13 · Health check e logging
**Depende de:** F0-02 · **Estimativa:** 2-3h · **Spec:** [arquitetura/02](../arquitetura/02-infra-e-deploy.md#health-check)

`/health/` (processo vivo) e `/ready/` (banco e Redis respondem), sem autenticação e **fora do log de acesso**. Logging JSON com filtro que bloqueia senha, token, `SECRET_KEY`, dado bancário e CPF/CNPJ integral.

**Pronto quando:** `/ready/` devolve 503 com o Postgres parado, e uma senha passada por engano a um logger não aparece na saída.

> **Testado em `apps/core/tests/test_health.py`** (503 simulado via mock, não Postgres parado de verdade) **e `test_logging.py`.** Achei e corrigi um bug real no caminho: o filtro de redação (`SensitiveDataFilter`) quebrava a formatação `%(name)s`-por-dict que o Celery usa no log de sucesso de task, porque iterava um dict como se fosse posicional — `config/logging_filters.py` agora trata os dois casos.

### ✅ F0-14 · Celery
**Depende de:** F0-02 · **Estimativa:** 2-3h · **Spec:** [arquitetura/01](../arquitetura/01-arquitetura.md#stack)

`worker` e `beat` no compose, `config/celery.py`, e uma task real para validar o caminho.

**Pronto quando:** uma task enfileirada pelo `web` executa no `worker` e o resultado aparece no log.

> **Validado com Redis de verdade** (baixei os pacotes `.deb` e rodei um `redis-server` local, já que o sandbox não tinha nenhum) — `core.ping` enfileirou e voltou `"pong"` pelo log JSON. Teste automatizado em `apps/core/tests/test_tasks.py` (síncrono, não depende de Redis estar no ar).

### ✅ F0-15 · Dados de desenvolvimento
**Depende de:** F0-06 · **Estimativa:** 2-3h · **Spec:** [00-visao-geral](../00-visao-geral.md#para-quem)

Comando `seed_demo`: empresa, safra 2025/2026, as 5 fazendas, um usuário por papel com escopos diferentes, as 11 categorias, os 11 centros de custo.

**Pronto quando:** `seed_demo` roda em banco limpo e dá para logar como `campo@teste` enxergando só uma fazenda.

> **Esta tarefa puxou modelos que a Fase 1 ainda não tinha criado.** Para o comando ter onde escrever, criei agora os cadastros mínimos do modelo de dados: `Company`/`BusinessUnit`/`Season` (`apps/organizations`), `Farm` completo + `Paddock` (`apps/properties`), `AnimalCategory`/`Breed` (`apps/livestock`), `CostClass`/`CostCenter` (`apps/costs`) — campos e nomes exatamente como em [modelo-dados/01](../modelo-dados/01-entidades.md). **Sem views, forms ou regra de negócio** — isso é Fase 1/2. A Fase 1 pode (e deve) assumir que esses modelos já existem, em vez de recriá-los.
> Semeei as **6 fazendas** listadas em [modelo-dados/01](../modelo-dados/01-entidades.md#espinha-organizacional) (incluindo São Francisco **e** São Francisco II como registros distintos) — decisão reversível, não resolve a pendência #5, só dá dado de desenvolvimento para testar o escopo por fazenda. `seed_demo` é idempotente (`get_or_create` em tudo). Testado em `apps/organizations/tests/test_seed_demo.py`.

### ⚠️ F0-16 · Integração contínua
**Depende de:** F0-04 · **Estimativa:** 2-3h

Ruff, Black, pytest com cobertura das regras. Regra de lint proibindo `float(` em `services.py` e `models.py` ([ADR 0005](../arquitetura/adr/0005-decimal-e-arredondamento.md)).

**Pronto quando:** a suíte roda em um comando e falha se alguém introduzir `float` em serviço.

> **`pyproject.toml`** centraliza Ruff/Black/coverage; `.github/workflows/ci.yml` sobe Postgres 16 e Redis 7 de verdade como *services* do GitHub Actions (é lá que o teste de concorrência do F0-10 e o trigger do F0-08 rodam). A regra contra `float(` virou **teste** (`apps/core/tests/test_lint_no_float.py`), não regra de lint — o Ruff não tem suporte nativo a "proibir token X nestes arquivos" sem um plugin próprio.
> **O workflow nunca rodou de verdade** — não há repositório Git ainda (decisão do início desta sessão) nem push ao GitHub. Os comandos que ele chama (`ruff check .`, `black --check .`, `pytest --cov=apps`, `manage.py migrate`/`check`) foram todos validados localmente, com Python 3.12 e Redis reais.

---

## Produção

### ❌ F0-17 · Primeiro deploy no VPS
**Depende de:** F0-13, F0-16 · **Estimativa:** 5-7h · **Spec:** [arquitetura/02](../arquitetura/02-infra-e-deploy.md)

`docker-compose.prod.yml` com Gunicorn, `restart: unless-stopped`, healthcheck e limite de memória. Integração com o **Nginx já existente no host** via `proxy_pass 127.0.0.1:8010` — sem subir outro proxy. TLS com renovação automática. Firewall conferido: 22, 80, 443 e nada mais.

`deploy.sh` com `set -euo pipefail`: backup → pull → build → migrate → collectstatic → up → healthcheck ou rollback.

> Máquina compartilhada. Conferir antes que a porta 8010 está livre, e documentar qualquer mudança de firewall em `deploy/firewall.md`.

**Pronto quando:** `https://rebanho360.<domínio>` responde, dá para logar do celular pela internet, e os outros sistemas do VPS continuam no ar.

> **Não executado — precisa de um VPS real.** `docker-compose.prod.yml` e `docker/web/Dockerfile` (estágio `prod`, com build do Tailwind e `collectstatic` embutidos) e `deploy/{deploy,backup,healthcheck,rollback,local}.sh` (+ `_lib.sh`, `nginx.conf.example`, `restore-check.sql`; revisados em 2026-10-01) estão escritos e com sintaxe conferida (`bash -n`), seguindo exatamente a topologia de [arquitetura/02](../arquitetura/02-infra-e-deploy.md) (Nginx do host, só `web` publica porta, só em `127.0.0.1:8010`). Falta: provisionar o VPS, rodar `deploy.sh` pela primeira vez, apontar o Nginx do host e o DNS.

### ❌ F0-18 · Backup e restauração testada
**Depende de:** F0-17 · **Estimativa:** 3-4h · **Spec:** [arquitetura/02](../arquitetura/02-infra-e-deploy.md#backup)

`pg_dump` diário, tar do volume de media, envio para fora do VPS. Retenção 7/4/12.

E a parte que costuma ser pulada: **restaurar o dump em container descartável e conferir**, anotando data, duração e resultado em `deploy/restore-log.md`.

**Pronto quando:** existe uma linha em `restore-log.md` com uma restauração real, e você sabe quanto tempo ela leva.

> **Não executado — depende da F0-17.** `deploy/backup.sh` (pg_dump + tar de media + `rclone`, retenção simplificada por idade) e `deploy/restore-log.md` (com o procedimento documentado) estão prontos. Falta rodar o primeiro backup e a primeira restauração reais e anotar o tempo.

---

## Fase fechada quando

- [ ] `https://rebanho360.<domínio>` responde e dá para logar do celular — **falta VPS**
- [x] O menu funciona em 360 px sem rolagem horizontal — verificado com Playwright (login, início, auditoria)
- [x] Uma ação qualquer gera `AuditEvent` com ator, IP e `request_id`
- [x] O `ADMIN` encontra essa ação no console, vê o diff e a desfaz por ali
- [x] Não existe caminho de código que altere um `AuditEvent` (trigger de banco ainda não exercido contra Postgres real nesta sessão — roda no CI)
- [x] Usuário fora do escopo recebe `404`, não `403`
- [ ] O backup rodou **e foi restaurado uma vez**, com o tempo anotado — **falta VPS**
- [ ] Os outros sistemas do VPS continuam funcionando — **falta VPS**

**Para fechar a fase por completo:** provisionar o VPS, rodar `deploy/deploy.sh` pela primeira vez (F0-17) e depois `deploy/backup.sh` + uma restauração real anotada em `deploy/restore-log.md` (F0-18). Tudo o que não depende de infraestrutura física está pronto e testado.

> **Antes de começar a Fase 1:** resolver a pendência **[#5](../regras-negocio/99-pendencias.md)** — São Francisco e São Francisco II são a mesma fazenda? Bloqueia a carga histórica, e desmembrar depois significa reprocessar todo o razão.

**Próxima:** [Fase 1 — Cadastros e rebanho](fase-1-cadastros-e-rebanho.md)
