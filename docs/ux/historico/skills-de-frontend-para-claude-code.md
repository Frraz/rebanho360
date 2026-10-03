# Rebanho 360 — Frontend, Design, UI/UX e QA para Claude Code

> **Documento histórico.** Prompt/insumo usado no redesenho de 01/10/2026, mantido só como registro. O `DESIGN.md` citado aqui hoje é [`02-design-system.md`](../02-design-system.md); a fonte de verdade é ele, não este arquivo.

> **Objetivo:** montar um conjunto enxuto de skills para que o Claude Code desenvolva e refine o Rebanho 360 com alta qualidade visual, UX consistente, acessibilidade, performance e QA real.
>
> **Ambiente considerado:** Ubuntu + VS Code + Claude Code.  
> **Revisado em:** 01/10/2026.

## Princípio central

Não instalar dezenas de skills de design que fazem a mesma coisa. O Rebanho 360 deve ter uma única **fonte de verdade visual** (`DESIGN.md`) e um fluxo:

```text
Design → Implementação → Renderização real → Auditoria visual/a11y → QA funcional → Performance → Review
```

As skills abaixo foram escolhidas por utilidade prática, maturidade do projeto, manutenção e complementaridade.

---

# 1. Stack recomendada

## Essenciais

| Skill | Função principal | Utilidade no Rebanho 360 | Instalação |
|---|---|---|---|
| **Anthropic Frontend Design** | Direção visual e implementação de UI | Evita UI genérica/“AI slop” e força decisões deliberadas de tipografia, composição, cor e interação | `/plugin marketplace add anthropics/claude-plugins-official` + `/plugin install frontend-design@claude-plugins-official` |
| **UI UX Pro Max** | Inteligência de design e geração de design system | Ajuda a estruturar estilo, tokens, padrões e componentes para um sistema administrativo consistente | `npx ui-ux-pro-max-cli init --ai claude` |
| **Impeccable** | Refinamento e auditoria visual | Excelente para polish, tipografia, espaçamento, hierarquia, motion e correção de “slop” | `npx impeccable install --providers=claude --scope=project` |
| **Vercel Web Design Guidelines** | Auditoria de UI/UX/a11y/performance | Revisa a interface contra regras web atuais e encontra problemas que podem passar despercebidos | `npx skills add https://github.com/vercel-labs/agent-skills --skill web-design-guidelines --agent claude-code` |
| **Vercel React Best Practices** | Performance React/Next.js | Evita waterfalls, bundles desnecessários, re-renders e padrões de implementação ruins | `npx skills add https://github.com/vercel-labs/agent-skills --skill react-best-practices --agent claude-code` |
| **Vercel Composition Patterns** | Arquitetura de componentes React | Ajuda a manter componentes reutilizáveis e evitar excesso de boolean props/prop drilling | `npx skills add https://github.com/vercel-labs/agent-skills --skill composition-patterns --agent claude-code` |
| **Anthropic webapp-testing** | QA funcional no navegador | Usa Playwright para testar o sistema executando, capturar screenshots e investigar comportamento real | Ver seção de instalação abaixo |
| **gstack** | Orquestração de design review, QA e code review | Cria um fluxo operacional de revisão e QA dentro do Claude Code | Ver seção de instalação abaixo |

## Complementar importante

| Skill | Quando usar |
|---|---|
| **Interface Design** | Quando a prioridade for memória/consistência visual persistente por meio de um sistema de design próprio. Pode complementar `DESIGN.md`, mas não é obrigatório se o projeto já tiver um bom `DESIGN.md`. |
| **skill-creator (Anthropic)** | Para criar depois uma skill própria do Rebanho 360 com regras específicas do produto. |

---

# 2. Instalação das skills oficiais da Anthropic

## Frontend Design

Dentro do Claude Code:

```text
/plugin marketplace add anthropics/claude-plugins-official
/plugin install frontend-design@claude-plugins-official
```

Depois, em uma tarefa de UI, pode-se usar explicitamente:

```text
Use frontend-design to design and implement this screen.
```

> **Nota:** o plugin `frontend-design` existe no marketplace oficial, mas atualmente não traz versão explícita no manifesto; portanto, não conte com pin de versão. Confira `claude plugin list` após instalar.

## Skill Creator

Útil mais tarde para criar a skill específica do Rebanho 360:

```text
/plugin install skill-creator@claude-plugins-official
```

## Webapp Testing

A skill oficial está no repositório `anthropics/skills`. A distribuição atual é feita junto do plugin de example skills.

Dentro do Claude Code:

```text
/plugin marketplace add anthropics/skills
/plugin install example-skills@anthropic-agent-skills
```

