# REDESIGN COMPLETO DA INTERFACE — REBANHO 360

> **Documento histórico.** Prompt/insumo usado no redesenho de 01/10/2026, mantido só como registro. O `DESIGN.md` citado aqui hoje é [`02-design-system.md`](../02-design-system.md); a fonte de verdade é ele, não este arquivo.

Você está trabalhando no **Rebanho 360**, um sistema já parcialmente desenvolvido e funcional, atualmente em estágio de MVP.

A sua missão nesta tarefa é **recriar e elevar radicalmente a interface visual e a experiência de uso do sistema**, transformando o frontend atual em uma interface com nível de qualidade comparável a um **SaaS/ERP maduro, profissional e desenvolvido por uma agência internacional de design de produto**.

## REGRA ABSOLUTA

**NÃO altere a lógica de negócio do sistema.**

Este trabalho é de **frontend, UI, UX, design system, acessibilidade, responsividade, performance de interface e qualidade visual**.

Preserve rigorosamente:

* regras de negócio;
* APIs;
* banco de dados;
* modelos;
* schemas;
* autenticação;
* autorização;
* rotas e URLs existentes;
* nomes e contratos das APIs;
* comportamento funcional;
* estados e fluxos existentes;
* validações existentes;
* persistência de dados;
* integrações;
* cálculos;
* serviços;
* hooks de negócio;
* mutations;
* queries;
* lógica de domínio.

Você pode refatorar componentes de frontend quando isso for necessário para melhorar a arquitetura da interface, **desde que o comportamento funcional permaneça equivalente**.

Não transforme esta tarefa em uma reescrita do sistema.

---

# 1. PRIMEIRO: ENTENDA O PROJETO

Antes de modificar qualquer código:

1. Leia completamente:

```text
REBANHO-360-FRONTEND-SKILLS.md
```

Esse arquivo contém as principais skills e ferramentas que devem ser utilizadas neste trabalho.

2. Inspecione toda a estrutura atual do projeto.

3. Identifique:

* framework;
* versão do framework;
* React/Next/Vite/etc.;
* TypeScript ou JavaScript;
* Tailwind ou outro sistema CSS;
* biblioteca de componentes existente;
* design tokens existentes;
* estrutura de páginas;
* layouts;
* componentes reutilizáveis;
* navegação;
* tabelas;
* formulários;
* modais;
* drawers;
* dashboards;
* gráficos;
* estados de loading;
* estados vazios;
* estados de erro;
* responsividade;
* temas claro/escuro, caso existam.

4. Descubra quais páginas e fluxos realmente existem.

5. Execute o projeto e observe a aplicação **no navegador**, não apenas lendo o código.

6. Faça uma auditoria visual inicial antes de começar o redesign.

---

# 2. PROTEJA O ESTADO ATUAL DO SISTEMA

Antes de qualquer alteração:

* verifique o estado do Git;
* identifique alterações existentes feitas pelo usuário;
* não apague trabalho existente;
* estabeleça mentalmente um baseline do projeto;
* registre quais problemas já existiam antes do redesign.

Durante todo o trabalho:

**não sobrescreva nem remova funcionalidades existentes apenas porque elas não combinam com o novo design.**

Caso encontre um problema de backend, banco, API ou regra de negócio já existente:

* não tente “aproveitar o redesign” para corrigi-lo;
* não altere a lógica para esconder o problema;
* registre o problema;
* mantenha o comportamento existente.

---

# 3. INSTALE AS SKILLS

Leia `REBANHO-360-FRONTEND-SKILLS.md` e instale as skills recomendadas que ainda não estiverem disponíveis.

Priorize estas:

### Design

* Anthropic Frontend Design
* UI UX Pro Max
* Impeccable

### Frontend Engineering

* Vercel Web Design Guidelines
* Vercel React Best Practices
* Vercel Composition Patterns

### QA

* Anthropic webapp-testing
* gstack

Não instale cegamente ferramentas redundantes.

