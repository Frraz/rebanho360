# Arquitetura

## Forma geral

**Monólito modular Django.** Um processo, um banco, apps com fronteiras claras. Sem microserviços, sem fila distribuída complexa, sem frontend separado.

A justificativa está em [ADR 0001](adr/0001-monolito-modular-django.md). Em resumo: o sistema é essencialmente formulários, tabelas, filtros, aprovações, documentos e dashboards, para uma equipe de pouco mais de 10 pessoas. Django server-side entrega isso com uma fração da complexidade operacional de qualquer alternativa.

## Stack

| Camada | Escolha | Observação |
|---|---|---|
| Backend | Python 3.12 + Django 5.x | |
| Banco | PostgreSQL 16 | Nunca SQLite em produção |
| Frontend | Django Templates + HTMX + Alpine.js + Tailwind CSS | Sem React/Vue. Design system próprio ([design system](../ux/02-design-system.md), [ADR 0007](adr/0007-design-system-proprio-sobre-tailwind.md)); fontes IBM Plex e ícones Lucide servidos localmente |
| Tarefas assíncronas | Celery + Redis | Só PDF pesado, importação e consolidação |
| PDF | WeasyPrint | HTML/CSS → PDF, mesmo motor de template |
| Planilhas | openpyxl | Leitura na importação, escrita na exportação |
| Arquivos | Disco local protegido | Servidos por view autenticada, nunca por URL pública |
| Infra | Docker Compose em VPS Ubuntu compartilhado | Ver [02-infra-e-deploy](02-infra-e-deploy.md) |
| Observabilidade | Logs estruturados + health check + Sentry (opcional) | |

DRF entra **só** quando houver um consumidor real de API. Não criar endpoints CRUD genéricos por antecipação.

## Estrutura de pastas

```
rebanho360/
├── backend/
│   ├── config/                  settings por ambiente, urls, wsgi, celery
│   ├── apps/
│   │   ├── core/                base compartilhada: mixins, Decimal, ScopedManager
│   │   ├── accounts/            User, Papel, UserFarmAccess
│   │   ├── organizations/       Empresa, Unidade, Safra
│   │   ├── properties/          Fazenda, Área/Pasto, Infraestrutura
│   │   ├── partners/            Parceiro (multi-papel), ContaBancaria
│   │   ├── livestock/           CategoriaAnimal, Raca, Lote
│   │   ├── herd/                HerdMovement, HerdLedgerEntry, Pesagem  ← núcleo
│   │   ├── costs/               CentroCusto, ClasseCusto, LancamentoCusto
│   │   ├── purchases/           Compra
│   │   ├── sales/               Venda / Abate
│   │   ├── finance/             Títulos e baixas, contas/fluxo/mapa (Fase 4)
│   │   ├── imports/             staging → validação → prévia → confirmação
│   │   ├── exports/             catálogo de dados → fila (Celery) → CSV, XLSX, JSON, PDF em ZIP
│   │   ├── reports/
│   │   ├── dashboards/
│   │   ├── documents/           geração e versionamento de documentos
│   │   └── audit/               AuditEvent, OperationEvent
│   ├── templates/
│   │   ├── base.html            shell: menu lateral, barra de contexto, avisos
│   │   ├── partials/            menu, contexto, toasts, _field, _form_page, _empty, _pagination
│   │   └── <app>/               telas de cada app
│   ├── static/
│   │   ├── css/input.css        design system (componentes); output.css é GERADO
│   │   ├── fonts/               IBM Plex (woff2)
│   │   ├── img/                 icons.svg (sprite), logo-mark.png, favicon.png
│   │   └── vendor/              htmx, alpine (sem CDN)
│   ├── bin/build_css.sh         compila o Tailwind (CLI standalone, sem Node)
│   ├── tailwind.config.js       tokens: paleta, fontes, sombra
│   └── manage.py
├── docker/
├── deploy/                      local, deploy, backup, rollback, healthcheck, nginx
├── docs/                        documentação; ux/02-design-system.md é a fonte visual
└── docker-compose.yml
```

`static/css/output.css` não é versionado: o estágio `prod` do Dockerfile o compila, e em desenvolvimento o `deploy/local.sh` (ou `sh bin/build_css.sh`) o gera.

## Camadas dentro de cada app

```
models.py        estrutura e constraints. Sem regra de negócio complexa.
services.py      escreve. Toda operação que altera estado passa por aqui.
selectors.py     lê. Consultas e agregações, com select_related/prefetch_related.
forms.py         validação de entrada vinda da web.
permissions.py   quem pode o quê, e sobre qual fazenda.
tasks.py         Celery.
views.py         fino. Recebe request, chama service/selector, devolve template.
tests/           testes das regras, não das telas.
```

