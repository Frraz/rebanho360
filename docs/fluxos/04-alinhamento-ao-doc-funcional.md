# Alinhamento ao documento funcional

> Auditoria de 2026-10-02: o **código** contra `docs/fontes/Sistema_Gestao_Pasto_Compra_Gado_Estrutura_Funcional.md` (a fonte principal do escopo), a imagem dos 3 blocos, as planilhas e os 5 relatórios legados. Base do plano de ondas abaixo. Refazer a matriz ao fim de cada onda.

**Legenda:** ✅ coberto · 🟡 parcial · ❌ ausente.

## O que já está alinhado

Fluxo ponta a ponta (compromisso → viagem → recebimento → romaneio → acerto → compra → rebanho, custos e títulos) · rebanho como razão · comissão com snapshot · trava de fechamento e reabertura do acerto · contrato PDF versionado · 21 relatórios (tela, CSV, XLSX, PDF) · os 5 importadores · números da planilha conferidos (954 cabeças, R$ 2.457.752,15, 235 custos, R$ 1.046.907,76, 3 abates).

## Por seção do documento funcional

| Seção | Estado | Falta |
|---|---|---|
| 2 · Entrada / cadastros | 🟡 | Tabela de preço e faixas com critério, condição de pagamento e prazo (hoje: 5 campos fixos por item e `payment_days`); produto (código, unidade, finalidade); Veículo e Motorista; propriedade de origem como cadastro; infraestrutura; `CostClass` sem CRUD; tipos de custo fixos no código |
| 3 · Compra / compromisso | 🟡 | Data da negociação; pecuarista distinto do produtor; empresa e unidade no compromisso; nº de programação e de compra separados; "aguardando aprovação" |
| 4 · Programação / embarque | 🟡 | Pré-programação como etapa ([#32](../regras-negocio/99-pendencias.md)); programação de pagamentos **antes do acerto** ([#31](../regras-negocio/99-pendencias.md)) — o relatório existe desde 2026-10-02; ADF/documentação, motorista e veículo são texto livre ([#34](../regras-negocio/99-pendencias.md)) |
| 5 · Recebimento / faturamento | 🟡 | Peso médio e peso previsto no recebimento; "tipo" na classificação; faixa de peso (hoje só 1 a 5); acréscimos; NF sem "documento relacionado" e sem ligação ao título |
| 6 · Acerto | 🟡 | Comissão prevista × realizada; preço previsto × aplicado e categoria × classificação na tabela; data real do abate; relatórios de frete, comissão e financeiro não são gerados na aprovação |
| 7 · Comissão | 🟡 | Regra por produto e por operação; valor fixo; título único em vez de rateado por item |
| 8 · Frete | ✅ | — |
| 9 · Rebanho / manejo | 🟡 | Mudança de lote e de fazenda não são tipos próprios; lote sem alocação em pasto; **reprodução e infraestrutura ausentes** |
| 10 · Financeiro | 🟡 | Programação de pagamentos: **feita** como relatório (com banco, agência, conta, [#27](../regras-negocio/99-pendencias.md)); títulos por item e não por viagem/transportador e um vencimento só ([#33](../regras-negocio/99-pendencias.md)); documento do título vazio |
| 11 · Centro de custo | 🟡 | Animais e frete no mesmo centro; tributos num valor só; análises por comprador, produtor, operação e unidade; custo/kg fora da compra |
| 12 · Relatórios e dashboard | 🟡 | Dashboard sem peso comprado, peso e preço médios, frete, comissão, custo/kg, quebra média, compras por produtor/comprador/fazenda/centro, pago × a pagar; custo total do painel exclui a aquisição |
| 13 · Rastreabilidade | 🟡 | Linha do tempo por operação (`OperationEvent` só em contrato, acerto e financeiro); sem dossiê que reúna títulos, notas, lote e centro de custo |
| 14 · Status geral | 🟡 | **6 dos 16** (ver abaixo) |
| 15 · Integração | 🟡 | **Recebimento não alimenta o rebanho** (entra na aprovação do acerto, [#24](../regras-negocio/99-pendencias.md)); centro de custo → dashboard parcial |
| 16 · Documentos | 🟡 | 11 cobertos, 8 parciais, 2 ausentes (ver abaixo) |
| 17 · Estrutura / menu | ✅ | Menu nos 3 blocos da imagem (Onda 1). Programação/Embarque e Recebimento ainda sem lista própria |

### Os 16 status gerais (seção 14)

✅ Em negociação · Compromisso aprovado · Recebida · Em acerto · Acerto aprovado
🟡 Programada (só após aprovado e com data de retirada) · Embarcada (qualquer viagem conta) · Cancelada (é `EXCLUÍDA`)
❌ Aguardando aprovação · Em programação de embarque · Em conferência · Em faturamento · Aguardando financeiro · Pagamento programado · Pago · Encerrada

A etapa é **derivada** (`procurement/selectors.py::etapa_do_compromisso`) e para em "Acerto aprovado": o financeiro não a faz avançar.

### Os 21 documentos (seção 16)

✅ Contrato · Programação de pagamentos · Programação de embarque · Programação de abate · Programado × realizado · Conferência do acerto · Comissão por comprador · Histórico por pecuarista · Pesagem · Por centro de custo · Mapa financeiro · Quebra de viagem
🟡 Acerto final (só a tela) · Fretes · Despesas (só agregados) · Viagens (junto com fretes) · Estoque/rebanho (só tela) · Movimentações (só tela) · Dashboards (sem PDF)
❌ Recebimento · Histórico por comprador

## Divergências entre decisões do projeto e a fonte

| Tema | Projeto | Fonte | Situação |
|---|---|---|---|
| Posicionamento | "Escopo errado / outro negócio" | Seção 19: gestão a pasto + compra | **Corrigido** (2026-10-02) |
| Dado bancário no contrato e em relatório | Omitido do contrato; relatório sem dado bancário | Seções 3.1 e 10 pedem | Contrato segue sem; a programação de pagamentos mostra, **só com permissão**. Pendência [#27](../regras-negocio/99-pendencias.md) |
| Entrada no rebanho | Na aprovação do acerto | "O recebimento alimenta o rebanho" | [#24](../regras-negocio/99-pendencias.md) aberta; exige ADR |
| Menu | 8 seções | 3 blocos × 5 itens | **Corrigido** (Onda 1) |
| Custo/@ | Dividido pela @ vendida ([#14](../regras-negocio/99-pendencias.md)) | Planilha do consultor divide pela @ produzida | Aberta |

## Ondas

1. **Docs e navegação** — ✅ feita em 2026-10-02: posicionamento, #27, correção da migração, menu em 3 blocos.
2. **Fluxo da compra** — ✅ relatório de programação de pagamentos (2026-10-02). **Aguardam decisão:** aprovação em duas etapas ([#28](../regras-negocio/99-pendencias.md)) e status até "Encerrada" ([#29](../regras-negocio/99-pendencias.md)) · entrada no rebanho no recebimento ([#24](../regras-negocio/99-pendencias.md), ADR) · quem é quem na negociação ([#30](../regras-negocio/99-pendencias.md)) · títulos por transportador ([#33](../regras-negocio/99-pendencias.md)) · Veículo, Motorista e ADF ([#34](../regras-negocio/99-pendencias.md)). **Não dependem de decisão e ficam para a próxima:** dossiê e linha do tempo da operação (`OperationEvent` nas etapas que faltam) · acerto completo (comissão prevista × realizada, datas).
3. **Cadastros comerciais** — tabela de preço e faixas, condição de pagamento, comissão por produto e operação, produto, tipos de custo. Alíquota de tributo **só com o contador** ([#21](../regras-negocio/99-pendencias.md)).
4. **Dashboard 12.1 e relatórios faltantes**; centro de custo por comprador, produtor, operação e unidade.

**Fase 6, fora desta rodada:** reprodução, infraestrutura, equipe, lotação UA/ha e alocação em pasto, causa da morte estruturada, inventário valorizado, TIR, curva ABC, indicadores do consultor (rendimento do ganho, GMD de carcaça, eficiência biológica, dias para 1 @).
