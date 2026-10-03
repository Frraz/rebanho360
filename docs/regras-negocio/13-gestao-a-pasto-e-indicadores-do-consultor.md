# Gestão a pasto e indicadores do consultor

> Decisão do cliente em 2026-10-03 ([12](12-decisoes-do-cliente-2026-10-03.md), pendências [#38](99-pendencias.md#38--lotação-por-pasto-uaha-e-alocação-de-lote-em-pasto-fase-6) e [#39](99-pendencias.md#39--eficiência-biológica-e-a-base-da-arroba-viva-fase-6)): os controles que as planilhas **realmente** usam entram no sistema, **de forma resumida**, sem virar módulo complexo. **Fora do escopo:** controle diário de chuva, suplementação/dieta e consumo detalhado.

Tudo aqui segue as regras de sempre: derivado é **calculado** (regra 6), divisor zero devolve `None` (**"—"**), escopo por fazenda (404 fora dele), motivo e auditoria em toda correção ou exclusão, e o sistema **não julga** o que é um índice bom ou ruim.

## O que existe

| Escopo do cliente | No sistema |
|---|---|
| **Cria / reprodução** — reprodução, prenhez, nascimentos, desmama, bezerros, indicadores | App `reproduction`: **ciclo reprodutivo** por fazenda e safra de nascimento. Nascimentos vêm do razão do rebanho (`NASCIMENTO`) |
| **Recria / engorda** — entrada, evolução, categorias, lotes, pesagens, movimentações, desempenho | Já existia (`herd`, `livestock`, desempenho do lote) |
| **Confinamento** | `Lot.regime` (pasto ou confinamento) e o relatório **Confinamento** |
| **Estoque / inventário** — quantidade, categoria, lote, valorização | Relatório **Inventário valorizado** |
| **Movimentações** — compra, transferência, venda, abate | Já existia |
| **Mortalidade** — categoria, quantidade, causa, indicadores | `HerdMovement.death_cause` (opcional) e o relatório **Mortalidade por causa**. **Sem alerta** por percentual |
| **Lotes e desempenho** | Já existia |
| **Infraestrutura e parque de máquinas** (resumidos) | App `infrastructure`: **estruturas da fazenda** (curral, cocho, bebedouro…) e **máquinas** com o **uso** lançado |

## Reprodução

Um registro por fazenda e safra de nascimento — o que a aba `DADOS REPRODUTIVOS` pede:

- **Informado:** tempo de estação, total de fêmeas, fêmeas acima de 18 meses, fêmeas **em monta** e **prenhes** por categoria (novilhas, novilhas desafio, primíparas, vacas), inseminadas, prenhes por IA/IATF, prenhes por touro, bezerros desmamados.
- **Calculado:** vazias, fertilidade geral e por categoria, % de fêmeas em reprodução, aproveitamento (em monta ÷ acima de 18 meses), % de inseminadas, fertilidade IA/IATF e de touro, **nascidos** (do razão, por sexo) e **desmama** (desmamados ÷ nascidos).
- **Travas:** prenhes ≤ em monta (serviço **e** banco), prenhes por IA ≤ inseminadas, IA + touro ≤ prenhes, **um ciclo por fazenda e safra**. Corrigir pede motivo; excluir é lógico.
- Relatório **Indicadores reprodutivos** (tela, CSV, XLSX, PDF).

## Infraestrutura e máquinas

- **Estrutura:** tipo, identificação, área (m²), cocho (m), bebedouros e animais atendidos. Calculados: **m² por animal**, **cm de cocho por cabeça**, **animais por bebedouro**.
- **Máquina:** cadastro (tipo, valor da máquina nova) e **uso** lançado por período — horas, litros, R$ de combustível e de manutenção. Calculados: **consumo (L/h)**, **combustível por hora**, **manutenção por hora** e **custo por hora**. Não inclui operador nem depreciação. O custo em si continua sendo lançado em **Custos** (centro `PARQUE DE MÁQUINAS`): o uso lançado aqui **não** gera custo.
- O campo lança uso; cadastrar estrutura e máquina é do escritório para cima. Uso é lançamento reversível (motivo, auditoria).

## Indicadores do consultor (relatórios)

Todos pelo catálogo de relatórios (tela, CSV, XLSX, PDF), com o filtro de safra e fazenda do topo. **Dinheiro** — curva ABC, inventário valorizado e TIR — é negado ao `CAMPO`, como no dashboard.

| Relatório | O que é |
|---|---|
| **Curva ABC de custos** | Cada centro de custo, do maior ao menor: R$, % do desembolso, % acumulado, % do faturamento e **perfil A / B / C** (o centro **começa** dentro dos primeiros 80% / até 95% / depois). O maior centro é sempre A |
| **Inventário valorizado** | O rebanho de hoje, lote a lote: cabeças, peso médio (última pesagem, ou o peso da compra), @ vivas, **custo acumulado** e **valor de mercado** |
| **TIR da safra** | Fluxo mensal da safra (custos × vendas) e a taxa interna de retorno, ao mês e ao ano (composta). Com o preço da @ informado, o estoque inicial entra como saída e o final como entrada |
| **Mortalidade por causa** | Mortes por causa informada ("Não informada" quando ninguém registrou) e a taxa por fazenda |
| **Confinamento** | Lotes marcados como confinamento: cabeças, peso de entrada e atual, permanência, GMD, @ produzidas, custo e custo por @ |
| **Indicadores reprodutivos** | Os índices de cada ciclo |

**Duas premissas são informadas pelo usuário — o sistema não escolhe:**

1. **O preço da @** (parâmetro `preco_arroba` do inventário e da TIR). Sem ele, o valor de mercado fica "—" e a TIR é a do caixa puro (só existe se já houve venda).
2. **A arroba viva do inventário é a da planilha do consultor: 30 kg de peso vivo** (`330 kg = 11 @`). É uma constante do módulo (`reports/consultor.py`), diferente da arroba de carcaça de 15 kg do resto do sistema. Se o cliente usar outra base, é uma linha.

A **TIR** é calculada por bisecção em `Decimal` (`apps/core/irr.py`), sem `float`; sem troca de sinal no fluxo, não existe (`None`).

## Ainda de fora

- **Eficiência biológica:** depende do consumo de matéria seca, que ficou fora do escopo. Não aparece. Se o consumo entrar, é um relatório novo.
- **Lotação por pasto (UA/ha)** e **alocação de lote em pasto:** o cadastro de pastos (`Paddock`) existe, mas nada o consome ainda.
- **Curva de consumo, equipe, chuva:** fora do escopo.
- **SOMA RENDIMENTO:** significado não definido ([#7](99-pendencias.md)).

## Testes que travam esta regra

`apps/reproduction/tests/` (índices, divisor zero, nascimentos do razão, constraints no banco, escopo) · `apps/infrastructure/tests/` (custo por hora, razões, permissões, escopo) · `apps/reports/tests/test_consultor.py` (perfil ABC, mortalidade por causa, inventário sem peso e com preço, TIR, confinamento, `CAMPO` sem dinheiro) · `apps/core/tests/test_irr.py`.