**A regra que sustenta isso:** uma view nunca escreve no banco diretamente, e um template nunca calcula. Se há conta em `{{ }}`, ela está no lugar errado.

## As três camadas conceituais do domínio

Separação que evita o pior problema deste tipo de sistema, que é duplicação de informação.

```
CADASTROS                TRANSAÇÕES                  DERIVADOS
(mudam pouco)            (o que aconteceu)           (nunca gravados)
─────────────            ─────────────────           ──────────────────
Empresa                  Movimentação de rebanho     Saldo do rebanho
Unidade                  Compra                      Custo por cabeça
Safra                    Venda / Abate               Custo por @
Fazenda                  Pesagem                     Custo por kg
Área / Pasto             Lançamento de custo         GMD
Parceiro                 Transferência               @ produzida
Categoria animal         Título / Pagamento          Rendimento de carcaça
Lote                                                 Resultado por lote
Centro de custo                                      Resultado por safra
```

Nada da terceira coluna existe como campo no banco. Tudo ali é função da segunda.

## Serviços de cálculo

Fonte única da verdade para cada número derivado. Relatório, dashboard e tela consomem o mesmo serviço — nunca reimplementam a conta.

| Serviço | App | Responde |
|---|---|---|
| `HerdBalanceService` | `herd` | Saldo por fazenda / lote / categoria em qualquer data |
| `WeightGainService` | `herd` | GMD, @ produzida, dias no período |
| `CarcassService` | `sales` | Rendimento de carcaça, @ de carcaça, peso médio |
| `PurchaseCostService` | `purchases` | Custo de aquisição = valor + frete + comissão + impostos |
| `CostAllocationService` | `costs` | Custo por lote / fazenda / cabeça / kg / @ |
| `SaleResultService` | `sales` | Receita líquida e resultado por lote e safra |

Detalhes das fórmulas em [regras-negocio/05](../regras-negocio/05-indicadores-e-calculos.md).

## Dinheiro e peso

`Decimal` sempre. `float` nunca, em nenhuma circunstância, para valor monetário ou peso.

```python
# apps/core/money.py — módulo único que define as regras
MONEY_PLACES   = Decimal("0.01")    # R$ com 2 casas
WEIGHT_PLACES  = Decimal("0.001")   # kg com 3 casas
ARROBA_PLACES  = Decimal("0.01")    # @ com 2 casas
ROUNDING       = ROUND_HALF_UP      # arredondamento comercial brasileiro
KG_PER_ARROBA  = Decimal("15")
```

Arredondar apenas na apresentação e na gravação final. Nunca no meio de uma cadeia de cálculo.

## Concorrência e integridade

O banco protege os dados, não só o código Python.

- `transaction.atomic()` em toda operação que escreve mais de uma linha
- `select_for_update()` ao alterar saldo, fechar acerto ou dar baixa em pagamento
- `CheckConstraint` para invariantes: quantidade positiva, peso não negativo, data de saída ≥ data de entrada
- `UniqueConstraint` para impedir duplicidade: número de compra por safra, lançamento por documento
- Índices nos campos realmente filtrados: `data`, `fazenda`, `safra`, `categoria`, `lote`, `status`
- Chave de idempotência em importação e em geração de título

O caso mais crítico é o par `HerdMovement` + `HerdLedgerEntry`: as duas linhas de um movimento de transferência nascem na mesma transação, ou nenhuma nasce.

## Identificadores

Dois, com papéis distintos:

- **Interno:** `BigAutoField` ou UUID, nunca mostrado ao usuário
- **Operacional:** código legível e estável, é o que aparece na tela e no papel

```
Compra        CP-2025/26-0001
Venda         VD-2025/26-0012
Movimentação  MV-2025/26-004871
Lote          LT-SFR-001
```

Gerados por serviço, com constraint de unicidade por safra.

## Auditoria

Duas coisas diferentes, e é importante não confundi-las:

- **`AuditEvent`** — trilha técnica. Quem, quando, de que IP, qual entidade, valor antes e depois, `request_id`. Serve para segurança e investigação.
- **`OperationEvent`** — linha do tempo de negócio. "Compra registrada", "150 cabeças transferidas para o Baixão", "Abate lançado". Serve para o usuário entender o que aconteceu.

Detalhes em [seguranca/01](../seguranca/01-seguranca.md).

## O que deliberadamente não fazemos

- Motor genérico de workflow. As máquinas de estado são pequenas e explícitas.
- Sistema de permissões abstrato. Papel + escopo de fazenda resolve, e é auditável.
- Event sourcing completo. A razão de movimentações do rebanho já dá a reconstituição onde ela importa.
- Camada de repositório sobre o ORM. O ORM do Django já é a camada.
- Cache antes de medir. Primeiro consultas bem construídas e índices certos.