Depois use:

```text
Use webapp-testing to test the local Rebanho 360 frontend.
```

Se preferir instalar a skill como skill local usando o ecossistema `npx skills`:

```bash
npx skills add anthropics/skills --skill webapp-testing --agent claude-code
```

> O repositório oficial define `webapp-testing` como toolkit para testar aplicações web locais com Playwright, inspecionar DOM renderizado, capturar screenshots e consultar logs do navegador.

---

# 3. UI UX Pro Max

## O que faz

É uma camada de **design intelligence** para ajudar o agente a tomar decisões de UI/UX, gerar e consultar padrões e manter um sistema de design estruturado.

## Por que usar no Rebanho 360

É útil principalmente no início de cada módulo/tela para responder de forma consistente:

- qual hierarquia visual usar;
- como organizar dashboard, tabelas, formulários e filtros;
- quais tokens e padrões reutilizar;
- como tratar diferentes tipos de conteúdo e densidade de informação.

## Instalação recomendada

```bash
npm install -g ui-ux-pro-max-cli
cd /caminho/do/rebanho-360
uipro init --ai claude
```

Alternativa sem instalação global:

```bash
npx ui-ux-pro-max-cli init --ai claude
```

Para instalar globalmente em todos os projetos:

```bash
uipro init --ai claude --global
```

Após instalar, reinicie o Claude Code.

---

# 4. Impeccable

## O que faz

É uma camada de **refino visual e linguagem de design**. Possui comandos para auditoria, crítica e polish, incluindo `/audit`, `/critique`, `/polish`, `/shape`, `/animate`, `/distill` e outros.

## Por que usar no Rebanho 360

Perfeito para a etapa em que a tela já funciona, mas ainda precisa parecer um produto profissional:

```text
implementado → criticado → refinado → verificado
```

Use principalmente depois de construir uma tela importante.

## Instalação

No terminal, a partir da raiz do projeto:

```bash
npx impeccable install --providers=claude --scope=project
```

Ou globalmente:

```bash
npx impeccable install --providers=claude --scope=global
```

Depois reinicie o Claude Code.

Exemplos:

```text
/impeccable audit
/impeccable critique
/impeccable polish
```

---

# 5. Vercel Web Design Guidelines

## O que faz

Audita interfaces web contra boas práticas de UX, acessibilidade, foco, formulários, animações, tipografia, imagens, navegação, estado, responsividade e performance.

## Por que usar no Rebanho 360

É uma excelente **barreira de qualidade** antes de considerar uma tela pronta. Ajuda a encontrar problemas que não são necessariamente bugs, mas degradam a experiência.

## Instalação

```bash
npx skills add https://github.com/vercel-labs/agent-skills --skill web-design-guidelines --agent claude-code
```

Para instalação global:

```bash
npx skills add https://github.com/vercel-labs/agent-skills --skill web-design-guidelines --agent claude-code -g
```

Uso:

```text
Review this UI against the Vercel Web Design Guidelines.
```

---

# 6. Vercel React Best Practices

## O que faz

Traz as regras de performance da Vercel para React/Next.js, cobrindo principalmente waterfalls assíncronos, bundle size, server-side performance, fetching, re-renders, rendering e otimizações de JavaScript.

## Por que usar no Rebanho 360

Sistemas administrativos acumulam tabelas, filtros, gráficos, formulários e consultas. Sem disciplina, a UI pode ficar lenta mesmo com um design excelente.

## Instalação

```bash
npx skills add https://github.com/vercel-labs/agent-skills --skill react-best-practices --agent claude-code
```

Global:

```bash
npx skills add https://github.com/vercel-labs/agent-skills --skill react-best-practices --agent claude-code -g
```

Uso:

```text
Review this React code using Vercel React Best Practices.
```

---

# 7. Vercel Composition Patterns

## O que faz

Ensina padrões de composição para componentes React, evitando componentes monolíticos e excesso de boolean props. Cobre compound components, lifting state, composição interna e variantes explícitas.

## Por que usar no Rebanho 360

Ajuda a impedir que componentes como `DataTable`, `Dialog`, `Form`, `FilterBar` e `Card` se transformem em componentes difíceis de manter depois de dezenas de telas.

## Instalação

```bash
npx skills add https://github.com/vercel-labs/agent-skills --skill composition-patterns --agent claude-code
```

Global:

```bash
npx skills add https://github.com/vercel-labs/agent-skills --skill composition-patterns --agent claude-code -g
```

---

# 8. gstack

## O que faz

É uma camada mais ampla de workflow para Claude Code. Entre os recursos mais úteis para este projeto estão:

```text
/design-consultation
/plan-design-review
/design-review
/qa
/qa-only
/review
/investigate
/autoplan
```

## Por que usar no Rebanho 360

Ele ajuda a transformar qualidade em **processo**, em vez de depender de lembrar manualmente todos os tipos de revisão.

Um fluxo possível:

```text
/plan-design-review
        ↓
implementação
        ↓
/design-review
        ↓
/qa
        ↓
/review
```

## Instalação

Na sessão do Claude Code:

```text
git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack
./setup
```

Depois reinicie o Claude Code.

> O próprio projeto recomenda adicionar uma seção `gstack` no `CLAUDE.md` para explicar o uso das skills. Não copie instruções antigas cegamente: depois da instalação, consulte a documentação do repositório instalado e mantenha apenas os comandos que você realmente pretende usar.

---

# 9. Interface Design — opcional

## O que faz

Mantém memória e enforcement de decisões de design, ajudando a evitar drift em medidas, espaçamento, profundidade e padrões.

## Por que pode ser útil

Pode ser interessante quando o Rebanho 360 já tiver muitas telas e você perceber que o Claude começa a variar componentes ou espaçamentos entre sessões.

## Instalação

```bash
npx skills add https://github.com/Dammyjay93/interface-design --skill interface-design --agent claude-code -g
```

Ou, para o projeto atual:

```bash
npx skills add https://github.com/Dammyjay93/interface-design --skill interface-design --agent claude-code
```

### Regra

Não trate `interface-design` e `DESIGN.md` como duas autoridades concorrentes. Escolha uma fonte principal de verdade para tokens e decisões visuais.

---

# 10. O arquivo mais importante: DESIGN.md

Independentemente das skills escolhidas, crie na raiz do Rebanho 360:

```text
DESIGN.md
```

Esse arquivo deve ser a **fonte de verdade visual do produto**.

Sugestão de conteúdo:

```text
# Rebanho 360 — Design System

## Brand
## Design Principles
## Colors
## Typography
## Spacing
## Radius
## Shadows
## Icons
## Layout
## Navigation
## Buttons
## Inputs
## Tables
## Cards
## Dialogs
## Badges
## Charts
## Forms
## Loading States
## Empty States
## Error States
## Success States
## Disabled States
## Responsive Rules
## Accessibility
## Motion
## Do / Don't
```

A função das skills é **aplicar e melhorar** esse sistema, não reinventá-lo a cada nova tela.

---

# 11. Skills que NÃO entram no núcleo

## Taste Skill

É interessante e possui parâmetros como `DESIGN_VARIANCE`, `MOTION_INTENSITY` e `VISUAL_DENSITY`, mas existe sobreposição considerável com `frontend-design` + `Impeccable` + `DESIGN.md`.

Instale apenas para experimentação estética.

Se quiser experimentar:

```bash
npx skills add https://github.com/Leonxlnx/taste-skill --skill design-taste-frontend --agent claude-code
```

## Hallmark

É uma skill anti-AI-slop forte e madura. Pode ser útil para projetos altamente visuais, porém no Rebanho 360 ela se sobrepõe parcialmente à função de `frontend-design` e `Impeccable`.

Instalação:

```bash
npx skills add nutlope/hallmark --agent claude-code
```

**Recomendação:** testar depois, não instalar no núcleo inicialmente.

## AccessLint / skills pequenas de a11y

Podem complementar testes de acessibilidade, mas eu não faria delas uma dependência central enquanto o projeto pode obter uma primeira camada sólida por meio das Web Design Guidelines, HTML semântico, teclado, foco, estados e testes do browser.

---

# 12. Como as skills devem trabalhar juntas

## Ao criar uma nova tela

```text
1. Leia PRODUCT.md
2. Leia DESIGN.md
3. Use frontend-design + UI UX Pro Max para direção
4. Implemente respeitando o design system
5. Use React Best Practices + Composition Patterns
6. Rode no browser
7. Use Impeccable /design-review
8. Use Vercel Web Design Guidelines
9. Use webapp-testing
10. Corrija
11. Teste novamente
```

## Ao melhorar uma tela existente

```text
1. Não redesenhar por impulso
2. Inspecionar o estado atual no browser
3. `/impeccable audit`
4. Corrigir problemas de maior impacto
5. Validar responsive + estados + teclado
6. Rodar webapp-testing
7. Rodar review técnico
```

## Ao finalizar uma feature

```text
implementação
    ↓
/design-review
    ↓
/qa
    ↓
/review
```

---

# 13. Checklist mínimo de “pronto”

Uma tela do Rebanho 360 não deve ser considerada pronta apenas porque compila.

### Visual