A intenção é criar um sistema de trabalho complementar:

```text
Frontend Design
        ↓
Design Intelligence
        ↓
Design System
        ↓
Implementação
        ↓
Visual QA
        ↓
Accessibility / UX QA
        ↓
Functional QA
        ↓
Performance
        ↓
Final Review
```

Se alguma skill já estiver instalada, não reinstale desnecessariamente.

Se uma ferramenta exigir configuração específica, configure-a corretamente para o projeto.

---

# 4. NÃO CRIE UMA INTERFACE GENÉRICA DE IA

Esta é uma prioridade máxima.

O resultado **NÃO pode parecer um template genérico produzido por IA**.

Evite explicitamente:

* gradientes roxos genéricos;
* excesso de glassmorphism;
* excesso de cards;
* dashboards compostos por dezenas de cards iguais;
* hero sections desnecessárias;
* layouts excessivamente simétricos;
* ícones decorativos sem função;
* sombras exageradas;
* bordas excessivas;
* excesso de pills;
* excesso de badges;
* excesso de animações;
* tipografia genérica;
* componentes visualmente repetitivos sem hierarquia;
* aparência de template SaaS comprado pronto;
* visual “tech startup genérico”;
* elementos decorativos que não ajudam o usuário;
* uso indiscriminado de ilustrações;
* interfaces que parecem uma landing page em vez de um software operacional.

O Rebanho 360 deve transmitir:

**confiança, estabilidade, clareza, precisão, maturidade, eficiência e profissionalismo.**

A estética deve ser sofisticada sem ser chamativa.

O design deve parecer feito por uma equipe profissional de produto, não por um gerador automático de interfaces.

---

# 5. CONTEXTO DO PRODUTO

O Rebanho 360 é um sistema de gestão de rebanho.

Portanto, a interface deve equilibrar:

* dados;
* operações;
* produtividade;
* leitura rápida;
* tomada de decisão;
* registros;
* filtros;
* tabelas;
* indicadores;
* formulários;
* histórico;
* rastreabilidade.

É um produto operacional.

A experiência deve priorizar **clareza e eficiência**, e não efeitos visuais.

A identidade pode ter relação sutil com o universo rural/agropecuário, mas:

**NÃO transforme a interface em um clichê agro.**

Não use vacas, bois, cercas, celeiros, folhas ou símbolos rurais em excesso apenas para “mostrar o tema”.

A personalidade deve aparecer principalmente através de:

* tipografia;
* cor;
* composição;
* iconografia;
* hierarquia;
* densidade;
* espaçamento;
* detalhes de interação;
* tratamento dos dados.

---

# 6. CRIE UM DESIGN SYSTEM REAL

Antes de redesenhar dezenas de telas isoladamente, estabeleça uma linguagem visual consistente.

Crie ou atualize:

```text
DESIGN.md
```

Esse arquivo deve ser a **fonte de verdade visual do Rebanho 360**.

Documente, conforme fizer sentido:

* princípios visuais;
* cores;
* tokens;
* tipografia;
* escala tipográfica;
* espaçamentos;
* grid;
* border radius;
* sombras;
* elevação;
* iconografia;
* botões;
* inputs;
* selects;
* tabelas;
* cards;
* badges;
* tabs;
* menus;
* navegação;
* dialogs;
* drawers;
* tooltips;
* alertas;
* notificações;
* estados de loading;
* estados vazios;
* estados de erro;
* estados de sucesso;
* estados disabled;
* feedback de interação;
* focus states;
* motion;
* breakpoints;
* comportamento responsivo.

Não crie um novo componente quando já existir um equivalente reutilizável.

Sempre que possível:

```text
Design Token
      ↓
Primitive
      ↓
Component
      ↓
Pattern
      ↓
Page
```

O objetivo é evitar inconsistência entre páginas.

---

# 7. REDESENHE PRIMEIRO A ESTRUTURA GLOBAL

Antes de polir telas individualmente, avalie:

* layout principal;
* sidebar;
* header;
* navegação;
* breadcrumbs;
* área de conteúdo;
* sistema de páginas;
* hierarquia;
* navegação entre módulos;
* densidade da interface;
* comportamento em diferentes tamanhos de tela.

O shell da aplicação precisa parecer sólido e maduro.

O usuário deve sentir imediatamente que está dentro de um software profissional.

---

# 8. REFAÇA OS COMPONENTES FUNDAMENTAIS

Depois do shell, revise os componentes que aparecem em várias áreas do sistema.

Priorize:

* buttons;
* inputs;
* selects;
* combobox;
* date pickers;
* dropdowns;
* dialogs;
* sheets;
* tabs;
* cards;
* badges;
* alerts;
* toast;
* tooltips;
* pagination;
* tables;
* filters;
* search;
* forms;
* empty states;
* loading states;
* skeletons;
* error states.

Todos precisam parecer parte do mesmo produto.

Não permita que cada tela pareça ter sido criada por uma equipe diferente.

---

# 9. TABELAS SÃO CRÍTICAS

Como o Rebanho 360 é um sistema operacional/ERP, trate tabelas como componentes de primeira classe.

Revise:

* hierarquia de colunas;
* alinhamento;
* densidade;
* cabeçalhos;
* ordenação;
* filtros;
* busca;
* paginação;
* ações;
* seleção;
* estados vazios;
* loading;
* erro;
* responsividade;
* overflow;
* sticky headers quando fizer sentido;
* feedback de interação;
* leitura de números;
* leitura de datas;
* badges e status.

A tabela precisa permitir que o usuário trabalhe rapidamente.

Evite transformar cada linha em uma coleção confusa de elementos.

---

# 10. FORMULÁRIOS DEVEM SER EXCEPCIONAIS

Revise todos os formulários existentes.

Priorize:

* hierarquia;
* agrupamento;
* labels;
* ajuda contextual;
* mensagens de erro;
* validação;
* estados;
* foco;
* navegação por teclado;
* preenchimento;
* feedback após salvar;
* prevenção de erros;
* clareza das ações primárias e secundárias.

Não adicione campos ou altere regras de negócio.

Melhore apenas a forma como os campos existentes são apresentados e utilizados.

---

# 11. DASHBOARDS

Não transforme o dashboard em uma parede de cards.

O dashboard deve responder rapidamente:

* o que está acontecendo;
* o que merece atenção;
* quais indicadores são importantes;
* quais ações devem ser realizadas.

Utilize:

* hierarquia;
* agrupamento;
* tabelas;
* indicadores;
* gráficos;
* listas;
* alertas;
* comparações;
* tendências.

Cada elemento precisa justificar sua existência.

---

# 12. RESPONSIVIDADE

O sistema deve ser responsivo.

Não significa simplesmente “diminuir tudo”.

Avalie cuidadosamente:

* desktop;
* notebook;
* tablet;
* telas menores;
* largura de tabelas;
* navegação;
* sidebar;
* formulários;
* modais;
* gráficos;
* ações;
* menus;
* espaçamentos.

Quando a estrutura precisar mudar em mobile, altere a composição em vez de simplesmente reduzir os elementos.

---

# 13. ACESSIBILIDADE

A interface deve ser acessível.

Verifique especialmente:

* contraste;
* foco;
* teclado;
* semântica HTML;
* labels;
* aria quando necessário;
* navegação;
* estados;
* mensagens de erro;
* tamanho de áreas clicáveis;
* uso correto de cores;
* componentes interativos.

Não use cor como único mecanismo de comunicação.

---

# 14. PERFORMANCE

O redesign não pode transformar o sistema em uma interface pesada.

Aplique as boas práticas do:

```text
Vercel React Best Practices
```

e das:

```text
Vercel Web Design Guidelines
```

Evite:

* componentes desnecessariamente pesados;
* dependências desnecessárias;
* renders excessivos;
* JavaScript que não precisa existir;
* animações custosas;
* imagens desnecessárias;
* bibliotecas adicionadas apenas por estética.

