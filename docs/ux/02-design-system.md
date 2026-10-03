# Design system — Rebanho360

Fonte de verdade **visual** do sistema. Regras de negócio, dados e segurança continuam em [`CLAUDE.md`](../../CLAUDE.md) e [`docs/`](../README.md); a navegação e os fluxos, em [`docs/ux/01-navegacao-e-ui.md`](01-navegacao-e-ui.md). Este arquivo diz **como as coisas ficam**, não o que o sistema faz.

> Escopo: só frontend (templates, CSS, ícones, fontes). Nenhuma regra de negócio, rota, modelo ou contrato mudou na criação deste design system.

---

## 1. Princípio

O Rebanho360 é um instrumento de trabalho, não um site. A interface transmite **precisão, calma e confiança**: muito dado, pouca decoração.

- **Hierarquia antes de enfeite.** Cada tela tem uma ação principal e ela é a única de cor cheia.
- **Número é protagonista.** Tipografia tabular, alinhado à direita, `—` quando falta dado.
- **Identidade vem do logotipo**, não de clichê rural: azul-petróleo, grafite e verde-sálvia.
- **Cor nunca sozinha.** Todo status tem texto e um marcador de forma.
- **Celular é o caso difícil.** Alvo mínimo 44 px, tabela vira cartão, ação principal no rodapé.

Evitar: gradiente decorativo, sombra pesada, glassmorphism, emoji, ícone sem função, cartão dentro de cartão, pílulas em excesso, ilustração.

---

## 2. Tokens

Definidos em [`backend/tailwind.config.js`](../../backend/tailwind.config.js). Os nomes `gray`, `red`, `amber`, `green`, `blue` foram **redefinidos** para a paleta do sistema; use-os normalmente.

### Cor

| Papel | Token | Hex (500/600) | Uso |
|---|---|---|---|
| Marca / ação | `brand-600` | `#1f566b` | Botão primário, link, foco, seleção |
| Marca escura | `brand-950` | `#0a1d27` | Menu lateral, painel de login |
| Positivo | `sage-500…700` | `#58846a` | Confirmado, sucesso, item ativo do menu (barra) |
| Neutros | `gray-50…900` | frio, levemente azulado | Texto, borda, fundo (`gray-50` = fundo da página) |
| Atenção | `amber-100/800` | | Pendência, excluído, estimativa |
| Erro / destrutivo | `red-600…800` | `#ab342d` | Erro, exclusão |

Texto principal `gray-900`; secundário `gray-500` (contraste ≥ 4,5:1 sobre branco); linhas `gray-200`, divisórias internas `gray-100`.

### Tipografia

- **IBM Plex Sans** (400, 500, 600) para interface; **IBM Plex Mono** (400, 500) para **códigos de registro** (`CP-2025/26-0005`, `LT-SFR-003`): rastreabilidade legível, distinguível de texto.
- Fontes **locais** em `static/fonts/` (sem CDN: abre rápido com sinal ruim e não depende de terceiros).
- Corpo 15 px; campo 16 px no celular (evita zoom do iOS) e 15 px no desktop.
- Escala: título de página `text-2xl/600` · seção `text-base/600` · rótulo de card `eyebrow` (12 px, caixa alta, tracking) · apoio `text-sm/xs`.
- Números em tabela e indicadores: `font-variant-numeric: tabular-nums`.

### Espaço, forma e elevação

- Escala de 4 px do Tailwind. Gutter da página: 16 px (celular) · 24 px (sm) · 32 px (lg). Conteúdo até `76rem`.
- Raio: `rounded-md` (6) em controles, `rounded-lg` (8) em superfícies. Selos de status: `rounded` (4), **não pílula**.
- Superfícies são **planas**: borda de 1 px `gray-200`, sem sombra. Sombra (`shadow-float`) só em quem flutua: menu do usuário, toast, painel de contexto, lista do seletor com busca.
- **Barra de rolagem** fina (8 px), sem trilho, só o polegar arredondado; cinza claro no conteúdo e branco translúcido no menu escuro, mais forte ao passar o mouse. Definida em `base` (`scrollbar-width/color`, com fallback `::-webkit-scrollbar` para Safari). Não estilize rolagem por componente. **Exceção única, o menu lateral (`.nav-scroll`):** o espaço da barra fica sempre reservado dos dois lados (`scrollbar-gutter: stable both-edges`) e o polegar só aparece com o mouse em cima (muda a cor, não a largura). Assim, abrir um bloco do menu e surgir a rolagem não encolhe os itens nem faz o menu piscar. O recuo dos itens vem da variável `--nav-inset` (4 px com barra clássica, 8 px em telas de toque, onde a barra é por cima).

