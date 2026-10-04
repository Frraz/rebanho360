# Navegação e interface

## Quem usa, e onde

| Perfil | Dispositivo | Situação |
|---|---|---|
| Campo | Celular, muitas vezes pequeno | Em pé, no curral, sinal ruim, pressa |
| Escritório | Notebook | Sentado, lançando em volume |
| Gestor | Notebook ou celular | Consultando, decidindo |

O campo é o mais exigente e o mais fácil de esquecer. **Se o lançamento no celular for ruim, ele volta para o WhatsApp** — e o sistema perde o dado na origem.

## Contexto fixo

**Toda tela abre no topo.** Nunca no meio nem no fim da página, e sem "subir sozinha" depois: não se põe `autofocus` em campo fora das telas de entrada (login e segundo fator), `.focus()` programático usa `{ preventScroll: true }`, e o `base.html` guarda a rede de segurança (rolagem manual, `scrollTo(0, 0)` ao carregar e ao voltar do cache, e o htmx rola `instant`). Troca de aba do dashboard não rola a página (`show:none`).

No topo, sempre:

```
Rebanho360   Empresa ▾   Safra 2025/2026 ▾   Fazenda: Todas ▾        Warley ▾
```

É o eixo mental do usuário e economiza filtro em toda tela. A seleção persiste na sessão. No celular, colapsa em um botão que abre um painel.

