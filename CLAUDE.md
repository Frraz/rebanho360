# CLAUDE.md — Rebanho360

Sistema de gestão pecuária para **uma operação real de fazenda a pasto, com a compra de gado integrada**: 5 fazendas, ~2.000 cabeças, ~R$ 2,5 milhões de compra e ~R$ 1 milhão de custo por safra. Substitui uma planilha Excel de 17 abas.

**Não é SaaS.** Sem multi-tenant, planos, cobrança ou marketplace. Não construir complexidade voltada a clientes externos.

📖 **Documentação completa em [`docs/`](docs/README.md).** Este arquivo é o resumo operacional.

---

## Antes de codificar

1. Ler [`docs/00-visao-geral.md`](docs/00-visao-geral.md)
2. Ler [`docs/regras-negocio/99-pendencias.md`](docs/regras-negocio/99-pendencias.md) — **47 pendências** (1 confirmada; as demais abertas, cada uma com padrão reversível implementado)
3. Consultar [`docs/roadmap/`](docs/roadmap/README.md) para saber em que fase e em que tarefa estamos
4. Vai mexer em tela? Ler [`docs/ux/02-design-system.md`](docs/ux/02-design-system.md) — componentes, tokens e padrões já existem; não inventar outro

> **Fonte principal do escopo:** [`docs/fontes/Sistema_Gestao_Pasto_Compra_Gado_Estrutura_Funcional.md`](docs/fontes/Sistema_Gestao_Pasto_Compra_Gado_Estrutura_Funcional.md) (decisão de Warley, 2026-10-02; `docs/fontes/` fica só no disco local, não é versionada). O projeto é um **Sistema de Gestão a Pasto + Compra de Gado**: a compra é parte integrada da gestão pecuária, do cadastro e da negociação até a entrada no rebanho, o custo, o financeiro e o resultado. Os relatórios do SisAtak em `docs/fontes/relatorios-legado/` mostram os conceitos e números que o ciclo de compra precisa reproduzir — não o layout. O `docs/fontes/referencia/CLAUDE.md` (o original) é material arquivado: bons princípios, sem a decisão de manter a fazenda a pasto como base.

---

## Stack

Python 3.12 · Django 5.x · PostgreSQL 16 · Django Templates + HTMX + Alpine.js + Tailwind · Celery + Redis · WeasyPrint · Docker Compose em VPS Ubuntu **compartilhado**.

Sem React/Vue. DRF só quando houver consumidor real de API.

---

## As 6 regras inegociáveis

### 1. Saldo do rebanho é derivado, nunca campo

`HerdMovement` (o evento) gera `HerdLedgerEntry` (linhas com sinal). Saldo é `SUM`.

Transferência, evolução de categoria e mudança de lote geram **2 linhas** — negativa na origem, positiva no destino, na mesma transação. Soma zero.

A planilha atual fecha em **−140 cabeças** por transferência que saiu e não entrou. Isso tem que ser impossível de representar.

→ [`docs/regras-negocio/01`](docs/regras-negocio/01-rebanho-movimentacoes.md) · [ADR 0002](docs/arquitetura/adr/0002-rebanho-como-razao-de-movimentacoes.md)

### 2. `Decimal` sempre. `float` nunca

Para valor, peso, arroba e percentual. Regras de arredondamento em `apps/core/money.py`, `ROUND_HALF_UP`, arredondar só no fim da cadeia.

→ [ADR 0005](docs/arquitetura/adr/0005-decimal-e-arredondamento.md)

### 3. Divisor zero devolve `None`, nunca `0` nem erro

```python
def safe_div(a, b):
    return a / b if b else None
```

`None` vira "—" na tela. É o que elimina os `#DIV/0!` da planilha. Falta de dado é estado normal, não defeito.

### 4. Escopo por fazenda em toda consulta

Papel define **o quê**; `UserFarmAccess` define **onde**. Todo modelo com fazenda herda `ScopedManager`. Listar com `.for_user(request.user)`, **nunca** `.all()`.

Registro fora do escopo devolve `404`, não `403` — `403` confirma que existe.