Não introduza uma dependência nova quando a solução existente no projeto já for suficiente.

---

# 15. USE BROWSER E SCREENSHOTS

Você não deve avaliar a interface apenas pelo código.

Para cada conjunto relevante de páginas:

1. rode a aplicação;
2. abra no navegador;
3. navegue pelos fluxos;
4. observe a interface renderizada;
5. capture screenshots;
6. identifique problemas;
7. corrija;
8. renderize novamente;
9. compare o resultado.

Faça isso especialmente em:

* dashboard;
* listagens;
* páginas de detalhe;
* formulários;
* modais;
* telas de configuração;
* fluxos de criação/edição;
* páginas com tabelas;
* páginas com gráficos.

---

# 16. USE AS SKILLS DE FORMA COMPLEMENTAR

Não peça para todas as skills “decidirem o design” simultaneamente.

Utilize aproximadamente esta hierarquia:

## `frontend-design`

Use para:

* direção visual;
* composição;
* hierarquia;
* personalidade;
* tipografia;
* linguagem visual.

## `UI UX Pro Max`

Use para:

* pesquisa de padrões;
* organização do design system;
* padrões de dashboards;
* tabelas;
* formulários;
* UX;
* decisões estruturais.

## `Impeccable`

Use principalmente para:

* crítica;
* auditoria;
* refinamento;
* polish;
* spacing;
* typography;
* visual hierarchy;
* motion;
* remoção de “AI slop”.

## `web-design-guidelines`

Use para:

* UX;
* accessibility;
* interaction;
* focus;
* forms;
* responsive;
* states;
* web standards.

## `react-best-practices`

Use para:

* performance;
* rendering;
* fetching;
* bundle;
* re-render;
* arquitetura React.

## `composition-patterns`

Use para:

* componentes;
* composição;
* reutilização;
* arquitetura de UI.

## `webapp-testing`

Use para:

* browser;
* Playwright;
* screenshots;
* fluxos;
* comportamento real.

## `gstack`

Use quando apropriado para:

* design review;
* QA;
* investigação;
* revisão;
* validação final.

---

# 17. PRESERVE O COMPORTAMENTO EXISTENTE

Antes de considerar qualquer página concluída, confirme:

* navegação continua funcionando;
* links continuam funcionando;
* botões continuam funcionando;
* formulários continuam funcionando;
* filtros continuam funcionando;
* pesquisa continua funcionando;
* paginação continua funcionando;
* dialogs continuam funcionando;
* mutations continuam funcionando;
* queries continuam funcionando;
* validações continuam funcionando;
* estados continuam funcionando;
* autenticação continua funcionando;
* permissões continuam funcionando.

O redesign não pode introduzir regressões.

---

# 18. TESTE TODAS AS ROTAS IMPORTANTES

Depois do redesign, faça uma inspeção das páginas existentes e verifique:

```text
rota
↓
renderização
↓
interação
↓
estado
↓
responsividade
↓
console
↓
erros
```

Procure:

* erros JavaScript;
* warnings importantes;
* elementos quebrados;
* overflow;
* conteúdo cortado;
* botões sem função;
* estados inexistentes;
* layout quebrado;
* problemas de scroll;
* problemas de focus;
* problemas em telas pequenas.

---

# 19. NÃO PARE NO PRIMEIRO RESULTADO

Não considere a primeira implementação como final.

Faça várias rodadas de:

```text
Implementar
↓
Renderizar
↓
Criticar
↓
Corrigir
↓
Renderizar novamente
↓
Polir
↓
Testar
```

O objetivo não é apenas “funcionar”.

O objetivo é alcançar uma interface visualmente refinada e tecnicamente sólida.

---

# 20. CRITÉRIO DE QUALIDADE

Antes de finalizar, avalie o sistema como se você fosse:

### Product Designer sênior

Pergunte:

* a hierarquia está clara?
* a navegação é intuitiva?
* o sistema parece profissional?
* existe consistência?
* existe personalidade?
* a interface parece genérica?
* existe excesso de elementos?

### UX Designer sênior

Pergunte:

* o usuário consegue trabalhar rapidamente?
* existem fricções?
* os estados estão claros?
* erros são compreensíveis?
* ações importantes estão claras?
* o sistema reduz carga cognitiva?

### Frontend Engineer sênior

Pergunte:

* os componentes são reutilizáveis?
* a arquitetura está saudável?
* existem duplicações?
* existem renders desnecessários?
* há dependências desnecessárias?
* a interface continua performática?

### QA Engineer

Pergunte:

* todos os fluxos continuam funcionando?
* existem regressões?
* existem problemas visuais?
* existem problemas responsivos?
* existem erros no console?
* existem estados quebrados?

---

# 21. RESULTADO ESPERADO

O resultado final deve transmitir:

```text
MADUREZ
CONFIANÇA
PRECISÃO
EFICIÊNCIA
CLAREZA
SOLIDEZ
PROFISSIONALISMO
CONSISTÊNCIA
```

A interface deve parecer:

> um produto de software profissional, maduro e cuidadosamente projetado.

Não deve parecer:

> um template gerado por IA.

---

# 22. ORDEM DE EXECUÇÃO

Siga aproximadamente esta sequência:

```text
1. Ler REBANHO-360-FRONTEND-SKILLS.md
                ↓
2. Inspecionar o projeto
                ↓
3. Instalar/configurar skills
                ↓
4. Rodar o sistema
                ↓
5. Auditar interface atual
                ↓
6. Mapear todas as páginas/componentes
                ↓
7. Criar/atualizar DESIGN.md
                ↓
8. Redesenhar App Shell
                ↓
9. Redesenhar componentes base
                ↓
10. Redesenhar dashboard
                ↓
11. Redesenhar páginas internas
                ↓
12. Redesenhar tabelas
                ↓
13. Redesenhar formulários
                ↓
14. Revisar estados
                ↓
15. Revisar responsividade
                ↓
16. Revisar acessibilidade
                ↓
17. Revisar performance
                ↓
18. Visual QA no navegador
                ↓
19. Functional QA
                ↓
20. Corrigir problemas
                ↓
21. Nova rodada de screenshots
                ↓
22. Review final
```

---

# 23. RESTRIÇÃO FINAL

**NÃO altere funcionalidades apenas para deixar a interface mais bonita.**

**NÃO remova funcionalidades existentes.**

**NÃO reescreva backend.**

**NÃO altere banco de dados.**

**NÃO altere contratos de API.**

**NÃO introduza mudanças de negócio.**

**NÃO faça refactors de backend fora do escopo.**

Pode modificar profundamente:

* componentes visuais;
* estrutura JSX/TSX;
* CSS;
* Tailwind;
* estilos;
* layouts;
* componentes;
* tokens;
* design system;
* estados visuais;
* animações;
* organização visual;
* responsive behavior;
* acessibilidade;
* arquitetura interna dos componentes de UI.

Desde que o comportamento funcional permaneça preservado.

---

# 24. DEFINIÇÃO DE “PRONTO”

A tarefa só deve ser considerada concluída quando:

```text
✓ interface redesenhada
✓ design system consistente
✓ DESIGN.md criado/atualizado
✓ componentes reutilizáveis
✓ visual profissional
✓ sem aparência genérica de IA
✓ desktop validado
✓ responsividade validada
✓ acessibilidade revisada
✓ performance revisada
✓ screenshots revisados
✓ fluxos principais testados
✓ console sem novos erros relevantes
✓ nenhuma funcionalidade existente quebrada
✓ nenhuma alteração de regra de negócio
✓ QA visual concluído
✓ QA funcional concluído
```

Execute o trabalho de forma autônoma, fazendo o máximo de análise e validação antes de alterar arquivos.

**Prioridade absoluta: preservar o sistema funcional enquanto transforma completamente a qualidade da interface.**
