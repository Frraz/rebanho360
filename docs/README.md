# Documentação do Rebanho360

Sistema de gestão pecuária para uma operação real de fazenda a pasto: 5 fazendas, ~2.000 cabeças, ~R$ 2,5 milhões de compra por safra.

**Comece por [00-visao-geral.md](00-visao-geral.md)** — que problema resolve, para quem, e o que deliberadamente não faz.

## Índice

### Fundamentos
| Documento | Assunto |
|---|---|
| [00-visao-geral](00-visao-geral.md) | Problema, usuários, escopo e não-escopo |
| [roadmap/](roadmap/README.md) | **As fases, tarefa a tarefa, até produção** — por onde começar |
| [roadmap/definition-of-done](roadmap/definition-of-done.md) | Quando uma tarefa está realmente pronta |
| [regras-negocio/99-pendencias](regras-negocio/99-pendencias.md) | **48 pendências de negócio** (1 confirmada; as demais abertas com padrão reversível) — ler antes de codificar |

### Arquitetura
| Documento | Assunto |
|---|---|
| [arquitetura/01-arquitetura](arquitetura/01-arquitetura.md) | Monólito modular, apps, camadas, stack |
| [arquitetura/02-infra-e-deploy](arquitetura/02-infra-e-deploy.md) | Docker em VPS compartilhado, deploy, estáticos, backup, restauração |
| [arquitetura/adr/](arquitetura/adr/) | Decisões arquiteturais, com alternativas descartadas |

### Modelo e regras
| Documento | Assunto |
|---|---|
| [modelo-dados/01-entidades](modelo-dados/01-entidades.md) | Entidades, campos, diagrama ER |
| [modelo-dados/02-vocabulario](modelo-dados/02-vocabulario.md) | Glossário pt-BR ↔ código |
| [regras-negocio/01-rebanho-movimentacoes](regras-negocio/01-rebanho-movimentacoes.md) | **A regra central do sistema** |
| [regras-negocio/02-custos-centro-de-custo](regras-negocio/02-custos-centro-de-custo.md) | Custos, rateio, centro de custo |
| [regras-negocio/03-compra-de-gado](regras-negocio/03-compra-de-gado.md) | Compra do produtor |
| [regras-negocio/04-venda-e-abate](regras-negocio/04-venda-e-abate.md) | Venda, abate, carcaça |
| [regras-negocio/05-indicadores-e-calculos](regras-negocio/05-indicadores-e-calculos.md) | Fórmulas, Decimal, divisor zero |
| [regras-negocio/07-financeiro](regras-negocio/07-financeiro.md) | Títulos, baixas, aprovação, bloqueios, fluxo de caixa |
| [regras-negocio/08-ciclo-de-compra](regras-negocio/08-ciclo-de-compra.md) | Compromisso, viagem, recebimento, romaneio e acerto (Fase 5) |
| [regras-negocio/09-usuarios-e-solicitacao-de-acesso](regras-negocio/09-usuarios-e-solicitacao-de-acesso.md) | Gerenciar usuários e o pedido de acesso pela tela de entrada |
| [regras-negocio/10-exportacao-de-dados](regras-negocio/10-exportacao-de-dados.md) | Exportar tudo ou parte, em CSV, Excel, JSON e PDF, em segundo plano e com o escopo de quem pede |
| [regras-negocio/11-dashboard-analitico](regras-negocio/11-dashboard-analitico.md) | O Dashboard: oito abas de análise (KPIs com comparação, gráficos, leituras automáticas), do mesmo número que o resto do sistema |
| [regras-negocio/06-edicao-exclusao-e-auditoria](regras-negocio/06-edicao-exclusao-e-auditoria.md) | **Editar, excluir, desfazer efeitos e auditar** — regra transversal |

### Fluxos e interface
| Documento | Assunto |
|---|---|
| [fluxos/01-fluxo-fazenda-a-pasto](fluxos/01-fluxo-fazenda-a-pasto.md) | O ciclo real da operação |
| [fluxos/02-maquinas-de-estado](fluxos/02-maquinas-de-estado.md) | Estados e transições |
| [fluxos/03-fluxo-compra-frigorifico](fluxos/03-fluxo-compra-frigorifico.md) | O ciclo do SisAtak, origem do ciclo de compra |
| [fluxos/04-alinhamento-ao-doc-funcional](fluxos/04-alinhamento-ao-doc-funcional.md) | **Matriz do documento funcional × sistema**: o que está pronto, o que falta, em que ordem |
| [ux/01-navegacao-e-ui](ux/01-navegacao-e-ui.md) | Menu, telas, responsividade, componentes (o *quê* e o *porquê*) |
| [ux/02-design-system](ux/02-design-system.md) | **Design system**: tokens, componentes, padrões de página (o *como fica*) |
| [ux/historico/](ux/historico/) | Prompt e insumos do redesenho de 01/10/2026, só como registro |