### Ícones

Sprite SVG único: [`static/img/icons.svg`](../../backend/static/img/icons.svg) (Lucide, ISC), traço 1,75 px, `currentColor`. Uso: `{% icon "nome" %}` (tag em `core_tags`). Ícone é **sempre** acompanhado de texto ou `aria-label`; é decorativo (`aria-hidden`). Para adicionar um ícone, inclua o `<symbol>` no sprite.

---

## 3. Layout

```
┌ Menu (lg: fixo 256 px; abaixo: gaveta) ┬ Barra superior: Empresa · Safra · Fazenda …… Usuário ┐
│ marca, 7 seções, ≤ 2 níveis           │ ───────────────────────────────────────────────────── │
│ item ativo: fundo + barra sálvia      │ Página: cabeçalho (voltar, título, ações) + conteúdo │
```

- **Contexto fixo no topo** (Empresa · Safra · Fazenda), sempre visível no desktop, numa **barra única** (`.ctx-bar`): três células (`.ctx-cell`) com divisores finos, fundo `gray-50`, que ficam brancas ao passar o mouse e ganham anel por dentro no foco. Safra e Fazenda são o seletor com busca (variante `.cb-ctx`). No celular e tablet vira um botão ("Safra · Fazenda") que abre um painel inferior com a mesma barra empilhada (`.ctx-bar-stack`). O cabeçalho (`.app-header`) é sólido, sem blur, com um fio de destaque quase invisível na base; o avatar leva um anel discreto.
- **Menu** gerado por `{% nav_menu %}` ([`core_tags.py`](../../backend/apps/core/templatetags/core_tags.py)): *Início* fixo no topo e três blocos + Sistema recolhíveis (`.nav-block` / `.nav-section`, `<details>` nativo; abre só o bloco da tela atual); o item ativo é a rota mais específica que casa com o caminho; links que o papel não pode abrir (Auditoria, Usuários) não aparecem.
- **Cabeçalho de página** (`.page-header`): link "voltar" (`.crumb`) → título (`.page-title`) com status ao lado → subtítulo → ações (`.page-actions`) à direita; no celular as ações quebram para baixo.
- **Breakpoints:** `sm` 640 · `md` 768 (tabela real, botões 40 px) · `lg` 1024 (menu fixo, 3 seletores no topo). Alvos de teste: 360×800 · 390×844 · 768×1024 · 1366×768 · 1920×1080.

---

## 4. Componentes

Todos em [`backend/static/css/input.css`](../../backend/static/css/input.css), camada `components`. **Nunca copie HTML de uma tela para outra**: use a classe ou o partial.