→ [ADR 0003](docs/arquitetura/adr/0003-escopo-por-fazenda-desde-a-fase-0.md)

### 5. Tudo é editável e excluível — e tudo fica auditado

Qualquer ação pode ser **editada** ou **excluída**, e desfazer uma ação **desfaz todos os efeitos dela** (movimento de rebanho, custos, lote, título), na mesma transação.

- Motivo obrigatório em toda edição ou exclusão de registro confirmado
- Exclusão é lógica: o registro sai da operação, **nunca do banco**
- Antes de executar, o sistema mostra a **análise de impacto** — o que será desfeito e o que depende
- Dependência reversível → cascata explícita, confirmada pelo usuário
- Dependência bloqueante (pagamento baixado, safra encerrada, saldo ficaria negativo) → recusa **explicando o caminho**

No razão do rebanho, desfazer escreve **linhas de compensação com a data do fato original** — o razão é append-only, e a correção vale para trás.

**A auditoria é imutável, inclusive para o `ADMIN`.** Sem tela, sem método, sem `UPDATE`/`DELETE` no banco. O administrador pode apagar qualquer dado; não pode apagar o registro de que apagou.

→ [`docs/regras-negocio/06`](docs/regras-negocio/06-edicao-exclusao-e-auditoria.md)

### 6. Derivado é calculado, nunca gravado

Peso médio, rendimento, custo/@, GMD, margem. Cada um em **um** serviço, consumido por tela, relatório e dashboard.

Se dois lugares mostram o mesmo indicador com números diferentes, o usuário para de confiar nos dois.

→ [`docs/regras-negocio/05`](docs/regras-negocio/05-indicadores-e-calculos.md)

---

## Estrutura

```
backend/apps/
├── core/           ScopedManager, money.py, safe_div, mixins
├── accounts/       User, papel, UserFarmAccess
├── organizations/  Empresa, Unidade, Safra
├── properties/     Fazenda, Pasto
├── partners/       Parceiro multi-papel, Conta bancária
├── livestock/      Categoria, Raça, Lote
├── herd/           HerdMovement, HerdLedgerEntry, Pesagem   ← núcleo
├── costs/          Centro de custo, Lançamento, rateio
├── commercial/     Classes de carcaça, tipos de tributo, regras de comissão
├── procurement/    Ciclo de compra: compromisso → viagem → recebimento → acerto
├── purchases/      Compra
├── sales/          Venda / Abate
├── finance/        Títulos e baixas (Fase 4)
├── imports/        staging → validação → prévia → confirmação
├── exports/        catálogo de dados → fila (Celery) → arquivo (CSV, XLSX, JSON, PDF)
├── reports/  dashboards/  documents/  audit/

backend/templates/   base.html, partials/ (menu, contexto, toasts, campo, vazio, paginação)
backend/static/      css/ (input.css = design system), fonts/, img/ (icons.svg), vendor/
deploy/              local.sh, deploy.sh, backup.sh, rollback.sh, healthcheck.sh
```

Dentro de cada app: `models / services / selectors / forms / permissions / tasks / tests`.

**View não escreve no banco. Template não calcula.** Se há conta em `{{ }}`, está no lugar errado.

---

## Código

- Nomes de **estrutura** em inglês (`HerdMovement`, `head_count`)
- Nomes de **ação de negócio** em português (`confirmar_compra`) — é como se conversa sobre eles com quem usa
- Texto de interface em português do Brasil, com o termo que o produtor usa
- `verbose_name` em português em todo modelo
- Comentar decisão não óbvia, nunca repetir o que o código diz

→ [`docs/modelo-dados/02-vocabulario.md`](docs/modelo-dados/02-vocabulario.md)

---

## Integridade

`transaction.atomic()` em tudo que escreve mais de uma tabela. `select_for_update()` antes de mudar saldo, confirmar operação ou dar baixa.

Constraints no banco, não só em Python: FK, `UNIQUE`, `CHECK`, `NOT NULL`.

**Verificar saldo dentro da transação, com a posição travada.** Fora dela, dois lançamentos simultâneos passam na validação e produzem saldo negativo.

