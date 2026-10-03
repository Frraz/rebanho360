# Rebanho360 — Visão geral

## O problema

A operação é controlada hoje por uma planilha Excel (`CONTROLE PASTO PADRÃO SÃO FRANCISCO — SAFRA 25-26`, 17 abas). Ela funcionou até aqui, mas chegou ao limite:

- **O saldo do rebanho não fecha.** Na aba `GERAL`, há 140 transferências de saída sem nenhuma transferência de entrada correspondente — o consolidado das fazendas fica em **−140 cabeças**.
- **Cada fazenda é uma aba copiada à mão.** São Francisco, Goiano, Baixão, Morada do Boi e São José do Grotão têm a mesma estrutura replicada. Mudar a regra significa mudar em cinco lugares.
- **`#DIV/0!` por toda parte.** As abas `COMPRA DE GADO`, `VENDAS` e `ADF E COMPRAS` têm centenas de linhas de erro onde ainda não há dado. Falta de informação aparece como erro de cálculo, não como pendência.
- **Números derivados são digitados.** Peso médio, rendimento de carcaça, valor por cabeça e valor por arroba estão gravados como valores — e em pelo menos um caso divergem da própria fórmula ao lado.
- **Pesagens individuais em oito blocos paralelos.** A aba `PESAGENS E CONFERENCIA` repete `(data, brinco, peso, movimentação)` em oito conjuntos de colunas lado a lado, porque não havia como empilhar.
- **Uma pessoa por vez.** Não há como o campo lançar uma morte no celular enquanto o escritório fecha o custo do mês.

## O que o sistema resolve

Substituir essa planilha por um sistema onde:

1. **O saldo do rebanho é consequência dos eventos, nunca um campo digitado.** Se nada foi lançado, nada mudou. Se uma transferência saiu, ela entrou em algum lugar — por construção.
2. **Todo número derivado é calculado por um serviço testado.** Peso médio, GMD, rendimento, custo por arroba. Divisor zero vira "pendente", não `#DIV/0!`.
3. **Custo e resultado saem por fazenda, lote, categoria e safra** sem montar tabela dinâmica à mão.
4. **Campo e escritório trabalham ao mesmo tempo**, cada um enxergando apenas as fazendas que lhe cabem, com registro de quem fez o quê.

## Para quem

Mais de 10 pessoas, entre campo e escritório, em várias fazendas.

| Papel | O que faz no sistema |
|---|---|
| `ADMIN` | Configuração, usuários, permissões, cadastros estruturais |
| `GESTOR` | Enxerga tudo, aprova, analisa resultado |
| `ESCRITORIO` | Lança custos, compras, vendas, concilia |
| `CAMPO` | Lança movimentação de rebanho e pesagem, no celular |
| `FINANCEIRO` | Títulos, pagamentos, baixas (Fase 4). Segundo fator (TOTP) opcional e recomendado |
| `CONSULTA` | Só leitura |

Acesso a dados é limitado por **fazenda**, não só por papel — quem cuida do Baixão não vê o Goiano.

## Escopo

### O sistema faz

- Cadastros: empresa, unidade, safra, fazenda, área/pasto, parceiros, categorias animais, lotes, centros de custo
- Rebanho por movimentações, com saldo por fazenda / lote / categoria / data
- Compra de gado com entrada automática no rebanho e no custo
- Venda e abate com rendimento de carcaça
- Pesagens de lote (e preservação dos dados de brinco existentes)
- Custos por centro de custo, classe, fazenda e safra
- Indicadores: custo/cabeça, custo/kg, custo/@, GMD, @ produzida, quebra
- Relatórios filtráveis, exportáveis em PDF e CSV/XLSX
- Importação das planilhas atuais com validação linha a linha
- **Financeiro (Fase 4):** títulos a pagar e a receber gerados pela compra e pela venda, programar → aprovar → baixar sem duplicar, contas a pagar, fluxo de caixa projetado e mapa financeiro — ver [regras-negocio/07](regras-negocio/07-financeiro.md)
- **Segundo fator (TOTP)** opcional, altamente recomendado a todos
- **Ciclo de compra:** compromisso, viagem, recebimento, romaneio valorizado e acerto, que ao ser aprovado gera as compras — parte do escopo principal, ver [regras-negocio/08](regras-negocio/08-ciclo-de-compra.md). O que ainda falta contra o documento funcional está em [fluxos/04-alinhamento-ao-doc-funcional](fluxos/04-alinhamento-ao-doc-funcional.md)
- **Toda ação editável e excluível**, com os efeitos desfeitos junto e auditoria imutável visível ao administrador