| Componente | Classe / partial | Regras |
|---|---|---|
| Botão | `.btn-primary` `.btn-secondary` `.btn-ghost` `.btn-danger` `.btn-danger-outline` · `.btn-sm` | 44 px no celular, 40 px no desktop. **Um** primário por tela. Destrutivo é *outline* até o último passo (confirmação com impacto). |
| Campo | `.field-label` `.field-input` `.field-help` `.field-error` · [`_field.html`](../../backend/templates/partials/_field.html) | Rótulo sempre visível (nunca só placeholder). `*` em obrigatório. Erro ligado por `aria-describedby`, com ícone e texto. |
| Formulário simples | [`_form_page.html`](../../backend/templates/partials/_form_page.html) | Cadastro de 1 tela: cabeçalho + cartão + ações. |
| Formulário de lançamento | `.form-section` (título à esquerda, campos à direita) + `.form-actions` | Seções nomeadas. No celular, ação principal **fixa no rodapé**. Rascunho em `localStorage` (mantido). |
| Cartão | `.card` · `.card-flush` | Só para agrupar conteúdo relacionado. Nada de cartão dentro de cartão. |
| Tabela | `.table` + `.table-stack` dentro de `.table-wrap` | Desktop: tabela, cabeçalho em caixa alta, número à direita (`.num`), linha inteira clicável (`.is-link` + `.row-link`). Celular: cada linha vira cartão — `td.cell-title` (título), `td.cell-status` (ao lado do título), `data-label` (rótulo), `.cell-hide-mobile` (some). Relatório denso é exceção: tabela com rolagem própria. |
| Selo de status | `.badge-confirmada` `-rascunho` `-excluida` `-editada` `-pendencia` `-erro` · `{% status_badge %}` | Cor **e** marcador (círculo, quadrado vazado, losango) **e** texto. Editado mostra a versão: "Editada (v3)". |
| Alerta | `.alert-info` `-success` `-warning` `-danger` | Ícone + texto. `role="alert"` quando for erro. |
| Indicador | `.stats` > `.stat` (`.stat-label` `.stat-value` `.stat-note`) | Faixa única dividida, não parede de cartões. |
| Lista de dados | `.dl` (dt/dd) · `.rows` (span) · `.facts` (grade de cabeçalho) | Rótulo cinza, valor `500`; linha de total em destaque. |
| Estado vazio | [`_empty.html`](../../backend/templates/partials/_empty.html) | Diz o que falta e oferece o próximo passo. |
| Paginação | [`_pagination.html`](../../backend/templates/partials/_pagination.html) | Preserva filtros (`url_pagina`). |
| Filtro por link | `.seg` | `aria-current` marca o ativo. |
| Aviso (toast) | [`toasts.html`](../../backend/templates/partials/toasts.html) | Ícone por nível; erro e aviso ficam 14 s, o resto 7 s; sempre fechável. O ✓/✗ do texto do servidor é removido (`sem_marca`). |
| Menu flutuante | `.menu` `.menu-item` | Fecha com `Esc` e clique fora. O menu do avatar tem cabeçalho (nome, e-mail, papel), **Conta** e **Sair**. |
| Seletor com busca | `.cb-trigger` `.cb-panel` `.cb-option` `.cb-sheet` (gerado por [`combobox.js`](../../backend/static/js/combobox.js)) | **Todo `<select>` do sistema.** O `<select>` real continua no DOM, escondido (`select[data-cb-native]`, ainda focável para o `required`), e um botão toma o lugar dele. Ao abrir mostra **todas** as opções, sem limite; digitar filtra sem diferenciar acento nem caixa e destaca o trecho achado (`mark` em negrito). Teclado: ↑ ↓ Home End PgUp PgDn, Enter escolhe, Esc fecha, digitar com o campo focado já abre a busca. No celular (<640 px) vira folha inferior com linhas de 44 px; a busca só abre o teclado se houver mais de 8 opções. Ao escolher dispara `input` e `change` no select, então HTMX, Alpine e `onchange` funcionam sem mudança. Quem entra depois (swap do HTMX, linha de formset) é melhorado por um `MutationObserver`. Opte por sair com `data-native`. Código novo que restaurar `.value` sem evento chama `campo._cb.sync()`. |
| Botão de informação | `{% info "slug" %}` · `.page-title-row` `.info-btn` · [`_info.html`](../../backend/templates/partials/_info.html) · textos em [`help_content.py`](../../backend/apps/core/help_content.py) | "i" discreto ao lado do título da tela; abre painel (folha inferior no celular, janela no desktop) com *Para que serve*, *Como se liga ao resto do sistema* e *Dúvidas comuns*. Substitui o subtítulo descritivo das telas de lista. **Toda tela de página leva o botão**: lista, formulário, detalhe e relatório, com o mesmo tópico da lista do assunto (o formulário de lote usa o tópico `lote`). Formulários feitos com `_form_page.html` passam `ajuda="slug"`; as telas genéricas (`cadastro_form`, `linhas_form`) recebem `ajuda` da view. Só passos de confirmação (aprovar, recusar, motivo, análise de impacto) ficam de fora, e a lista `ISENTAS` em `test_help_info.py` diz por quê. Tela nova: adicione o tópico em `AJUDA` e use a tag; o teste falha se uma tela não tiver o botão (nem isenção com motivo), se um slug não tiver texto ou se um texto não tiver tela. Descreva o que o sistema **faz**, não o que se pretendia: mudou a regra, mude o texto. Subtítulo que traz contexto dinâmico (safra e fazenda no Início) ou aviso de ação em formulário continua na tela. |