**Como ficou (redesign, 01/10/2026):** no desktop (≥ 1024 px) os três seletores ficam sempre visíveis na barra superior, cada um com rótulo pequeno (EMPRESA, SAFRA, FAZENDA). Abaixo disso a barra mostra um botão "Safra · Fazenda" com a seleção atual, que abre um painel inferior com os três — antes, no celular, o contexto não aparecia em lugar nenhum. Usuário fica num menu no canto, com **Conta** e **Sair** (a Conta reúne perfil, senha e segundo fator; ver [regra 09](../regras-negocio/09-usuarios-e-solicitacao-de-acesso.md#conta-o-próprio-usuário)). **Refino de 02/10/2026:** os três contextos viraram uma barra única com divisores (`.ctx-bar`), o cabeçalho é sólido e todo `<select>` do sistema virou o seletor com busca (ver o [design system](02-design-system.md)).

## Menu

```
ENTRADA                          cadastros do sistema
  Empresa / Propriedades         Empresas · Unidades · Safras · Fazendas · Áreas / Pastos
  Parceiros
  Rebanho / Produtos / Lotes     Categorias · Raças · Lotes
  Comercial                      Classes de carcaça · Tributos e taxas · Regras de comissão
  Custos / Centros de Custo

MOVIMENTAÇÕES                    operação diária
  Compra / Compromisso           Compras · Compromissos
  Programação / Embarque         (relatório de programação, até haver lista de viagens)
  Recebimento / Acerto           Acertos
  Rebanho / Manejo               Posição · Movimentações · Pesagens · Vendas e abates · Conciliação
  Financeiro / Fechamento        Custos · Contas a pagar · Contas a receber · Pagamentos

RELATÓRIOS E ANÁLISE             visão gerencial
  Dashboard / Resultados         Início
  Compras / Histórico
  Programações / Logística
  Acertos / Financeiro
  Rebanho / Fazenda

SISTEMA                          o que a imagem não prevê
  Todos os relatórios · Documentos gerados · Importações · Exportações · Auditoria · Usuários e acessos
```

Lateral fixa no desktop, drawer no celular. **Bloco → grupo → item**, como no desenho do escopo (`docs/fontes/imagem.jpeg`); grupo de um item só aparece sem subtítulo. Programação/Embarque e Recebimento ainda não têm lista própria: viagens e recebimentos abrem pelo compromisso (lacuna na [matriz de alinhamento](../fluxos/04-alinhamento-ao-doc-funcional.md)).

**Fase 4:** a seção *Financeiro* só aparece para quem vê títulos. O segundo fator passou a morar na página *Conta* (02/10/2026); `/contas/2fa/` em GET redireciona para lá. As telas do 2FA usam layout **sem menu** (quem ainda não provou o segundo fator não clica no sistema).

**Como ficou:** menu escuro (azul-petróleo) com ícone por item, em **3 blocos como no desenho do escopo** (Entrada, Movimentações, Relatórios e Análise, cada um com 5 grupos — `docs/fontes/imagem.jpeg`) mais um bloco Sistema. **Organização (02/10/2026):** cada bloco é recolhível (`<details>` nativo, sem JS) e só abre sozinho o bloco da tela atual — eram ~40 links sempre abertos; *Início* fica fixo no topo, fora dos blocos; o subtítulo de grupo só aparece quando o bloco tem mais de um grupo e o grupo mais de um item; cada link tem ícone próprio. Financeiro e o ciclo de compra só aparecem para quem pode vê-los, fixo a partir de 1024 px e gaveta abaixo disso (fecha com `Esc` e ao tocar fora). O item ativo é a rota mais específica que casa com o endereço (`/compras/12/` acende "Compras"; "Posição" não acende "Movimentações"). Link que o papel não pode abrir não aparece — hoje, Auditoria (só `ADMIN`) e Usuários e acessos (só `ADMIN`, com a contagem de pedidos de acesso pendentes ao lado); a barreira de verdade continua na view. O menu é montado por `{% nav_menu %}` em `apps/core/templatetags/core_tags.py`.

## Tela inicial

Responde "o que preciso fazer hoje?", não é enfeite.

```
┌─ PENDÊNCIAS ───────────────────────────────────────────┐
│ ⚠ 3 transferências sem entrada correspondente          │
│ ⚠ 12 custos sem centro de custo                        │
│ ⚠ 2 lotes sem pesagem há mais de 90 dias               │
│ ⚠ 1 venda sem peso de carcaça                          │
└────────────────────────────────────────────────────────┘

┌─ REBANHO ──────────┬─ SAFRA 2025/2026 ─────────────────┐
│ 1.954 cabeças      │ Comprado    954 cb  R$ 2.457.752  │
│ 5 fazendas         │ Vendido     354 cb  R$ 2.298.586  │
│ 14 lotes abertos   │ Custos              R$ 1.046.908  │
│ Entradas mês  126  │ Custo/cabeça        R$     536    │
│ Saídas mês     81  │ Custo/@                    —      │
└────────────────────┴───────────────────────────────────┘

ÚLTIMOS LANÇAMENTOS
15/04  Compra CP-2025/26-0013 · 126 cb · São Francisco   Warley
12/04  Abate VD-2025/26-0003  ·  81 cb · Coperfrigu      Maria
```

Pendências em primeiro lugar. O gráfico bonito vem depois — e só se for usado.

**Layout atual:** pendências à esquerda (cada uma é uma linha-link com até 4 exemplos) e o bloco do rebanho à direita; abaixo, a faixa de indicadores da safra (comprado, vendido, custos, custo/cabeça, custo/@) e a tabela de últimos lançamentos. Um único bloco de números dividido em células, em vez de uma parede de cartões.

Note o `Custo/@` como "—": não há peso de carcaça em todas as vendas ainda. Melhor que um número inventado.

**Como ficou (Fase 3):** as sete regras de pendência são transferência sem contrapartida (as `TRANSF.` da planilha sem par), custo sem centro (linhas de custo ainda em prévia), lote sem pesagem há mais de 90 dias, venda sem carcaça, lote a saldo zero ainda aberto, mortalidade acima do normal e rendimento fora da faixa. Cada uma é um link com até 4 exemplos. "Custos" **não inclui** o que a compra gera (já está em "Comprado"); `Custo/cabeça` = custos ÷ rebanho atual; `Custo/@` é o dos lotes **encerrados** na safra, do mesmo serviço da tela do lote, com o motivo quando é "—". Sem gráfico: o roadmap manda só se mudar decisão, e nenhum mudou.

**Como ficou (Fase 4):** duas regras novas, só para quem pode vê-las: **título a pagar vencido** (com o total) e **pagamento programado aguardando aprovação** (só para quem aprova). Cada uma é um link para a lista já filtrada.

## Responsividade

Mobile first de verdade. Alvos: 360×800 · 390×844 · 768×1024 · 1366×768 · 1920×1080.

### Tabela no celular

Não rola na horizontal. Vira cartão:

```
Desktop
┌──────────┬────────────┬──────────┬──────────┬──────────┐
│ Data     │ Tipo       │ Categoria│ Qtd      │ Fazenda  │
├──────────┼────────────┼──────────┼──────────┼──────────┤
│ 15/04/26 │ COMPRA     │ Machos…  │ 126      │ São Fran…│
└──────────┴────────────┴──────────┴──────────┴──────────┘

Celular
┌─────────────────────────────────┐
│ 15/04/2026          [ COMPRA ]  │
│ Machos Desm. até 12m            │
│ 126 cabeças · São Francisco     │
└─────────────────────────────────┘
```

Exceção: relatório denso, que fica em container com `overflow-x: auto` — decisão consciente, não descuido.

**Como ficou:** `.table` + `.table-stack` (ver [design system](02-design-system.md#4-componentes)). O mesmo `<table>` serve os dois: no celular cada linha vira um cartão com o código na primeira linha, o status ao lado do código e os demais campos com o rótulo da coluna; colunas secundárias podem sumir no celular. Linha clicável no desktop (o link do código cobre a linha toda). Os relatórios (`reports/_tabela.html`) mantêm a estrutura própria cartões/tabela por serem a exceção acima.

### Formulário de campo

Uma coluna · rótulos acima · botão com ao menos 44 px de altura · teclado numérico em campo numérico · ação principal fixa no rodapé · **rascunho salvo em `localStorage`** para que sinal caindo não apague o que foi digitado.

**Como ficou:** formulários de lançamento (movimentação, compra, venda) em seções com título e descrição (`.form-section`): título à esquerda e campos à direita no desktop, uma coluna no celular. Campo obrigatório leva `*`; erro aparece abaixo do campo, com ícone, e é ligado a ele por `aria-describedby`. As prévias de custo e de venda (HTMX) ficam logo abaixo dos valores. Os formulários de correção reaproveitam os mesmos campos e acrescentam a seção "Motivo da correção".

```
┌─────────────────────────────┐
│ ← Registrar movimentação    │
├─────────────────────────────┤
│ Tipo                        │
│ [ Morte              ▾ ]    │
│ Data                        │
│ [ 15/04/2026           ]    │
│ Fazenda                     │
│ [ São Francisco      ▾ ]    │
│ Lote                        │
│ [ LT-SFR-004         ▾ ]    │
│ Categoria                   │
│ [ Machos Desm. até…  ▾ ]    │
│ Quantidade                  │
│ [ 1                    ]    │
│ Motivo *                    │
│ [                      ]    │
├─────────────────────────────┤
│ [       Registrar       ]   │
└─────────────────────────────┘
```

## Componentes

> A especificação visual de cada componente (classes, estados, regras de uso) está em [design system](02-design-system.md). Esta seção lista o que existe; aquela diz como fica.

Botão · input · select · **combobox com busca** · date picker · input de dinheiro (máscara pt-BR, `Decimal` no servidor) · input de quantidade · badge de status · card de indicador · tabela responsiva · paginação · filtros em drawer · modal · toast · confirmação com impacto · timeline · empty state · skeleton · alerta de pendência.

Um lugar só. Nunca copiar HTML de uma tela para outra.

## Autocomplete, nunca select gigante

Parceiro, lote, fazenda, categoria e centro de custo usam busca via HTMX, com informação suficiente para distinguir semelhantes:

```
[ secchi                                    ]
  WALDEMAR SECCHI · 275.974.740-91 · Alvorada-TO
  WALDEMAR SECCHI FILHO · 812.334.120-04 · Gurupi-TO
```

## Status e cor

Cor **nunca sozinha** — sempre com texto ou ícone.

| Estado | Cor | Marcador | Texto |
|---|---|---|---|
| Rascunho | cinza | quadrado vazado | Rascunho |
| Confirmada | verde-sálvia | círculo cheio | Confirmada |
| Excluída | âmbar, riscado | losango | Excluída |
| Editada | azul-petróleo | quadrado | Editada (v3) |
| Pendência | âmbar | losango | Pendente |
| Erro | vermelho | losango | Erro |

O marcador é desenhado em CSS no próprio selo; **nenhum selo usa emoji ou símbolo de texto** (✓, ⚠, ✕). Alertas e avisos usam ícone do sprite (`{% icon %}`) ao lado do texto.

## Feedback

```
✓ Compra confirmada. 126 cabeças deram entrada no lote LT-SFR-014.
```

Diz o que aconteceu, não só que deu certo.

O texto das mensagens do servidor continua começando com "✓ …"; o aviso (toast) remove esse símbolo (filtro `sem_marca`) e mostra um ícone de nível no lugar, para não duplicar. Erro e aviso ficam na tela 14 s, o resto 7 s, e todo aviso pode ser fechado.

Erro de negócio é específico:
```
Saldo insuficiente: há 12 cabeças de Machos 13 a 24 meses no Baixão,
foram informadas 20.
```

Erro inesperado nunca mostra traceback:
```
Ocorreu um erro inesperado.
Código de referência: ABC-123456
```

## Editar e excluir

Toda ação é editável e excluível ([regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md)). A interface precisa deixar claro **o que vai ser desfeito** antes de desfazer.

### Análise de impacto, sempre antes

```
┌─────────────────────────────────────────────────┐
│ Excluir compra CP-2025/26-0013                  │
├─────────────────────────────────────────────────┤
│ Isto vai desfazer:                              │
│   · entrada de 126 cabeças no lote LT-SFR-014   │
│   · R$ 388.080,00 em DESPESA GADO               │
│   · o lote LT-SFR-014                           │
│                                                 │
│ ⚠ 2 registros dependem desta compra:            │
│   · Pesagem 12/11/2025 · 126 cb                 │
│   · Venda VD-2025/26-0004 · 81 cb               │
│                                                 │
│ Motivo *                                        │
│ [___________________________________________]   │
├─────────────────────────────────────────────────┤
│        [ Cancelar ]   [ Excluir em cascata ]    │
└─────────────────────────────────────────────────┘
```

Nunca um "Tem certeza?" genérico. O usuário precisa ver a lista.

Quando há bloqueio, a tela diz **o caminho**, não só o não:

> **Não é possível excluir esta compra.**
> O lote LT-SFR-014 foi vendido na VD-2025/26-0004, e o pagamento dessa venda já foi baixado em 20/04/2026.
> Para prosseguir, desfaça antes a baixa do pagamento.   `[ Ir para o pagamento ]`

### Versão visível no registro

Registro editado mostra a versão e dá acesso ao histórico:

```
Compra CP-2025/26-0013    [ Confirmada ]  [ Editada (v3) ]

   Última alteração: 14/10/2026 09:15 por Maria
   Motivo: "Contagem corrigida no curral"          [ ver histórico ]
```

Registro excluído não some da lista — aparece riscado, com filtro "Mostrar excluídos" desligado por padrão, e botão **Restaurar** para quem tem permissão.

### Console de auditoria

Em `GESTÃO → Auditoria`, para `ADMIN`. Filtro por usuário, ação, entidade, período e IP; diff campo a campo; cascata agrupada num único item; restaurar direto do evento; exportar CSV.

Ação destrutiva informa o impacto antes de executar — ver [seguranca/01](../seguranca/01-seguranca.md#proteção-contra-mau-uso).

## Após salvar, sugerir o próximo passo

```
✓ Compra confirmada.

Próximos passos:
  → Registrar pesagem de entrada
  → Lançar frete
  → Ver o lote LT-SFR-014
```

O usuário não deve ter que lembrar onde fica a próxima tela.

## Acessibilidade

Contraste mínimo 4.5:1 · foco visível · `<label>` de verdade, não placeholder · erro associado ao campo por `aria-describedby` · navegação por teclado · `<button>` para ação e `<a>` para navegação · texto mínimo de 16 px em campo (evita zoom automático no iOS).

## O que evitar

Excesso de gradiente e sombra · tela superlotada · ícone sem legenda · texto pequeno · animação desnecessária · modal onde a página resolve · **gráfico que não muda decisão nenhuma**.

## Implementação do redesign (01/10/2026)

Feito antes da Fase 4, só no frontend. Regra de negócio, rotas, modelos e contratos não mudaram; os testes que dependiam de trechos de texto continuam passando. O que existe e como se usa está em [design system](02-design-system.md).

**Verificado em navegador real** (Playwright/Chromium) em 360×800 e 1366×768, em todas as rotas do menu, formulários, detalhes e telas de exclusão: nenhuma rolagem horizontal, nenhum erro de console. Também conferidos: gaveta do menu, painel de contexto, menu do usuário, aviso de sucesso e erro de validação.

**Do que esta especificação pedia e ainda não existe** (decisão consciente — só entra quando um uso real pedir):

| Item | Situação |
|---|---|
| ~~Combobox com busca para parceiro, lote, categoria, centro de custo~~ | **Feito em 02/10/2026** para todo `<select>` (`static/js/combobox.js`): lista completa ao abrir, filtro ao digitar, folha inferior no celular. A lista de Parceiros segue com a busca por HTMX |
| Máscara de dinheiro pt-BR no campo | Campo numérico comum; `Decimal` no servidor |
| Filtros em drawer | Filtros ficam num cartão acima da lista |
| Skeleton de carregamento | Usa só o estado `htmx-request` (opacidade) nas prévias |
| Modal | Nenhuma tela usa; a página resolve (análise de impacto é uma página) |
| Excluído riscado na lista, com "Mostrar excluídos" desligado por padrão | Compras, vendas e custos têm filtro por Situação (inclui Excluídas); "Restaurar" fica no detalhe do registro e na auditoria |
| Páginas de erro 403/404/500 próprias, com código de referência | Ainda são as padrão do Django — **pendente** |
| ~~Dark mode~~ | **Feito em 03/10/2026**: tema por usuário, escolhido só em Conta › Aparência. Ver [design system, seção 14](02-design-system.md#14-tema-escuro) |
