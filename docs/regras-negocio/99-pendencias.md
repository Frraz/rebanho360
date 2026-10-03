# Pendências de negócio

Dúvidas que **continuam sem resposta**. Cada uma tem: a pergunta, por que importa, o que foi implementado provisoriamente (sempre o padrão mais reversível) e o custo de mudar depois. As **já respondidas ou dispensadas** estão em [99-pendencias-resolvidas](99-pendencias-resolvidas.md).

**Status:** 🔴 bloqueia · 🟡 resolver antes da fase indicada · 🟢 pode esperar

> **O que ainda é "decisão para seguir".** As respostas de 2026-10-03 vieram do Facholi, rápidas e **provisórias**; os usuários finais as validam **em reunião, com o sistema na tela** ([14](14-roteiro-de-validacao-com-os-usuarios.md)). E a planilha São Francisco é só **exemplo**: lacuna ou divergência dentro dela não é pendência — o que vale são os campos.

Os números das pendências **não foram reordenados** (o código e os documentos citam "pendência #N"): faltam números porque esses itens estão no arquivo de resolvidas.

**Abertas (18):** #3 · #7 · #13 · #14 · #19 · #21 · #26 · #29 · #35 · #37 · #38 · #39 · #40 · #42 · #44 · #45 · #47 · #48

---

## #3 — 🟡 O que é "PARCERIA"? *(Fase 2)*

**Onde:** coluna `PARCERIA` nas abas `COMPRA DE GADO` e `VENDAS`. Valor `-` em **todas** as linhas.

**A dúvida:** a coluna existe, então alguém a criou por um motivo. Há operação em parceria, arrendamento ou meação? Quem é o parceiro e como se divide?

**Por que importa:** afeta quem é dono do animal, como o custo é rateado e como o resultado é dividido. É estrutural — não é um campo a mais.

**Implementado:** campo `partnership` como texto livre, preservado na importação, sem efeito em cálculo algum.

**Custo de mudar:** médio a alto. Se houver divisão de resultado, mexe em rateio de custo, resultado por lote e provavelmente em titularidade do rebanho.

**Fase 2:** `Purchase.partnership` existe como texto livre; o importador de compras o preserva (`-` vira vazio). Continua sem efeito em cálculo. Nenhuma compra da planilha real tem valor nele.

---

## #7 — 🟡 `SOMA RENDIMENTO`: o que é? *(Fase 3)*

**Onde:** aba `VENDAS`, coluna `SOMA RENDIMENTO` (no abate de ago/2025, 43,12). Não é percentual e não é arroba.

**A dúvida:** o que essa coluna mede, e se algum usuário a quer como indicador.

**Por que importa:** só importa se alguém a usa. O cliente confirmou que, até o significado ser esclarecido, **não se cria regra, cálculo nem indicador** para ela.

**Implementado:** nada — `SOMA RENDIMENTO` não existe no sistema (há teste que garante que nenhum campo com esse sentido foi criado). O rendimento de carcaça usa o **informado pelo frigorífico**, com o calculado ao lado para conferência.

**Custo de mudar:** baixo, depois que o significado for dito: é um indicador derivado novo (regra 6), sem campo.

---

## #13 — 🟡 Abate pode ser confirmado sem o peso de carcaça? *(Fase 3)*

**Onde:** [04-venda-e-abate](04-venda-e-abate.md) diz "carcaça obrigatória só em `ABATE`", e o dashboard prevê a pendência "venda sem carcaça". As duas frases só convivem se o abate puder existir antes do romaneio do frigorífico.

**A dúvida:** o produtor confirma o abate no dia em que o gado sai e o romaneio chega depois? Ou só lança quando já tem a carcaça?

**Por que importa:** se confirmar exigir carcaça, as cabeças ficam no saldo até o romaneio chegar — o rebanho mostra animais que já foram embora.

**Implementado:** `ABATE` **confirma sem carcaça** (as cabeças saem do saldo na hora) e fica como **pendência** no painel e na tela da venda; os indicadores de carcaça mostram "—" até o romaneio ser informado. `VENDA` de animal vivo **não aceita** carcaça (constraint no banco).

**Custo de mudar:** baixo. É uma validação em `confirmar_venda`.

---

## #14 — 🟡 Margem por @: qual denominador, e o que fazer com lote aberto? *(Fase 3)*