### Estados

- **Foco:** anel de 2 px `brand-500` (`:focus-visible`), em todo elemento interativo; não remover.
- **Hover:** mudança sutil de fundo/borda; nunca só cor do texto.
- **Desabilitado:** 50 % de opacidade + cursor bloqueado.
- **Carregando (HTMX):** `.htmx-request` reduz a opacidade da região recalculada (prévias de custo e de venda) sem mexer no layout. PDF em geração mostra um indicador giratório e atualiza sozinho.
- **Vazio / erro:** sempre com texto específico. Erro de negócio diz o que aconteceu e o caminho; traceback nunca aparece.
- **Sem dado:** `—`, nunca `0` nem `R$ 0,00` (regra 3 do `CLAUDE.md`).

---

## 5. Padrões de página

- **Lista:** cabeçalho com ação primária → filtros (se houver) → `.table-wrap` → paginação. Vazia: `_empty.html`.
- **Detalhe:** voltar → código (mono) + selos → ações (primária, editar) → `.facts` → blocos em 2–3 colunas (`.dl`/`.rows`) → "o que este registro gerou" → zona de exclusão separada por linha, no fim.
- **Lançamento:** `.form-section`s; prévia de indicadores atualizada por HTMX logo abaixo dos valores; salvar rascunho + confirmar.
- **Exclusão:** análise de impacto antes ("Isto vai desfazer", dependentes, bloqueios com o caminho), motivo obrigatório, cascata só com confirmação explícita.
- **Painel inicial:** pendências primeiro (cada uma é um link com exemplos), depois rebanho, faixa de indicadores da safra e últimos lançamentos. Sem gráfico: os gráficos moram no **Dashboard** ([seção 13](#13-dashboard-analítico)).

---

## 6. Acessibilidade

- Contraste ≥ 4,5:1 para texto; foco visível; navegação completa por teclado; "Ir para o conteúdo" no topo.
- `<button>` para ação, `<a>` para navegação; `<label>` real em todo campo; `aria-current="page"` no menu; `aria-live` nas prévias; `role="alert"` em erro.
- Cor nunca sozinha (ver selos). `prefers-reduced-motion` desliga transições e animações.
- Tabela mantém `<th scope="col">` mesmo quando vira cartão (o cabeçalho fica só para leitor de tela).

## 7. Movimento

Só onde ajuda a entender: gaveta do menu (200 ms), abrir/fechar bloco do menu (200 ms, só onde há `::details-content`), painel de contexto, toast (150–200 ms), menu do usuário e lista do seletor (100 ms), folha do seletor no celular (180 ms). Tudo some com `prefers-reduced-motion`. Sem animação de entrada de página, sem parallax.

---

## 8. Como trabalhar com o CSS

```bash
# Tailwind standalone (sem Node) — mesmo script do build de produção
cd backend && sh bin/build_css.sh      # gera static/css/output.css
```

`output.css` é gerado e **não é versionado** (ver `.gitignore`): compile depois de mexer em `input.css`, em `tailwind.config.js` ou em classes novas nos templates. O build de produção (Dockerfile) recompila sozinho.

Checklist antes de dar uma tela por pronta (além do *Definition of Done* do `CLAUDE.md`): hierarquia clara · um botão primário · estados vazio/erro/sucesso · 360 px sem rolagem horizontal · tabela vira cartão · foco por teclado · sem emoji · códigos em mono · números alinhados.

## 9. Estáticos em produção

CSS, fontes e ícones precisam chegar ao navegador. Em produção o Django **não** serve `/static/`: o `deploy/deploy.sh` publica o `collectstatic` em `STATIC_HOST_DIR` e o Nginx do host entrega (vhost de exemplo em [`deploy/nginx.conf.example`](../../deploy/nginx.conf.example)). Tela sem estilo em produção quase sempre é isso. Detalhes em [`docs/arquitetura/02-infra-e-deploy.md`](../arquitetura/02-infra-e-deploy.md#estáticos-css-fontes-ícones). Decisão: [ADR 0007](../arquitetura/adr/0007-design-system-proprio-sobre-tailwind.md).

## 10. Testes e markup

Alguns testes leem trechos do HTML. Não os quebre sem ajustar o teste: `sm:hidden` e `hidden sm:block` em `reports/_tabela.html`; `Custo por @ (peso vivo)</span> <span>—</span>` em `purchases/purchase_detail.html`; textos como `Nada pendente hoje`, `Custo/@ (lotes encerrados)`, `Isto vai desfazer`, `dependem deste`, `PDF pronto`, `Gerando o PDF`, `Exportação pronta`, `Cancelar exportação` e `hx-trigger="every 2s"`.

## 11. Telas do financeiro (Fase 4)

Nasceram dos componentes acima, sem classe nova. Convenções:

- **Selo de situação do título** (`{% titulo_selos %}`, em `apps/finance/templatetags`): a pagar = `.badge-rascunho`, programado/aprovado = `.badge-editada`, pago em parte = `.badge-pendencia`, pago = `.badge-confirmada`, **Vencido** = `.badge-erro` ao lado do selo de situação, cancelado = `.badge-excluida`. Cor nunca sozinha: todo selo tem texto e marcador.
- **Resumo de vencimentos** no topo de contas a pagar/receber: faixa `.stats` (vencidos em vermelho **e** com a contagem de títulos).
- **Telas de decisão** (programar, aprovar, baixar) abrem com o resumo do título (`finance/_resumo_titulo.html`) e têm uma ação primária só.
- **Bloqueio com caminho:** a tela de impacto mostra o link ao lado do motivo (`Bloqueio(texto, url, rótulo)`).
- **Dado bancário:** número inteiro só para quem pode ver; no seletor, só o final (`•••••5-4`).
- **Telas do 2FA** (`registration/2fa_*.html`) usam o layout **sem menu** (`layout_minimo`), como o login.

## 12. Tela de exportação

Nasceu dos componentes acima, sem classe nova. Convenções: formulário em `.form-section` (o que exportar · formatos · filtros), com contagem por conjunto à direita de cada caixa e um resumo vivo ("12 selecionados · 8.420 registros", Alpine); andamento em fragmento HTMX (`exports/_estado.html`, `every 2s` só enquanto roda) com **barra** (`role="progressbar"`, texto de percentual ao lado: cor nunca sozinha) e tabela item a item com selo de situação (aguardando = `.badge-rascunho`, em andamento = `-editada`, pronto = `-confirmada`, com erro = `-erro`). Regras: [regra 10](../regras-negocio/10-exportacao-de-dados.md).

## 13. Dashboard analítico

Decisão de 03/10/2026: a análise ganhou tela própria (**Dashboard**, abaixo de *Início*), com gráficos. Regras e abas em [`docs/regras-negocio/11`](../regras-negocio/11-dashboard-analitico.md). Nasceu dos componentes acima; as classes novas (`.dash-*`, `.kpi*`, `.delta*`, `.insight*`, `.mark*`, `.cell-bar`) estão em `input.css`, no fim da camada `components`.

**Biblioteca.** ECharts 5.5 (Apache-2.0), **hospedado** em `static/vendor/echarts.min.js`, sem CDN (mesma regra das fontes: abre rápido com sinal ruim e não depende de terceiros). Só a tela do Dashboard o carrega. Justifica-se porque mapa de calor, árvore, Sankey, calendário e cascata não são viáveis à mão; não é biblioteca por moda.

**Divisão de trabalho.** O servidor monta a especificação do gráfico (`bi/specs.py`: dados já calculados, rótulos, tabela equivalente); `static/js/dashboard.js` só desenha. Nada é recalculado no JavaScript e o template não calcula.

**Cor.**

| Papel | Valores | Regra |
|---|---|---|
| Categórica | `#1a78a0 #eb6834 #1baf7a #eda100 #e87ba4 #008300 #4a3aa7 #e34948` | Validada com o validador da skill `dataviz` (fundo branco): faixa de luminosidade, croma, separação para daltonismo e piso de visão normal passam. **Ordem fixa, nunca cíclica**; a cor segue a entidade (a mesma fazenda tem a mesma cor em todo gráfico). Três cores ficam abaixo de 3:1 no branco — por isso há rótulo, legenda e tabela equivalente em todo gráfico (alívio obrigatório). Série além de 8 vira "Outros" ou ranking. |
| Magnitude (mapa de calor, árvore, calendário, etapas) | petróleo da marca, clara → escura | Uma matiz só. Etapas ordenadas usam a rampa **ordinal** (luz do extremo claro ≥ 2:1). |
| Polaridade (lucro × prejuízo, aumento × redução) | `#2f6d82` ↔ `#c4423a`, ponto neutro cinza | Azul ↔ vermelho (seguro para daltonismo; verde ↔ vermelho não é). Sempre com o valor e o sinal escritos. |
| Estado (KPI, tabela, leitura) | sálvia · âmbar · vermelho da marca | Reservada para estado; **sempre com ícone e texto**. |
| Texto | tokens de texto (`gray-900/600/500`) | **Texto nunca usa a cor da série.** |

**Marca do gráfico.** Barra de até 24 px com ponta arredondada; linha de 2 px; marcador final de 8 px com anel da cor da superfície; grade em fio contínuo e discreto; abertura de 2 px entre fatias e barras empilhadas; rótulo só no que importa (ponta, extremo), nunca em todo ponto; legenda sempre que há 2 séries ou mais; área em ~10% de opacidade quando é uma série só.

**Um eixo só.** Nunca dois eixos de valor: a escala do segundo é arbitrária e inventa correlação. Duas grandezas → dois gráficos. Por isso o "Pareto" é um ranking de barras com a participação na tabela, e a soma acumulada é um gráfico à parte.

**Interação.** Cruz de leitura na linha/barra vertical; tooltip por marca em barra e célula (valor em destaque, nome ao lado, chave em traço); alvo de toque ≥ 24 px nos pontos de dispersão (camada transparente maior); legenda clicável. **Tooltip nunca é o único caminho**: o botão de tabela de cada cartão mostra os mesmos dados, e o de download baixa o gráfico em PNG. O botão **Texturas nas cores** acrescenta hachuras (45° e 135°) a cada série, para quem não distingue cores; é opcional e a escolha fica no navegador. Texto de tooltip entra por escape (nome vem de dado).

**KPI.** Rótulo em caixa alta, valor grande (sem algarismo tabular), nota, seta de variação (ícone + texto + leitura para leitor de tela), mini-gráfico de linha desenhado no servidor (SVG) e, quando há estado, ícone e texto ao lado da borda colorida. A explicação de como é calculado abre no "i" do cartão.

**Tabela de análise.** `.table` com barra de dados dentro da célula numérica (`.cell-bar`), marca condicional **com texto** (`.mark`) e código de registro em mono. É relatório denso: tem rolagem própria (exceção prevista na seção 4), com cabeçalho fixo.

**Grade.** 12 colunas no desktop, 1 no celular. As larguras pedidas por gráfico são só uma dica: `specs.reorganizar` fecha as linhas para nunca sobrar buraco ao lado de um cartão.

**Armadilhas.** (1) Classe montada por interpolação no template (`kpi-{{ estado }}`) não é vista pelo Tailwind: está na `safelist` de `tailwind.config.js`; as classes de largura vêm do Python e o diretório `apps/dashboards/bi/` está no `content`. (2) Não dê ao contexto do template o nome `painel`: `partials/context_bar.html` o usa para escolher a versão empilhada do celular (o Dashboard usa `quadro`). (3) `float` no template é localizado em pt-BR ("93,0") e quebra atributo SVG: formate no Python. (4) O painel de ajuda ("i") é teleportado para o `<body>` pelo Alpine; com `hx-push-url` o retrato do histórico do HTMX o copiaria sem escopo — `dashboard.js` o tira do retrato e o devolve (`data-info-dialog`).

**Checklist de gráfico novo:** forma certa para o trabalho do dado (ou nem é gráfico: cartão de número) · um eixo · cor pelo papel · tabela equivalente · estado vazio · 360 px sem rolagem horizontal · rodou o validador se a paleta mudou.

## 14. Pendente neste design

Páginas 403/404/500 próprias (com código de referência para erro inesperado) · máscara de dinheiro · modo escuro. Ver [`docs/ux/01-navegacao-e-ui.md`](01-navegacao-e-ui.md#implementação-do-redesign-01102026).
