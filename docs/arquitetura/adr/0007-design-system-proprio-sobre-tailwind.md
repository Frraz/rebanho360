# ADR 0007 — Design system próprio sobre Tailwind, com ícones e fontes locais

**Data:** 2026-10-01 · **Status:** Aceita

## Problema

Ao fim da Fase 3 a interface funcionava, mas parecia protótipo: cada tela montada com classes soltas, menu simples, contexto escondido no celular, emoji como ícone, tabelas feitas de cartões. O sistema vai ser usado por gente de campo (celular, sinal ruim) e de escritório (volume), e precisa transmitir confiança. Como evoluir a interface sem reescrever o frontend e sem criar um segundo sistema para manter?

## Decisão

**Design system próprio, em cima do Tailwind e dos templates Django que já existem.** Documentado em [design system](../../ux/02-design-system.md).

- **Tokens** em `tailwind.config.js`: paleta derivada do logotipo (azul-petróleo, grafite, verde-sálvia). As escalas `gray`, `red`, `amber`, `green` e `blue` foram *redefinidas* — os templates já usavam esses nomes, então o sistema inteiro mudou de tom sem reescrever classe por classe.
- **Componentes** em `static/css/input.css` (`.btn-*`, `.card`, `.table`, `.badge-*`, `.alert-*`, `.field-*`, `.stats`…) e **partials** de template (`_field`, `_form_page`, `_empty`, `_pagination`). Nunca copiar HTML de uma tela para outra.
- **Ícones** num sprite SVG único (`static/img/icons.svg`, Lucide, licença ISC), usados por `{% icon "nome" %}`. Sem emoji.
- **Fontes locais** (IBM Plex Sans para a interface, IBM Plex Mono para códigos de registro), em `static/fonts/`.
- **Status nunca só por cor**: todo selo tem texto e um marcador de forma.

## Alternativas descartadas

**Biblioteca de componentes (shadcn/ui, Flowbite, DaisyUI…).** As boas dependem de React ou de um build de Node que o projeto deliberadamente não tem ([ADR 0001](0001-monolito-modular-django.md)); as que não dependem trazem um visual de "template pronto" que o redesign precisava evitar e mais um CSS para entender e atualizar.

**Reescrever o frontend em React/Vue.** Duplicaria a modelagem e o estado, pelo mesmo motivo do ADR 0001, para resolver um problema que é de organização visual, não de tecnologia. As skills de React/Vercel sugeridas no briefing do redesign não se aplicam a este stack e não foram usadas.

**Ícones por CDN, fonte de ícones ou emoji.** CDN é dependência externa e pedido extra com sinal ruim; fonte de ícones carrega o conjunto inteiro e falha sem aviso; emoji varia por aparelho e foi rejeitado explicitamente como linguagem de um sistema que lida com dinheiro.

**Google Fonts.** Mesma objeção do CDN, mais envio do acesso a terceiro. As fontes pesam ~100 KB no total e ficam em cache.

**Gradientes, glassmorphism, sombras, ilustração rural.** Decoração sem função num instrumento de trabalho. A personalidade vem da tipografia, da cor e da densidade dos dados. Sombra só em quem flutua (menu, aviso, painel).

## Consequências

**Boas:** uma linguagem visual só; tela nova nasce das mesmas classes e partials; troca de tom (ou de marca) é editar tokens; tudo funciona offline depois do primeiro carregamento; sem dependência nova de runtime.

**Ruins:** o `output.css` é gerado e **não versionado** — esquecer de compilar abre a tela sem estilo (o `deploy/local.sh` e o Dockerfile de produção cobrem isso); em produção o Nginx precisa servir `/static/` (ver [infra](../02-infra-e-deploy.md#estáticos-css-fontes-ícones)); alguns testes dependem de trechos de markup (`sm:hidden` e `hidden sm:block` na tabela dos relatórios; `Custo por @ (peso vivo)</span> <span>—</span>` no detalhe da compra), e mexer neles exige ajustar o teste junto.

**A disciplina que sustenta:** o [design system](../../ux/02-design-system.md) é a fonte de verdade. Mudou um componente, mudou o documento no mesmo commit.