**Onde:** [05-indicadores](05-indicadores-e-calculos.md): `margem/@ = valor recebido por @ − custo por @`, com `custo/@ = custo total ÷ arrobas produzidas`. Mas "@ produzida" ([05](05-indicadores-e-calculos.md#arrobas-produzidas)) é *ganho* de carcaça, e o "valor recebido por @" é por @ **vendida**. Subtrair uma da outra mistura as duas bases. E a regra de "congelar" o resultado não diz o que mostrar enquanto o lote ainda tem animais.

**A dúvida:** a margem deve usar o custo por @ **vendida** (de modo que `resultado = margem/@ × @ vendidas` feche exato), ou por @ **produzida** (ganho)?

**Implementado:** `custo/@ = custo do lote ÷ @ de carcaça vendida` — com isso `resultado = margem/@ × @ vendidas`, a conta fecha, e é o que o relatório legado `06_Historico_de_Abate_por_Pecuarista` mostra (`R$ @` × `Custo @`). Lote **ainda aberto** mostra resultado **parcial**: o custo é rateado pela fração vendida (`vendidas ÷ (vendidas + saldo)`), e a tela diz "parcial". Lote **sem custo de aquisição** (como o "saldo anterior" da planilha) não tem resultado: mostra "—" e diz por quê. "Congelar" = o período termina na `exit_date`; **nenhum derivado é gravado** (regra 6).

**Custo de mudar:** baixo — é a função `resultado_do_lote`, isolada em `apps/sales/result.py`.

**🔎 Auditoria de 2026-10-02:** a planilha `REPORTAGEM IVAN` (aba `ANÁLISE PECUÁRIA`) divide o custo pela **@ produzida**, não pela vendida. Quem comparar o painel com o relatório do consultor verá números diferentes sem erro de nenhum dos lados. Ver também [#37](#37--o-que-é-custo-total-e-custo-por-cabeça-no-painel-fase-5).

---

## #19 — 🟡 Segundo fator: adotar ou não *(Fase 4)*

**A dúvida:** o cliente ainda avalia se o segundo fator (código no celular) é sustentável na operação. Se adotado, será **obrigatório para todos** os usuários, não só para `ADMIN` e `FINANCEIRO`. E: quantas pessoas vão usá-lo, e quem refaz o acesso de quem perde o celular **e** os códigos de recuperação?

**Implementado:** opcional e recomendado a todos (decisão de Warley, 2026-10-03). Pronto para ligar: `TWO_FACTOR_OBRIGATORIO=True` no `.env` leva quem ainda não ativou direto à configuração. Códigos de recuperação (10, uso único). Perdeu tudo: um `ADMIN` redefine pela tela de usuários (nunca o próprio) ou o servidor roda `manage.py resetar_segundo_fator` — ambos auditados, e as sessões do usuário são encerradas.

**Custo de mudar:** baixo. É uma variável de ambiente; a regra mora em `two_factor.precisa_de_segundo_fator`.

---

## #21 — 🟡 Efeito padrão de cada natureza de tributo (contador) *(Fase 5)*

**Onde:** `04_Conferencia_do_Acerto` (Funrural, Fundepec, GTA, ICMS, taxa de abate, indenização, Incentivo Precoce, Idaterra, crédito GR-3, desconto, adiantamento) e o roadmap, que exige confirmar toda regra tributária com o contador.

**A dúvida:** para cada natureza, **quem arca** — nós, como custo da compra, ou o vendedor, retido do valor que pagamos? O que é desconto de preço e o que é só movimento de caixa?

**Por que importa:** errar quem arca muda o custo do lote **e** o valor pago ao produtor.

**Implementado:** o sistema **não calcula** tributo: todo valor é digitado, com alíquota, base, favorecido e vencimento só de registro. O **efeito** de cada tipo é escolhido pelo usuário no cadastro do tipo (`TaxType.effect`); sem escolha vale o padrão da natureza, em um lugar só (`procurement/settlement.py::TRATAMENTO_POR_NATUREZA`):

| Natureza | Efeito padrão | Hipótese |
|---|---|---|
| `TRIBUTO`, `TAXA` | somam ao **custo de aquisição** e geram título de impostos | arcamos com o tributo |
| `DESCONTO` | **reduz o valor dos animais** (custo e pagamento) | o desconto muda o preço |
| `ADIANTAMENTO`, `CREDITO` | **reduzem o líquido a pagar**; não mudam o custo | é movimento de caixa |

**Custo de mudar:** baixo — uma tabela, ou o campo no tipo. Calcular por alíquota é trabalho novo e só começa com a resposta do contador. **Confirmar com o contador antes de usar o acerto de verdade.**

---

## #26 — 🟢 Base do preço do item: @ de carcaça ou cabeça *(Fase 5)*

**Onde:** o contrato legado precifica em R$/@ de carcaça por faixa. A compra de bezerro do produtor é por cabeça (a planilha só tem `MÉDIA/CAB`).

**Implementado:** cada item escolhe a base. **@ de carcaça:** valor = Σ líquido do romaneio. **Cabeça:** valor = cabeças recebidas × preço unitário, sem romaneio.

**Custo de mudar:** baixo. É um campo do item.

---

## #29 — 🟡 Status da operação depois do acerto aprovado *(Fase 5)*

**Onde:** seção 14 do documento funcional lista 16 status ("em conferência", "em faturamento", "aguardando financeiro", "pagamento programado", "pago", "encerrada"…).

**A dúvida:** (a) "Pago" da operação é quando **todos** os títulos do acerto estão quitados? (b) Dos 16 status, quais a operação realmente usa? "Em conferência" e "em faturamento" separam o quê, na prática?

**Por que importa:** é o que responde "o que falta fazer nesta compra?" sem abrir cinco telas.

**Implementado:** depois do acerto aprovado a situação é **derivada dos títulos** (`selectors.situacao_financeira`): *aguardando financeiro* → *pagamento programado* → *pago* (todos os títulos quitados). *Encerrada* é o único passo manual (`ADMIN`/`GESTOR`, com motivo ao reabrir).

**Custo de mudar:** baixo a médio. Mais status derivados são uma função; um status que alguém muda à mão é um campo e uma trava.

---

## #35 — 🟢 Tabela fixa de preço por faixa *(Fase 5)*

**Onde:** seção 2.1 do documento (Comercial): tabelas de preço, faixas e **critérios** das faixas (por peso), com vigência.

**A dúvida:** o preço por faixa vem de uma tabela que se repete entre compromissos, ou é sempre negociado caso a caso? A faixa depende do peso da carcaça?

**Implementado:** o preço das faixas 1 a 5 é **digitado por operação**, e a faixa é informada pelo frigorífico (nunca deduzida), como o cliente pediu. Se houver padronização comercial recorrente, o cadastro reutilizável vem depois, sem mudar a estrutura.

**Custo de mudar:** médio. Tabela de preço com vigência e faixa por peso é cadastro novo em `apps/commercial`; preencher o compromisso a partir dela é pequeno.

---

## #37 — 🟢 O que é "custo total" e "custo por cabeça" no painel *(Fase 5)*

**Onde:** o cartão da safra (`dashboards/selectors.py`) soma só os custos **avulsos** (`source_purchase__isnull=True`) e divide o custo por cabeças do rebanho **atual**. O documento (12.1) pede "custo total, custo por cabeça, kg e @" junto com valor comprado, frete e comissão.

**A dúvida:** "custo total" inclui a aquisição dos animais? "Custo por cabeça" é custo de aquisição por cabeça comprada, ou custo da safra por cabeça em estoque? Os dois são úteis e diferentes — qual o painel mostra?

**Por que importa:** é o número que o produtor compara com a planilha e com o consultor ([#14](#14--margem-por--qual-denominador-e-o-que-fazer-com-lote-aberto-fase-3)).

**Implementado:** o painel atual, sem mudança.

**Custo de mudar:** baixo. Um serviço novo de indicadores por safra; o painel passa a consumi-lo.

---

## #38 — 🟡 Lotação por pasto (UA/ha) e alocação de lote em pasto *(Fase 6)*

**Onde:** seção 9 do documento e abas da `REPORTAGEM IVAN` (lotação em UA/ha, alocação de lote em pasto). O sistema tem `Paddock` (área e capacidade em UA) e **nada o consome**.

**A dúvida:** os usuários querem alocar lote em pasto e ver lotação (UA/ha)? A operação faz **cria** (tem matrizes) ou só recria e engorda? Quem alimentaria equipe e infraestrutura — e quem leria?

**Implementado:** o escopo definido pelo cliente (reprodução, confinamento, inventário, mortalidade com causa, infraestrutura e máquinas, tudo **resumido**; chuva, suplementação e consumo ficam fora) está pronto — ver [13](13-gestao-a-pasto-e-indicadores-do-consultor.md). **Falta** só a lotação por pasto.

**Custo de mudar:** médio — um lote (ou animal) alocado em pasto, e o indicador derivado.

---

## #39 — 🟡 Eficiência biológica e a base da arroba viva *(Fase 6)*

**Onde:** abas `INVENTARIO`, `ANÁLISE PECUÁRIA`, `PLACAR` e `TIR` da `REPORTAGEM IVAN`.

**A dúvida:** (a) **eficiência biológica** depende do consumo de matéria seca, que o sistema não registra (consumo detalhado ficou fora do escopo): os usuários vão registrar consumo? (b) O **inventário valorizado** usa a **arroba viva de 30 kg**, tirada da planilha do consultor (`330 kg = 11 @`) — é a base deles? E o preço da @ é informado por quem, e com que frequência?

**Implementado:** curva ABC, inventário valorizado, TIR, mortalidade por causa, confinamento e indicadores reprodutivos ([13](13-gestao-a-pasto-e-indicadores-do-consultor.md)); o preço da @ é **informado** na tela e a arroba viva é a constante `KG_POR_ARROBA_VIVA` (`reports/consultor.py`). Eficiência biológica **não aparece**.

**Custo de mudar:** (b) uma constante; (a) um relatório novo, depois que houver consumo registrado.

---

## #40 — 🟢 Mudança de lote e mudança de fazenda como tipos próprios *(Fase 1)*

**Onde:** a lista de movimentações do documento (seção 9) separa "mudança de lote" e "mudança de fazenda" de "transferência". No sistema as duas são `TRANSFERENCIA`, distinguidas pelos campos de origem e destino.

**A dúvida:** o produtor precisa **filtrar ou relatar** as duas separadamente? Ou transferência entre fazendas e entre lotes se lê bem pelos campos?

**Implementado:** um tipo só, com 2 linhas no razão (regra 1).

**Custo de mudar:** baixo, se for só rótulo e filtro derivado dos campos. Tipo novo no banco só se a regra de geração de linhas diferir.

---

## #42 — 🟢 O que o pedido de acesso deve conter e como confirmar quem pede *(Fase 0)*

**A dúvida:** basta nome, e-mail, telefone e uma frase de justificativa? Falta algo (fazenda, função, quem indicou)? Convém limitar a domínio de e-mail da empresa, ou o administrador decide caso a caso?

**Por que importa:** o pedido é aberto ao público. Pedir pouco deixa o administrador decidindo no escuro; pedir muito afasta quem tem sinal ruim no campo.

**Implementado:** nome completo, e-mail, telefone opcional e texto livre (10 a 1.000 caracteres). O e-mail **não é confirmado antes**: o link para definir a senha só vai ao endereço informado, então só o dono dele entra — e o aviso ao administrador diz isso. Limites: 5 pedidos/hora por IP, 20 avisos por e-mail/hora, um pedido pendente por e-mail, campo-isca contra robô. Nada de CAPTCHA.

**Custo de mudar:** baixo. Campos novos: `AccessRequest` + `SolicitacaoAcessoForm`. Restrição de domínio: um `clean_email`. CAPTCHA só se o abuso aparecer.

---

## #44 — 🟡 Exportação de dados além do PDF *(Fase 6)*

**Onde:** tela *Exportações* ([regra 10](10-exportacao-de-dados.md)).

**A dúvida:** o cliente definiu que **todos os perfis exportam relatórios em PDF**, no escopo de fazendas de cada um. Ficam em aberto as regras de **Excel**, de **auditoria** e de **retenção de arquivos**: quem leva dado em massa para fora? O `GESTOR` deve ver a trilha de auditoria exportada? Algum papel de campo precisa exportar o próprio escopo?

**Por que importa:** exportar é o jeito mais fácil de vazar a base inteira — compra, custo, parceiros com CPF/CNPJ, contas bancárias.

**Implementado:** a tela de exportação de **dados** abre para `ADMIN`, `GESTOR`, `ESCRITORIO` e `FINANCEIRO` (`CAMPO` e `CONSULTA` não); cada conjunto segue a regra da tela correspondente; contas bancárias só para quem já vê dado bancário; usuários e auditoria só para o `ADMIN`; só quem pediu baixa o arquivo; cada pedido e download vão para a auditoria. Relatórios (PDF, CSV, Excel) abrem para todos, no escopo.

**Custo de mudar:** baixo. Papéis da tela: `PAPEIS_QUE_EXPORTAM` em `apps/exports/permissions.py`; de um conjunto: o campo `permitido` em `apps/exports/catalog.py`.

---

## #45 — 🟢 Por quanto tempo o arquivo fica e o que a exportação não é *(Fase 6)*

**Onde:** tela *Exportações* e `manutencao` (Celery beat).

**A dúvida:** (a) o arquivo exportado fica disponível por **7 dias** e depois é apagado do servidor — é o prazo certo? (b) A exportação **não** é um instantâneo atômico do banco: os conjuntos são lidos um depois do outro. Para quem sai do sistema, isso basta, ou é preciso uma exportação "congelada" num instante só? (c) O PDF mostra só as colunas principais e vai até 20.000 linhas por conjunto: aceitável?

**Por que importa:** (a) o arquivo é dado do negócio parado em disco, sem a proteção de papel e escopo do sistema; quanto mais fica, maior a janela de vazamento. (b) Quem exporta "tudo" para guardar de vez espera consistência: um lançamento feito durante a leitura poderia aparecer num conjunto e faltar em outro. (c) PDF de tabela larga é ilegível; o dado completo está nos outros formatos.

**Implementado:** (a) 7 dias (`EXPORT_RETENTION_DAYS`); o dono pode apagar antes; o **pedido** e a auditoria nunca saem. (b) Sem snapshot; o `LEIA-ME` do pacote e a ajuda da tela dizem isso, e apontam o `deploy/backup.sh` para a cópia exata. (c) Como descrito.

**Custo de mudar:** (a) uma variável de ambiente. (b) médio: ler tudo numa transação `REPEATABLE READ` por uma conexão separada, com o custo de segurar o snapshot por minutos. (c) baixo: lista de colunas por conjunto (`Conjunto.pdf`) e `PdfEscritor.LIMITE_DE_LINHAS`.

---

## #47 — 🟡 Mais de uma empresa: troca de empresa no topo e escopo *(Fase 0)*

**Onde:** barra de contexto Empresa · Safra · Fazenda (`apps/core/context.py`, `templates/partials/context_bar.html`) e [`docs/ux/01-navegacao-e-ui.md`](../ux/01-navegacao-e-ui.md).

**A dúvida:** (a) as duas empresas cadastradas são operações separadas, cada uma com suas fazendas, safras e rebanho — ou a segunda foi teste? (b) Quem tem acesso amplo (`has_broad_access`) deve ver todas as empresas ou só as dos seus vínculos? (c) Um usuário comum pode ter fazendas de empresas diferentes e alternar entre elas? (d) Fazenda sem Unidade (`business_unit` é opcional) pertence a qual empresa?

**Por que importa:** hoje a Empresa é só um texto na barra. `current_company()` devolve a primeira empresa ativa por `id`, então a segunda **nunca é a atual**: as safras dela não aparecem no seletor e as telas que usam a safra atual (painel, compras, vendas, custos, rebanho, relatórios, exportações, contrato) só enxergam a primeira. Já as fazendas **não** são filtradas por empresa — `available_farms` ignora a Unidade —, então as das duas empresas aparecem misturadas. Resultado: o usuário cria a segunda empresa e não consegue operá-la, e os totais por fazenda podem somar dados de empresas diferentes sem aviso.

**Implementado:** nada além do comportamento acima — **conhecido e deixado assim por decisão de Warley (2026-10-02)**, até responder as perguntas. Operar com uma empresa só funciona normalmente. Não cadastrar dado real na segunda empresa enquanto isso estiver aberto.

**Plano reversível quando for resolver:**
1. Guardar a empresa escolhida na sessão (`ctx_company_id`), com `current_company(request, user)` e a empresa de menor `id` como padrão.
2. Transformar o texto da barra num seletor (view `trocar_empresa`, igual à de safra e fazenda).
3. Ao trocar de empresa, zerar a safra e a fazenda escolhidas.
4. Filtrar `available_farms` pela empresa atual (via Unidade) e definir a regra da fazenda sem Unidade.
5. Limitar as empresas listadas às do escopo do usuário (ADR 0003), com `404` para empresa fora do escopo; teste de que um usuário não alcança a empresa alheia.
6. Trocar as chamadas `ctx.current_company()` (13 pontos em views, `contract.py` e `exports/forms.py`) pela nova assinatura.

**Custo de mudar:** médio. O modelo já tem `Season.company` e `Farm.business_unit → Company`; falta o contexto de sessão, o seletor e o filtro de fazendas. Não há migração de dados, salvo se (d) pedir tornar a Unidade obrigatória na Fazenda.

---

## #48 — 🟢 Dashboard: quem vê dinheiro, limiares das leituras e o "resultado da safra" *(Fase 6)*

**Onde:** `apps/dashboards/bi/` — `escopo.py` (`PAPEIS_SEM_DINHEIRO`), `insights.py` (limiares), `vendas.py` (`resultado_da_safra`). Regra: [11](11-dashboard-analitico.md).

**A dúvida:** (a) o pessoal de **campo** deve ver preço, custo e resultado, ou só rebanho e desempenho dos lotes? (b) Os limiares das leituras automáticas estão certos para esta operação: preço de compra que oscila mais de 10%, um vendedor com mais de 40% do valor comprado, custo por cabeça/dia que sobe mais de 15%, um centro com mais de 35% do custo, lote com GMD abaixo de metade da média, rendimento de carcaça que muda mais de 1 ponto? (c) O "resultado da safra" é a **soma do resultado dos lotes com venda na safra** (cada lote por inteiro, com custo pela fração já vendida) — ou deve ser só a receita e o custo **do período**, mesmo que o lote atravesse safras? (d) O custo por @ do dashboard deve usar o custo do lote com venda na safra ou só dos lotes **encerrados** (como o painel inicial)?

**Por que importa:** (a) preço e comissão são dado comercial — o ciclo de compra já esconde de `CAMPO` ([#25](99-pendencias-resolvidas.md#25)); (b) leitura com limiar errado vira ruído ou deixa passar problema real; (c) e (d) decidem se o número do dashboard bate com a contabilidade da safra ou com a do lote.

**Implementado:** (a) `CAMPO` vê só *Visão geral* (sem dinheiro), *Rebanho* e *Lotes*; as demais abas dão `403`. (b) Os valores acima, todos constantes nomeadas no topo de `insights.py`, `compras.py` e `custos.py`. (c) Soma por lote, com o aviso "27 de 30 lotes com resultado" ao lado do número. (d) O cartão da *Visão geral* usa o **mesmo seletor do painel inicial** (lotes encerrados na safra); a aba *Vendas* mostra a margem por @ de todos os lotes com carcaça — os dois rótulos dizem qual é qual.

**Custo de mudar:** baixo. (a) uma tupla em `escopo.py`; (b) uma constante cada; (c) e (d) uma função em `vendas.py`/`visao_geral.py`, sem migração: nada é gravado.

---

## Como usar este documento

1. **Antes de usar o acerto de verdade:** confirmar #21 com o contador.
2. **Antes de apresentar:** o que entra na reunião com os usuários está em [14](14-roteiro-de-validacao-com-os-usuarios.md); a de **#47** (mais de uma empresa) precisa ser decidida antes de cadastrar dado real na segunda empresa.
3. **Decididas na reunião:** #19 (segundo fator), #29 (status), #35 (tabela de preço), #38 (lotação), #39 (consumo e arroba viva), #44 (exportações).
4. **Podem esperar:** #3, #26, #37, #40, #42, #45, #48 — funcionam com os padrões reversíveis e não bloqueiam nada.
5. Resolvida uma pendência: registrar a resposta **no próprio item**, com data e quem respondeu, **mover o item para** [99-pendencias-resolvidas](99-pendencias-resolvidas.md) e só então mexer no código. A pergunta e a resposta ficam no arquivo de resolvidas — apagar a pergunta é perder o motivo da regra.
