# Decisões do cliente — 2026-10-03

O cliente (Facholi) respondeu 34 perguntas estruturais. A **diretriz geral**: o sistema é, antes de tudo, de **registro, controle e rastreabilidade**. Onde preço, alíquota, comissão, quebra, custo, condição ou regra comercial podem variar entre operações, o sistema prefere **campos editáveis** a presumir ou deduzir. A automação fica para reaproveitar o que já foi registrado, gerar documentos, gerar títulos a partir de lançamentos aprovados, consolidar centro de custo, alimentar relatórios e dashboards e manter a auditoria.

## Natureza das respostas — leia antes de tudo

1. **São provisórias.** Vieram do Facholi, que **não tem todas as respostas** (tem "muito mais" que o desenvolvedor, mas não é o usuário da operação). Quem responde de verdade são os **usuários finais**. O combinado: **seguir com estas respostas**, colocar tudo dentro do sistema e **validar em reunião, com o sistema na tela** — porque "eles vão querer ver na prática". Roteiro em [14](14-roteiro-de-validacao-com-os-usuarios.md).
2. **A planilha São Francisco é um exemplo.** O cliente respondeu muitas perguntas com a mesma lógica: **o sistema contém os campos das planilhas, não os dados delas**. Dado que "falta" ou diverge na planilha de exemplo **não é relevante** — "deve ter esquecido". Pendências que só perguntavam isso (#2, #5, #6, #10, #11, #12, #18) ficaram **⚪ dispensadas**, e a carga histórica da planilha deixou de ser objetivo. As planilhas continuam sendo **fonte de campos e de indicadores**, não de dados a reconciliar.
3. **Mesmo assim houve decisões de verdade** — são as tabelas abaixo.

Cada decisão está registrada na pendência correspondente em [99-pendencias-resolvidas](99-pendencias-resolvidas.md) (o que ainda falta de cada tema está em [99-pendencias](99-pendencias.md)). Esta página é o mapa: **resposta → o que mudou no sistema**.

## Cadastro e pessoas

| # | Resposta | No sistema |
|---|---|---|
| 1 | Pecuarista e produtor são a mesma pessoa | Um papel só (Produtor/Fornecedor) no compromisso — #30 |
| 2 | Comprador = comissionado; **vários compradores**, cada um com a sua comissão | `Commission` passou a uma linha **por comprador**; botão *+ Adicionar comprador* no compromisso; título e vencimento por comprador — #30, #33 |
| 31 | E-mail obrigatório; só o Admin altera o e-mail de outro | E-mail obrigatório ao criar e editar; entra-se por usuário **ou** e-mail — #43, #46 |
| 30 | Admin e Gestor aprovam novos acessos | `pode_aprovar_acessos`; o Gestor não concede o papel de Administrador — #41 |
| 32 | 2FA em aberto; se adotado, obrigatório para todos | `TWO_FACTOR_OBRIGATORIO` (desligado) — #19 |

## Numeração e fluxo

| # | Resposta | No sistema |
|---|---|---|
| 3 | **Um número só** por operação (`OP-000123`) | Compromisso `OP-000123`; viagem `/V1`, recebimento `/R1`, acerto `/AC1`, compra do item `/I1`; financeiro e centro de custo pela compra — #32 |
| 8 | Admin/Gestor aprovam, **inclusive o próprio lançamento** | Sem segregação; auditoria guarda lançou/aprovou/data/hora — #25, #28 |
| 11 | O animal entra no rebanho **só após aprovar o acerto** | Como já era — #24 |
| 15 | **Encerramento manual** | `encerrar_operacao` / `reabrir_operacao` (Admin/Gestor); situação depois do acerto derivada dos títulos — #29 |
| 29 | Admin e Gestor excluem registro confirmado | Como já era — #9 |
| 20 | Previsão de pagamento antes do acerto **não** entra no fluxo de caixa | Como já era (sem título previsto) — #31 |

## Comercial e preço

| # | Resposta | No sistema |
|---|---|---|
| 4, 5 | Faixa **informada pelo frigorífico**; preços digitáveis por operação | Como já era — #20, #35 |
| 6, 16 | **Cadastro de condições de pagamento** (à vista, prazos, parcelado…) | `PaymentCondition`; escolhida na compra, compromisso e venda; parcelada = um título por parcela — #16, #35 |
| 7 | Comissão percentual sobre o **valor bruto**; ou valor direto | Tipo `VALOR`; base única `BRUTO` — #4 |
| 22 | Venda: **preço único por @** | Como já era — #8 |
| 23 | Rendimento = o **informado pelo frigorífico**; `SOMA RENDIMENTO` sem regra | `Sale.reported_yield_percent` prevalece; nada para `SOMA RENDIMENTO` — #7 |
| 28 | **Rendimento estimado de entrada** editável (~50%) | `entry_yield_percent` na compra e no item; alimenta a @ produzida — #15 |

## Viagem, acerto e financeiro

| # | Resposta | No sistema |
|---|---|---|
| 9 | ADF = número, sem anexo | `Trip.adf_number` — #34 |
| 10 | Motorista, veículo e placa digitados na viagem | `driver_name`, `vehicle`, `vehicle_plate` — #34 |
| 12 | **Quebra digitada**; sem alerta nem desconto | `Receiving.trip_loss_percent`; alerta removido — #23 |
| 13 | **Sem rateio automático** | `SettlementAllocation`: o usuário distribui; a soma tem de fechar — #22 |
| 14 | Tributos, taxas e descontos **informados**; auxiliares alíquota/base/favorecido/observação | `SettlementLine` com esses campos, só de registro; efeito definido no tipo — #21 |
| 17, 18 | Frete → transportador da **viagem**, um título por viagem; comissão → cada comprador; tributos → favorecido informado; **vencimentos próprios** | Títulos do acerto (`origin_settlement` + `ref`) — #17, #33 |
| 19 | **Aprovam** Admin/Gestor; **executa** o Financeiro | `PAPEIS_QUE_APROVAM_PAGAMENTO = ADMIN, GESTOR` — #17 |
| 26 | **Frete com centro de custo próprio** | Centro `FRETE` — #36 |
| 21 | Dados bancários só onde já são parte do modelo | Contrato e conferência do acerto; fora da programação de pagamentos — #27 |

## Gestão a pasto e indicadores

| # | Resposta | Estado |
|---|---|---|
| 24 | Escopo: cria/reprodução, recria/engorda, confinamento, estoque, movimentações, mortalidade, lotes, infraestrutura (resumida). **Fora:** chuva, suplementação, consumo | Escopo registrado — #38; **implementação pendente** |
| 25 | Indicadores do Relatório Ivan: TIR, curva ABC, inventário valorizado, eficiência biológica, GMD, @ produzidas… | Registrado — #39; **implementação pendente** |
| 27 | **Sem alerta de mortalidade** por percentual | Removido — #15 |
| 33 | **PDF** para todos os perfis, dentro do escopo | Como já era — #44 |
| 34 | Nenhuma outra rotina da planilha | Escopo atual é a referência |

## Seguem abertas (palavras do cliente)

1. `SOMA RENDIMENTO`: esclarecer o significado, se quiser incorporar.
2. Segundo fator: decidir se será usado.
3. Tabela fixa de preços por faixa: digitável por operação; avaliar cadastro reutilizável depois.
4. Exportações além do PDF: regras de Excel, auditoria ou retenção de arquivos, em etapa posterior.

## O que a mudança deixa de fazer sozinho

O sistema **deixou de**: ratear frete, comissão e tributos entre itens; calcular ou alertar quebra de viagem; alertar mortalidade; presumir o favorecido de tributo; exigir segunda pessoa para aprovar. Qualquer retorno a esses comportamentos é decisão do cliente — cada um mora em um lugar só (`procurement/settlement.py`, `procurement/receivings.py`, `procurement/permissions.py`).