- [ ] Hierarquia visual clara
- [ ] Tipografia consistente
- [ ] Espaçamento baseado nos tokens
- [ ] Sem componentes “genéricos de IA” sem motivo
- [ ] Sem excesso de cards, gradientes ou sombras
- [ ] Estados visuais definidos
- [ ] Desktop e mobile/viewport menor verificados

### UX

- [ ] A ação principal é evidente
- [ ] Labels são claros
- [ ] Erros explicam como corrigir
- [ ] Loading/empty/error/success existem quando necessários
- [ ] Filtros e navegação têm estado previsível
- [ ] Confirmações aparecem apenas quando agregam segurança

### Acessibilidade

- [ ] HTML semântico
- [ ] Navegação por teclado
- [ ] Focus visível
- [ ] Contraste adequado
- [ ] Não usar apenas cor para comunicar estado
- [ ] Labels e nomes acessíveis
- [ ] Motion respeita `prefers-reduced-motion` quando aplicável

### Técnica

- [ ] Sem waterfalls desnecessários
- [ ] Sem re-renders evitáveis
- [ ] Componentes compostos e reutilizáveis
- [ ] Sem boolean props descontroladas
- [ ] Dados e estado separados adequadamente da apresentação
- [ ] Console sem erros

### QA

- [ ] Fluxo principal testado no browser
- [ ] Screenshots/estado renderizado revisados
- [ ] Casos de erro testados
- [ ] Casos vazios testados
- [ ] Responsividade verificada
- [ ] Regressão verificada após correções

---

# 14. Ordem de instalação recomendada

Para o primeiro setup do Rebanho 360, faça nesta ordem:

```text
1. frontend-design
2. UI UX Pro Max
3. Impeccable
4. web-design-guidelines
5. react-best-practices
6. composition-patterns
7. webapp-testing
8. gstack
9. criar DESIGN.md
10. criar uma skill própria rebanho360-ui (fase posterior)
```

Não instale Taste, Hallmark e várias outras skills estéticas ao mesmo tempo. Primeiro estabeleça uma direção visual e um sistema de design estáveis.

---

# 15. Recomendação de escopo: projeto vs global

### Projeto (`.claude/skills`)

Prefira para as skills que fazem parte da identidade e qualidade do Rebanho 360. Isso mantém o setup reproduzível e facilita documentar o ambiente do projeto.

### Global (`~/.claude/skills`)

Prefira para ferramentas que você quer usar em qualquer projeto, como algumas ferramentas gerais de workflow.

### Plugins do Claude Code

Plugins instalados via `/plugin` são gerenciados pelo próprio Claude Code e não devem ser duplicados manualmente no mesmo escopo sem necessidade.

---

# 16. Segurança antes de instalar

Para qualquer skill de terceiros:

```bash
# baixe/inspecione primeiro
# confira SKILL.md, scripts, hooks e dependências
# só depois instale
```

Priorize:

```text
Anthropic
↓
Vercel / Google / projetos de alta confiança
↓
GitHub ativo, código auditável, licença clara
↓
skills pequenas/obscuras apenas quando realmente necessárias
```

Não trate número de stars como prova de segurança. Skills são instruções que podem ganhar acesso a ferramentas do agente; revise o conteúdo antes de conceder esse acesso.

---

# 17. Fontes principais consultadas

- Anthropic — Frontend Design plugin: https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design
- Anthropic — Webapp Testing: https://github.com/anthropics/skills/tree/main/skills/webapp-testing
- Anthropic — Skill Creator: https://github.com/anthropics/claude-plugins-official/tree/main/plugins/skill-creator
- Vercel Agent Skills: https://github.com/vercel-labs/agent-skills
- Vercel Web Interface Guidelines: https://github.com/vercel-labs/web-interface-guidelines
- UI UX Pro Max: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill
- Impeccable: https://github.com/pbakaus/impeccable
- gstack: https://github.com/garrytan/gstack
- Interface Design: https://github.com/Dammyjay93/interface-design
- Hallmark: https://github.com/nutlope/hallmark
- Taste Skill: https://github.com/Leonxlnx/taste-skill

---

## Resumo executivo

Para o Rebanho 360, a combinação de maior utilidade prática é:

```text
frontend-design
      +
UI UX Pro Max
      +
Impeccable
      +
Vercel Web Design Guidelines
      +
Vercel React Best Practices
      +
Vercel Composition Patterns
      +
webapp-testing
      +
gstack
      +
DESIGN.md
```

O ganho principal não vem de acumular skills. Vem de fazer essas ferramentas obedecerem ao mesmo sistema de design e passarem por um ciclo real de inspeção e QA no navegador.