### O sistema NÃO faz (decisão consciente)

- **Não é SaaS.** Sem multi-tenant, planos, cobrança ou marketplace. É um sistema interno para uma operação real.
- **Não controla animal por animal na v1.** O saldo é por lote e categoria. Os dados de brinco existentes são importados e guardados, mas não há entidade `Animal` ainda — ver [ADR 0004](arquitetura/adr/0004-lote-agregado-antes-de-brinco.md).
- **Tributo não é calculado.** O acerto (Fase 5) registra Funrural, Fundepec, GTA, ICMS e demais como valores digitados: nada tributário foi implementado sem o contador ([#21](regras-negocio/99-pendencias.md)).
- **Não faz contabilidade fiscal.** Não emite nota, não apura imposto, não substitui o contador.
- **Não tem app nativo.** É web responsivo, que funciona bem em celular pequeno.
- **Não reproduz o layout dos relatórios legados pixel a pixel.** Reproduz os conceitos e os números.

## As três fontes do projeto

| Fonte | O que é | Como usamos |
|---|---|---|
| `docs/fontes/planilhas/CONTROLE PASTO…xlsx` | A operação real do produtor, safra 25/26, dados verdadeiros | **Fonte primária.** Define entidades, vocabulário e o que importar |
| `docs/fontes/Sistema_Gestao_Pasto_Compra_Gado_Estrutura_Funcional.md` + `imagem.jpeg` | **O escopo funcional consolidado**: gestão a pasto + compra de gado, em 3 blocos (Entrada, Movimentações, Relatórios e Análise) | **Fonte principal do escopo.** Fluxo, status, relatórios e integração entre telas |
| `docs/fontes/relatorios-legado/*.png` | 5 relatórios do SisAtak do frigorífico Boi Brasil (Alvorada-TO) | **Conceitos e números do ciclo de compra** (contrato, programação, acerto, comissão, histórico). Não o layout |
| `docs/fontes/planilhas/REPORTAGEM IVAN.xlsx` | Análise de consultoria da Fazenda Katuete: GMD, carcaça, eficiência biológica, TIR, curva ABC | **Referência de indicadores.** Define o que os dashboards devem chegar a calcular |

> **Mudança de posicionamento (2026-10-02, Warley):** até aqui estes documentos tratavam o escopo funcional como "outro negócio (mesa de compra de frigorífico)" e a Fase 5 como "antecipada, sem demanda". Está corrigido: o escopo funcional é a fonte principal, e o projeto é um **Sistema de Gestão a Pasto + Compra de Gado**. O `CLAUDE.md` original em `docs/fontes/referencia/` segue arquivado — foi escrito antes dessa decisão.

## Números da operação (safra 2025/2026)

Serve para dimensionar o sistema — é uma operação pequena em volume de dados e grande em valor por registro.

| | |
|---|---|
| Fazendas | 5 |
| Cabeças em estoque (São Francisco) | 1.954 |
| Cabeças compradas na safra | 954 |
| Valor das compras | R$ 2.457.752,15 |
| Custos lançados | R$ 1.046.907,76 (235 lançamentos) |
| Centros de custo em uso | 11 |
| Categorias animais | 11 |
| Abates na safra | 3 (354 cabeças) |

## Por onde começar

1. [Arquitetura](arquitetura/01-arquitetura.md) — como o sistema é organizado e por quê
2. [Modelo de dados](modelo-dados/01-entidades.md) — as entidades e seus relacionamentos
3. [Rebanho por movimentações](regras-negocio/01-rebanho-movimentacoes.md) — a regra mais importante do sistema
4. [Roadmap](roadmap/README.md) — o que construir, em que ordem, tarefa a tarefa
