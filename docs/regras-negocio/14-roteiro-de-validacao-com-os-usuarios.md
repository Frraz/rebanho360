# Roteiro de validação com os usuários finais

> As respostas de 2026-10-03 vieram do Facholi, rápidas e **provisórias** ([12](12-decisoes-do-cliente-2026-10-03.md)). Quem responde de verdade são os usuários da operação, e o combinado é **mostrar o sistema funcionando** e decidir ali, porque "eles vão querer ver na prática". Este roteiro diz **o que mostrar** e **o que perguntar**. Use dados de demonstração (`seed_demo`), **nunca** a planilha São Francisco como régua: ela é um exemplo, e o que importa são os campos.

**Como registrar o resultado:** cada resposta confirmada ou mudada vai para a pendência correspondente (com data e quem respondeu): se era aberta, sai de [99](99-pendencias.md) para [99-pendencias-resolvidas](99-pendencias-resolvidas.md); se já estava resolvida, atualiza o item lá e, se mudar comportamento, para [12](12-decisoes-do-cliente-2026-10-03.md). Mudança de regra mora em um lugar só (indicado em cada item).

## 1. O ciclo de compra, de ponta a ponta (30 min)

Mostrar nesta ordem: **compromisso** com dois compradores → **aprovar** (como Gestor, o próprio lançamento) → **viagem** (ADF, motorista, veículo, placa, vencimento do frete) → **recebimento** (quebra digitada) → **romaneio** → **acerto** com tributos informados → **distribuição entre os itens** → **aprovar** → títulos de frete, comissão e tributo → **encerrar** a operação.

| Perguntar | Resposta provisória | Onde muda |
|---|---|---|
| Vocês lançam **mais de um comprador** na mesma operação? A comissão deles é **percentual, por cabeça ou valor**? | Sim, sem limite; os três tipos, sobre o **valor bruto** | `procurement/commitments.py`, `commercial/commission.py` |
| Quem **aprova** o compromisso e o acerto? Pode ser quem lançou? | Admin e Gestor; sim, o próprio | `procurement/permissions.py` |
| Com **mais de um item**, como vocês dividem frete, comissão e tributos? A tela sugere por cabeça/valor: serve, ou é sempre à mão? | Sempre **informado**; a sugestão só pré-preenche | `procurement/settlement.py` |
| O **número** `OP-000123` único serve para tudo, ou alguém precisa de número separado para programação/compra? | Um só | `procurement/codes.py` |
| A **quebra de viagem**: digitam em %? Em kg? Querem ver diferença de peso na tela? | % digitada; pesos lado a lado, sem alerta | `procurement/receivings.py` |
| O que muda quando uma operação está **encerrada**? Quem reabre? | Para de aceitar lançamento; Admin/Gestor reabrem com motivo | `procurement/commitments.py` |
| Os **status** da operação: quais vocês realmente usam? (o documento funcional lista 16) | 4 derivados do financeiro + *encerrada* | `procurement/selectors.py` |

## 2. Financeiro (15 min)

Mostrar: condição de pagamento **parcelada** gerando parcelas · título de frete por viagem e de comissão por comprador com **vencimentos próprios** · **programar → aprovar → baixar** com três pessoas.

| Perguntar | Resposta provisória |
|---|---|
| Quem aprova pagamento e quem dá a baixa? Pode ser a mesma pessoa? | Admin/Gestor aprovam; Financeiro paga; o Admin não paga o que ele aprovou, havendo outro |
| O **favorecido do tributo** (Funrural, GTA…) é sempre digitado? Há tributos que o frigorífico retém e **não** geram pagamento nosso? | Digitado; hoje o **efeito** (soma ao custo / reduz animais / reduz líquido) é escolhido por tipo — **confirmar com o contador** (#21) |
| Quais **condições de pagamento** vocês usam? Parcelado é com datas fixas ou em dias? | À vista, 4/7/15/30 dias e parcelado em dias |
| Dado bancário no **contrato** e na **conferência do acerto**: só esses dois mesmo? Quem pode ver? | Sim; Admin, Gestor e Financeiro |

## 3. Gestão a pasto (20 min)

Mostrar: **reprodução** (ciclo da fazenda), **mortalidade por causa**, **confinamento** (marcar lote), **infraestrutura e máquinas**, e os relatórios **curva ABC, inventário valorizado e TIR**.

| Perguntar | Observação |
|---|---|
| A operação faz **cria** (tem matrizes) ou só recria/engorda? | Se for só recria, a reprodução fica escondida do menu |
| A **causa da morte**: a lista curta serve? Falta alguma? | Lista em `herd/models.py::DeathCause` |
| **Inventário valorizado:** o preço da @ é informado por quem, e com que frequência? A @ **viva de 30 kg** é a base de vocês? | Premissa tirada da planilha do consultor — **confirmar** (`reports/consultor.py::KG_POR_ARROBA_VIVA`) |
| **TIR:** querem a do caixa puro ou com o estoque valorizado? Mensal serve? | Os dois, dependendo de informar o preço da @ |
| **Máquinas:** o custo por hora precisa incluir operador e depreciação? Quem lança as horas (campo)? | Hoje só combustível + manutenção; o campo lança o uso |
| **Infraestrutura:** as medidas do curral (m², cocho, bebedouro) bastam? | Resumido, como pedido |
| **Eficiência biológica** depende de consumo de matéria seca; vão registrar consumo? | Hoje **não aparece** (consumo está fora do escopo) |
| **Lotação por pasto (UA/ha):** querem alocar lote em pasto? | Ainda não existe |

## 4. Acesso e segurança (10 min)

| Perguntar | Resposta provisória |
|---|---|
| Todos terão **e-mail**? Entram por usuário ou e-mail? | E-mail obrigatório; entra pelos dois |
| **Segundo fator** (código no celular): vai ser usado? Se sim, para todos? | **Em aberto** — `TWO_FACTOR_OBRIGATORIO` pronto para ligar |
| Quem **aprova pedidos de acesso** e quem é avisado? | Admin e Gestor |
| Quem **exporta** dados? PDF para todos os perfis? Excel/auditoria/retenção? | PDF para todos, dentro do escopo; o resto **em aberto** |

## 5. O que ainda precisa de resposta de verdade

Itens que o Facholi deixou abertos ou que dependem de quem opera: **SOMA RENDIMENTO** (o que é?) · **segundo fator** · **tabela fixa de preço por faixa** (há padrão que se repete entre compromissos?) · **exportações além do PDF** · **mais de uma empresa** (#47: as duas cadastradas são operações separadas?) · **quem vê dinheiro** no campo (#48) · **Parceria** nas compras e vendas (#3: existe de fato?).

## 6. O que NÃO levar para a reunião

Conciliar a planilha São Francisco (cabeças sem contrapartida, compra de 126 cabeças, ano digitado errado, pesos que divergem entre abas, "quem é ONODA"). O cliente dispensou: **são dados do exemplo, não requisitos** (#2, #5, #6, #10, #11, #12, #18 — ⚪).