### Operação
| Documento | Assunto |
|---|---|
| [seguranca/01-seguranca](seguranca/01-seguranca.md) | Ameaças, controles, checklist |
| [migracao/01-planilhas-e-importacao](migracao/01-planilhas-e-importacao.md) | Aba por aba: o que importar |
| [relatorios/01-catalogo](relatorios/01-catalogo.md) | Relatórios por fase + leitura dos legados |

### Decisões (ADR)
| ADR | Decisão |
|---|---|
| [0001](arquitetura/adr/0001-monolito-modular-django.md) | Monólito modular Django |
| [0002](arquitetura/adr/0002-rebanho-como-razao-de-movimentacoes.md) | Rebanho como razão com partidas dobradas |
| [0003](arquitetura/adr/0003-escopo-por-fazenda-desde-a-fase-0.md) | Escopo por fazenda desde a Fase 0 |
| [0004](arquitetura/adr/0004-lote-agregado-antes-de-brinco.md) | Lote agregado antes de brinco individual |
| [0005](arquitetura/adr/0005-decimal-e-arredondamento.md) | Decimal, arredondamento e divisor zero |
| [0006](arquitetura/adr/0006-tudo-editavel-com-auditoria-imutavel.md) | Tudo editável e excluível, com auditoria imutável |
| [0007](arquitetura/adr/0007-design-system-proprio-sobre-tailwind.md) | Design system próprio sobre Tailwind, com ícones e fontes locais |
| [0008](arquitetura/adr/0008-ciclo-de-compra-por-composicao.md) | Ciclo de compra por composição: o núcleo não muda |

## Fontes

`fontes/` guarda o material original que deu origem ao projeto. **A pasta não é versionada** (tem dados reais da fazenda); só o [README dela](fontes/README.md) vai para o GitHub, e os links abaixo só funcionam no disco de quem a tem.

| Arquivo | O que é | Como usar |
|---|---|---|
| `planilhas/CONTROLE PASTO…xlsx` | **A operação real.** 17 abas, safra 25/26 | Fonte primária — entidades, vocabulário, dados a importar |
| `planilhas/REPORTAGEM IVAN.xlsx` | Consultoria da Fazenda Katuete, 44 abas | Referência de indicadores avançados. Não importar |
| `Sistema_Gestao_Pasto_Compra_Gado_Estrutura_Funcional.md` | **Escopo funcional consolidado** | **Fonte principal.** Fluxo, status, relatórios, integração |
| `imagem.jpeg` | Proposta visual em 3 blocos | **Estrutura do menu** (Entrada, Movimentações, Relatórios e Análise) |
| `relatorios-legado/*.png` | 5 relatórios do SisAtak (frigorífico Boi Brasil) | Conceitos e números do ciclo de compra |
| `audio.txt` | Transcrição que originou o projeto | Contexto |
| `referencia/` | `CLAUDE.md` original e `ideiachatgpt.md` | Arquivados: o `CLAUDE.md` atual da raiz os substitui |

> **Posicionamento:** o projeto é um Sistema de Gestão a Pasto + Compra de Gado, com o escopo funcional como fonte principal. Ver [00-visao-geral](00-visao-geral.md#as-três-fontes-do-projeto).

## Como manter

- Documento longo não é lido. Alvo: 1 a 3 páginas.
- Decisão importante vira ADR, **com a alternativa descartada e o porquê**.
- Dúvida de negócio vai para `99-pendencias.md`. **Nunca inventar regra em silêncio.**
- Decisão que muda: atualizar o documento no mesmo commit do código.
- Mudou algo visual? O [design system](ux/02-design-system.md) é a fonte de verdade: atualize-o junto, e recompile o CSS.
- Pendência resolvida: registrar a resposta, com data e quem respondeu. A pergunta fica — apagá-la é perder o motivo da regra.
