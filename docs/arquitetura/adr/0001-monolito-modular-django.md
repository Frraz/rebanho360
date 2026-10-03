# ADR 0001 — Monólito modular Django

**Data:** 2026-09-30 · **Status:** Aceita

## Problema

O sistema cobre rebanho, custos, compras, vendas, financeiro, relatórios e dashboards, para pouco mais de 10 usuários, hospedado num VPS Ubuntu que já roda outros sistemas. Qual arquitetura?

## Decisão

**Monólito modular Django.** Um processo web, um banco PostgreSQL, apps com fronteiras claras e camadas internas (`models / services / selectors / forms / permissions / tasks`).

Frontend server-side: Django Templates + HTMX + Alpine.js + Tailwind. Sem SPA.

Celery + Redis apenas para PDF pesado, importação de planilha e consolidação. Não para tudo.

## Alternativas descartadas

**Microserviços.** Resolveria escala que não existe e independência de times que não existem. Traria rede entre serviços, consistência eventual e uma conta de operação que uma equipe de uma pessoa não paga. O sistema todo cabe num processo.

**Django + React/Vue.** Duplicaria a modelagem — serializers, estado no cliente, roteamento, build. O sistema é formulário, tabela, filtro, aprovação, documento e dashboard: exatamente o que Django server-side faz com menos código. HTMX cobre a interatividade que falta (busca, autocomplete, atualização parcial, modal) sem build separado.

**Django "solto", tudo em `views.py`.** É o caminho natural e é o que apodrece. Regra financeira espalhada entre view, template e JavaScript é impossível de testar e de auditar — e aqui há dinheiro e saldo de rebanho envolvidos.

## Consequências

**Boas:** um deploy, um banco, uma migração, um log. Transação atômica atravessando módulos sem esforço — decisivo para confirmar uma compra que mexe em rebanho e custo ao mesmo tempo. Menos infraestrutura para proteger num VPS compartilhado.

**Ruins:** escala vertical até certo ponto — irrelevante neste volume. Fronteira entre apps depende de disciplina, não de rede: exige revisão de código para não virar espaguete. Um deploy derruba tudo — mitigado por health check e deploy rápido.

**A disciplina que sustenta:** view não escreve no banco, template não calcula. Se há conta em `{{ }}`, está no lugar errado.