---

## Segurança

Nunca: senha no código · `.env` versionado · Postgres ou Redis exposto · confiar só em `is_staff` · CSRF desabilitado "para resolver problema" · HTML não confiável com `|safe` · SQL por concatenação · dado bancário ou segredo de 2FA em log · token em URL · traceback para o usuário.

Sempre: validação no servidor · permissão explícita · auditoria do que importa · Argon2 · rate limit no login · **2FA opcional, altamente recomendado a todos** · anexo servido por view autenticada.

→ [`docs/seguranca/01-seguranca.md`](docs/seguranca/01-seguranca.md)

---

## Testes

Sem cobertura artificial. O que não pode faltar:

**Cálculo** — os 6 números do abate de ago/2025 · `safe_div(x, 0) → None` · `ROUND_HALF_UP` em `0,005` · soma de transferência = 0 · rateio sem centavo perdido.

**Integridade** — saldo não fica negativo · confirmação concorrente cria um movimento, não dois · importar o mesmo arquivo duas vezes é detectado · **confirmar duas vezes gera um título, e clique duplo na baixa paga uma vez só** · soma das baixas nunca passa do título.

**Segurança** — sem permissão dá `403` · fora do escopo dá `404` · inativo não autentica · POST sem CSRF é recusado · quem aprova não paga (havendo outro) · quem ativou o segundo fator não entra sem ele.

---

## Interface

Mobile first **de verdade**. O campo lança no celular, em pé, com sinal ruim. Se for ruim ali, volta para o WhatsApp e o dado se perde na origem.

Tabela vira cartão no celular (`.table-stack`) · botão com 44 px · rascunho em `localStorage` · contexto Empresa · Safra · Fazenda fixo no topo · cor nunca sozinha para indicar status · após salvar, sugerir o próximo passo.

Feedback diz **o que aconteceu**: "✓ Compra confirmada. 126 cabeças deram entrada no lote LT-SFR-014."

Erro de negócio é específico: "Saldo insuficiente: há 12 cabeças de Machos 13 a 24 meses no Baixão, foram informadas 20."

**Design system:** [`docs/ux/02-design-system.md`](docs/ux/02-design-system.md) é a fonte de verdade visual. Em resumo: usar as classes de componente (`.btn-*`, `.card`, `.table`, `.badge-*`, `.alert-*`, `.field-*`) e os partials (`_field`, `_form_page`, `_empty`, `_pagination`) em vez de copiar HTML; ícones só pelo sprite (`{% icon "nome" %}`); **sem emoji** e sem cor como único sinal; código de registro em mono (`.code`); número alinhado à direita. Mexeu em classe ou CSS? Recompile: `docker compose exec web sh bin/build_css.sh` (o `output.css` é gerado, não versionado).

→ [`docs/ux/01-navegacao-e-ui.md`](docs/ux/01-navegacao-e-ui.md)

---

## Quando faltar uma regra de negócio

1. **Não inventar em silêncio**
2. Registrar em [`docs/regras-negocio/99-pendencias.md`](docs/regras-negocio/99-pendencias.md), com a pergunta, o porquê e o custo de mudar
3. Implementar a alternativa mais **reversível** para continuar
4. Deixar o código isolado para ajuste

O maior risco deste projeto não é técnico. É modelar o negócio errado.

---

## O que não construir

Multi-tenant · SaaS · cobrança · microserviços · Kubernetes · event sourcing completo · motor genérico de workflow · permissões abstratas · sistema de plugins · app nativo · integração sem necessidade real · abstração prematura · biblioteca por moda.

E não reescrever o projeto a cada mudança. Antes de refatoração grande: qual problema concreto resolve, qual o risco, existe solução menor? Sem ganho claro, não fazer.

---

## Definition of Done

Backend + validação + permissão **e escopo** + integrado ao fluxo + tratamento de erro + auditoria + teste das regras + funciona no desktop + **funciona no celular de 360 px (verificado, não suposto)** + não quebra o existente + não duplica dado + texto claro + documentação atualizada.

Tela que aparece não é funcionalidade pronta.
