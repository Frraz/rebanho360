# Pendências de negócio

Dúvidas encontradas na análise das planilhas e dos relatórios legados que **não foram resolvidas inventando regra**.

Cada uma tem: a pergunta, por que importa, o que foi implementado provisoriamente e o custo de mudar depois.

**Status:** 🔴 bloqueia · 🟡 resolver antes da fase indicada · 🟢 pode esperar

---

## #1 — ✅ O que é a EVOLUÇÃO de categoria? *(Fase 1)*

**Onde:** abas de fazenda, coluna `EVOLUÇ`, dentro do bloco ENTRADAS.

**A dúvida:** a coluna aparece só como entrada, sem contrapartida de saída visível. Se um animal "evolui" de `Machos Desm. até 12m` para `Machos 13 a 24 meses`, ele deveria sair de uma categoria e entrar na outra. Só que a planilha tem uma coluna só. Como a saída é registrada hoje — valor negativo na linha de origem?

**Por que importa:** é a diferença entre o rebanho fechar ou não. Se evolução só soma, o total infla a cada reclassificação.

**Implementado:** movimento de **2 linhas**, igual à transferência — sai da categoria de origem, entra na de destino, soma zero. A reclassificação nunca altera o total do rebanho.

**Custo de mudar:** baixo. É trocar a regra de geração de linhas de um tipo de movimento.

**✅ Confirmado em 2026-10-01** por Warley (dono do produto): é exatamente a reclassificação por idade descrita acima. Modelo de 2 linhas aprovado sem ressalva — segue para implementação na F1-06/F1-07.

---

## #2 — 🟡 A aba `GERAL` fecha em −140 cabeças *(Fase 1)*

**Onde:** aba `GERAL` (oculta), linha `Machos Desm. até 12m`: `TRANSF. S = 140`, `TRANSF. E = 0`, `FINAL = −140`.

**A dúvida:** três possibilidades. (a) Erro de preenchimento — a entrada nunca foi lançada. (b) Os animais foram para uma fazenda de terceiro, fora do grupo. (c) A aba `GERAL` não consolida todas as fazendas.

**Por que importa:** se for (b), o sistema precisa de um destino cadastrável fora do grupo — e a transferência vira saída de verdade, não deslocamento interno.

**Implementado:** transferência sempre interna, com as duas pontas obrigatórias. Saída para fora do grupo se registra como `VENDA` ou `CONSUMO_DOACAO`. Se a resposta for (b), acrescenta-se um tipo `TRANSFERENCIA_EXTERNA`.

**Custo de mudar:** baixo, se resolvido antes da carga histórica. Alto depois — os 140 teriam que ser reclassificados à mão.

**⏸️ Decisão em 2026-10-01:** Warley não sabe a resposta ainda. Decidiu explicitamente seguir com o padrão reversível (transferência sempre interna) para não travar a Fase 1, e resolver antes da **carga histórica real** (Fase 2 — `imports`). Continua 🟡 aberta; não resolver antes de importar o histórico de verdade.

**🔎 O que o importador da Fase 2 achou na planilha real (2026-10-01):** os −140 são **duas linhas `TRANSF. S` na aba `GOIANO`** (95 em 20/07/2025 e 45 em 20/08/2025, ambas com `DESTINO = GOIANO`) e **nenhuma `TRANSF. E` em aba nenhuma**. As datas e quantidades coincidem com as compras de 96 e 40 cabeças de 20/07 e 20/08 em São Francisco — indício de que os animais foram comprados para São Francisco e seguiram para Goiano, com a saída lançada na aba errada (a de Goiano, e não a de São Francisco). É só indício. O importador **não pareia nem inventa**: as duas linhas ficam como pendência na prévia, com as ações *ignorar* ou *definir origem e destino* — o custo de decidir é o clique do usuário, antes de importar. Resolver esta pendência agora vira uma decisão de 2 cliques.

---

## #3 — 🟡 O que é "PARCERIA"? *(Fase 2)*

**Onde:** coluna `PARCERIA` nas abas `COMPRA DE GADO` e `VENDAS`. Valor `-` em **todas** as linhas.

**A dúvida:** a coluna existe, então alguém a criou por um motivo. Há operação em parceria, arrendamento ou meação? Quem é o parceiro e como se divide?

**Por que importa:** afeta quem é dono do animal, como o custo é rateado e como o resultado é dividido. É estrutural — não é um campo a mais.

**Implementado:** campo `partnership` como texto livre, preservado na importação, sem efeito em cálculo algum.

**Custo de mudar:** médio a alto. Se houver divisão de resultado, mexe em rateio de custo, resultado por lote e provavelmente em titularidade do rebanho.

**Fase 2:** `Purchase.partnership` existe como texto livre; o importador de compras o preserva (`-` vira vazio). Continua sem efeito em cálculo. Nenhuma compra da planilha real tem valor nele.

---

## #4 — 🟢 A comissão incide sobre bruto ou líquido? *(Fase 5)*

**Onde:** aba `CUSTOS`, 2 lançamentos "COMISSÃO CORRETOR" (R$ 1.966,50 e R$ 900,00), lançados à mão. No relatório legado `05_Relatorio_Comissao_por_Comprador.png`, a coluna aparece como `0,00 V` — sem base visível.

**A dúvida:** a comissão do corretor é percentual sobre o valor da compra, valor fixo por cabeça, ou negociada caso a caso? Se percentual, sobre o valor bruto ou líquido de frete e impostos?

**Por que importa:** só na Fase 5, quando a comissão passar a ser calculada em vez de digitada.

**Implementado:** campo `commission_value` digitado na compra. Nenhum cálculo automático. O `CommissionService` da Fase 5 nasce isolado, para ser ajustado sem tocar em nada mais.

**Custo de mudar:** baixo, enquanto a comissão for digitada.

**Fase 5 (2026-10-02, decisão de Warley):** a pergunta segue **aberta**, e a Fase 5 foi construída **sem responder**. `CommissionRule` guarda tipo (`PERCENTUAL` ou `POR_CABECA`) e, no percentual, a **base** (`BRUTO` ou `LIQUIDO`), com comprador, categoria e vigência. Padrão `BRUTO`, escolhido na regra. `CommissionService` é uma função isolada (`apps/commercial/commission.py`); **a regra aplicada fica copiada no compromisso** quando ele é aprovado (snapshot). Responder #4 é trocar o padrão da regra — as operações antigas não mudam.

---

## #5 — 🔴 "SÃO FRANCISCO" e "SÃO FRANCISCO II" são a mesma fazenda? *(Fase 1 — bloqueia)*

**Onde:** aba `SÃO FRANCISCO` registra as movimentações e recebe **todas** as 954 cabeças compradas. Aba `VENDAS` registra as 3 vendas saindo de `SÃO FRANCISCO II`. Não existe aba `SÃO FRANCISCO II`.

**A dúvida:** são duas fazendas distintas, ou fazenda e retiro/unidade da mesma? Se distintas, por que não há aba de movimentação da segunda — e como os animais chegaram lá sem transferência registrada?

**Por que importa:** **bloqueia a carga histórica.** Sem resposta, o sistema não sabe de onde saíram os 354 animais abatidos. E há risco de duplicar uma fazenda no cadastro, o que contamina todo relatório por fazenda daí em diante.

**Implementado:** nada. É a primeira pergunta a fazer antes de importar.

**Custo de mudar:** alto depois da carga. Desmembrar ou fundir fazenda significa reprocessar todo o razão.

**⏸️ Decisão em 2026-10-01:** Warley não sabe a resposta ainda. Decidiu explicitamente seguir com o padrão reversível — as duas fazendas continuam cadastradas como registros distintos (como o `seed_demo` da F0-15 já fez), sem reconciliar a origem das cabeças que "apareceram" em São Francisco II. Isso **não bloqueia mais a F1-02** (CRUD de fazenda não depende da resposta), mas continua 🔴 bloqueando a **carga histórica real** (Fase 2 — `imports`): sem resposta até lá, a importação do razão de São Francisco II fica sem origem rastreável.


**🔎 O que a Fase 3 achou na planilha real (2026-10-01):** a aba `SÃO FRANCISCO` (a de movimentações) **já registra os 3 abates** — 84, 189 e 81 cabeças, `Machos 25 a 36 meses`, as mesmas 354 de `VENDAS`, com datas iguais ou a 1 dia (03/08, 26/03 × 27/03, 23/04 × 24/04). Em `VENDAS` a fazenda desses mesmos abates é `SÃO FRANCISCO II`. É indício forte de que **"São Francisco II" é o nome que `VENDAS` dá à mesma fazenda** — mas continua indício: o produtor responde. Efeito prático no sistema: o importador de vendas **não depende** da resposta — ele vincula cada venda ao abate que já está no razão (ver [#12](#12--pesos-de-saída-divergem-entre-as-abas-fase-3)) em vez de debitar uma fazenda sem saldo.
---

## #6 — 🟡 Quem é "ONODA"? *(Fase 2)*

**Onde:** coluna `PAGADOR` da aba `CUSTOS` — valor único nas 417 linhas que têm a coluna preenchida (235 são lançamentos reais; 182 estão em branco com o pagador arrastado).

**A dúvida:** é a empresa que paga, um sócio, uma conta bancária, ou um escritório de contabilidade?

**Por que importa:** define se vira `Company`, `Partner` ou `BankAccount`. E se há mais de um pagador possível no futuro, o campo precisa ser FK desde já.

**Implementado:** campo `payer` como FK opcional para `Partner`. Na importação, cria-se um parceiro "ONODA" sem papel definido.

**Custo de mudar:** baixo. É um `UPDATE` e uma migração de campo.

**Fase 2:** o importador de custos cria um único `Partner` "ONODA", **sem nenhum papel**, e o liga como `payer` de todos os lançamentos. Responder a pergunta é editar esse parceiro (ou trocar o pagador em massa).

---

## #7 — 🟡 Rendimento de carcaça: informado ou calculado? *(Fase 3)*

**Onde:** aba `VENDAS`, colunas `RENDIMENTO %` e `SOMA RENDIMENTO`. No abate de ago/2025: `RENDIMENTO %` = 0,5133 e `SOMA RENDIMENTO` = 43,12. Só a primeira bate com `carcaça ÷ peso vivo`.

**A dúvida:** duas perguntas. (a) O rendimento vem no romaneio do frigorífico ou é calculado pela fazenda? (b) O que `SOMA RENDIMENTO` mede? Não é percentual e não é arroba.

**Por que importa:** se o frigorífico informa, é dado a conferir — e divergência entre o informado e o calculado é uma pendência a destacar na tela, exatamente o tipo de erro que custa dinheiro.

**Implementado:** rendimento sempre **calculado** de `carcaça ÷ peso vivo`. `SOMA RENDIMENTO` não é importada. Alerta (não bloqueio) fora da faixa 40%–65%.

**Custo de mudar:** baixo. Acrescentar `reported_yield` e comparar.

**🔎 Fase 3 (2026-10-01):** implementado como a decisão acima: rendimento **sempre calculado** (`CarcassService`), alerta fora de 40%–65%, `SOMA RENDIMENTO` não importada. O importador de vendas recalcula os seis indicadores e **compara com a planilha**; o `RENDIMENTO %` bate nas 3 vendas (51,33% · 56,45% · 56,79%). A pergunta (a) segue aberta — e agora tem consequência prática: o rendimento depende do **peso vivo**, e o peso vivo diverge entre abas ([#12](#12--pesos-de-saída-divergem-entre-as-abas-fase-3)).

---

## #8 — 🟢 O produtor vende por faixa de preço? *(Fase 5)*

**Onde:** relatórios legados `02_Contrato_Compra_Animais` e `03_Relatorio_Programacao_de_Abate` — o frigorífico Boi Brasil negocia com Faixa 1 a Faixa 5 (ex.: 216,00 / 237,60 / 248,40 / 270,00 / 270,00).

**A dúvida:** esse é o modelo do frigorífico. O produtor também recebe por faixa quando vende para a Coperfrigu, ou é preço único por @?

**Por que importa:** na aba `VENDAS` só há um `VALOR POR @` por operação, o que sugere preço único. Mas pode ser a média de faixas aplicadas no romaneio.

**Implementado:** preço único por operação. Faixas ficam para a Fase 5.

**Custo de mudar:** médio. Exige tabela de faixas e recálculo do valor por classificação.

**Fase 5 (2026-10-02):** faixas existem **só no compromisso de compra** (`CommitmentItem`, Faixa 1 a 5). **A venda segue com preço único** (`Sale.total_value`): a Fase 5 é o ciclo de compra, e a pergunta — o produtor recebe por faixa da Coperfrigu? — continua aberta. Como a escolha da faixa é outra dúvida, ver [#20](#20--como-se-escolhe-a-faixa-de-preço-de-cada-linha-do-romaneio-fase-5).

---

## #9 — 🟡 Quem pode excluir registro confirmado? *(Fase 0)*

**Onde:** decisão de permissão, não achado de planilha. Nasce da regra de que [toda ação é editável e excluível](06-edicao-exclusao-e-auditoria.md).

**A dúvida:** com mais de 10 pessoas entre campo e escritório, `ESCRITORIO` deve poder **excluir** operação confirmada, ou apenas **editar**? E `CAMPO` pode excluir a própria movimentação depois de confirmada?

**Por que importa:** exclusão desfaz efeitos em cascata. Mesmo com auditoria completa, alguém precisa ir olhar para perceber — e ninguém olha auditoria todo dia. Quanto mais gente pode apagar, maior a chance de um erro ficar semanas sem ser notado.

**Implementado:** editar é de `ESCRITORIO`, `GESTOR` e `ADMIN`. Excluir é de `GESTOR` e `ADMIN`. Motivo obrigatório nos dois casos. `CAMPO` edita e exclui apenas o que criou, e apenas enquanto ninguém dependa daquilo.

**Custo de mudar:** baixo. É uma linha em `permissions.py`.

---

## #10 — 🟡 A compra de 126 cabeças de 27/04/2026 não está na aba da fazenda *(Fase 2)*

**Onde:** `COMPRA DE GADO` soma **954** cabeças; as linhas `COMPRA` da aba `SÃO FRANCISCO` somam **828**. A diferença é exatamente a compra de **126 cabeças, R$ 388.080,00, em 27/04/2026** — as outras três compras desse dia (130 + 120 + 18 = 268) aparecem na aba, essa não.

**A dúvida:** a compra de 126 aconteceu mesmo e só faltou lançar na aba da fazenda, ou foi uma compra que não se concretizou e ficou na aba de compras?

**Por que importa:** o `FINAL` de São Francisco na planilha é **1.954**; com as 954 compras, o sistema fecha em **2.080**. As duas verdades convivem até alguém responder. Importar nenhuma das duas em silêncio foi a decisão.

**Implementado:** a compra entra **uma vez só, pela aba `COMPRA DE GADO`** (as linhas `COMPRA` das abas são ignoradas — senão o rebanho dobra). A prévia da importação de movimentações **avisa a diferença** ("as linhas COMPRA da aba somam 828, mas as compras importadas somam 954 — diferença de 126"), e o `conferir_importacao` a mostra como divergência explicada (`Saldo São Francisco: 1.954 × 2.080, +126`).

**Custo de mudar:** baixo. Se a compra não existiu: excluir a `CP` correspondente (desfaz movimento, custo e lote). Se existiu: nada a fazer — a planilha é que estava incompleta.


**🔎 O que a Fase 3 achou (2026-10-01) — indício, não resposta:** a aba `PESAGENS E CONFERENCIA` tem um bloco (`AP-AS`) de **268** pesagens em 27/04/2026 — exatamente 130 + 120 + 18, as três compras desse dia que **estão** na aba da fazenda. As 126 cabeças da compra que **não** está lá também **não têm pesagem de entrada**. Dois pontos independentes concordando com a aba da fazenda (828), contra a aba de compras (954). Pode ser que a compra de 126 exista e só não tenha sido pesada. Continua dependendo do produtor.
---

## #11 — 🟡 Lançamentos de custo com ano digitado errado *(Fase 2)*

**Onde:** aba `CUSTOS`, **30 lançamentos** com data `03/01/2025` (fora de qualquer safra) e `MÊS = JANEIRO`, `ANO = 2026`, `SAFRA = 2025/2026`. As colunas digitadas contradizem a data.

**A dúvida:** o ano certo é 2026 (como dizem `ANO` e `SAFRA`), ou 2025 (como diz a data)?

**Implementado:** o importador **não corrige e não descarta**: vira pendência com sugestão "ano corrigido pela coluna ANO" (`03/01/2026`), que só vale quando o usuário aceita o grupo. É exatamente o caso que a spec previu para `MÊS`/`ANO` ("redundantes com `DATA` e sujeitas a divergir").

**Custo de mudar:** baixo — antes de importar, é um clique; depois, editar o lançamento com motivo.


---

## #12 — 🟡 Pesos de saída divergem entre as abas *(Fase 3)*

**Onde:** os 3 abates aparecem em três lugares, com pesos vivos diferentes:

| Abate | `VENDAS` | aba `SÃO FRANCISCO` | `PESAGENS E CONFERENCIA` |
|---|---|---|---|
| 03/08/2025 · 84 cb | 43.540 kg | 47.040 kg | **43.540 kg** (84 brincos) |
| 26-27/03/2026 · 189 cb | 106.680 kg | 115.617 kg | — |
| 23-24/04/2026 · 81 cb | 45.000 kg | 47.878 kg | **47.878 kg** (81 brincos) |

**A dúvida:** qual é o peso vivo de saída? Em agosto as pesagens concordam com `VENDAS`; em abril, com a aba da fazenda — e `45.000` é redondo demais para ser soma de pesagem. O peso vivo é o denominador do **rendimento** (abril: 56,79% com 45.000 kg, **53,37%** com 47.878 kg) e é o que o GMD e a @ produzida usam.

**Por que importa:** muda o rendimento, o peso médio e qualquer comparação entre lotes. E é exatamente o tipo de número que o produtor leva ao frigorífico.

**Implementado:** a venda guarda o peso que **a aba `VENDAS` informa** (é o documento comercial, com carcaça e valor). O movimento já importado da aba da fazenda **não é alterado**. A diferença vira **aviso** na prévia e na tela da venda ("peso na venda 45.000 kg × peso no razão 47.878 kg"), nunca correção silenciosa. Não se escolhe lado.

**Custo de mudar:** baixo. É editar a venda (com motivo) — a auditoria guarda os dois valores.

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

## #15 — 🟢 Dois números que o sistema precisa e ninguém informou *(Fase 3)*

**(a) Rendimento de carcaça de entrada.** A @ produzida precisa da carcaça de entrada, que nunca é medida: é estimada (`peso vivo × rendimento`). Qual rendimento usar? **Implementado:** nenhum valor padrão. Sem ele a @ produzida mostra "—" e diz que falta; o relatório de desempenho aceita um valor informado na hora e **marca a conta como estimativa**.

**(b) Mortalidade "acima do normal"** (regra do painel de pendências). Qual é o normal? **Implementado:** limite de **2%** por safra e fazenda, em `MORTALIDADE_LIMITE_PERCENTUAL` (`settings`), só para a regra do painel não nascer morta. Palpite do desenvolvimento, não regra do produtor.

**Custo de mudar:** baixo — uma constante e um parâmetro.

---

## #16 — 🟡 Prazo e parcelamento do pagamento *(Fase 4)*

**Onde:** a spec original previa `payment_terms` na compra, mas a planilha não tem a informação — `COMPRA DE GADO` e `VENDAS` não dizem quando se paga nem quando se recebe. A aba `ADF E COMPRAS`, que controlaria isso, está toda zerada.

**A dúvida:** como o produtor paga e recebe — à vista, em prazo único, ou **parcelado**? O frigorífico paga em quantos dias depois do abate?

**Implementado:** `payment_days` opcional na compra e na venda (dias a partir da data da operação; vazio = vence na data). Gera **um título por componente**; parcelamento se faz com **baixa parcial** (o título fica `PARCIAL` até quitar), e o vencimento é ajustável no próprio título.

**Custo de mudar:** médio. Parcelas de verdade pedem vários títulos por componente (a chave de idempotência ganharia o número da parcela) e uma tela de "gerar parcelas".

---

## #17 — 🟡 Quem recebe o frete, a comissão e os impostos — e quem aprova e paga *(Fase 4)*

**Onde:** a compra tem `freight_value`, `commission_value` e `tax_value`, mas **nenhum campo diz a quem** (`Purchase` só tem o vendedor). E o roadmap fala em `finance.approve_payment` e `finance.execute_payment` sem dizer quais papéis.

**A dúvida:** (a) frete, comissão e impostos se pagam a quem — transportador, corretor, guia de imposto? Entram como título mesmo quando já foram pagos no ato? (b) Quem **aprova** pagamento — o `GESTOR`, o `FINANCEIRO`, o dono? E quem **executa**?

**Implementado:** (a) cada valor positivo gera um título **sem favorecido** ("a definir"), que o financeiro completa — ou cancela, se já foi pago. Só os animais têm favorecido (o vendedor). (b) **Aprovam:** `ADMIN`, `GESTOR`, `FINANCEIRO`. **Executam a baixa:** `ADMIN`, `FINANCEIRO`. Quem aprovou não dá a baixa se houver outro usuário que possa — com um só usuário financeiro, passa, e a auditoria marca.

**Custo de mudar:** baixo. (a) é a lista `COMPONENTES_DA_COMPRA` em `finance/services.py` (e, se vier o transportador, um campo na compra); (b) é uma linha por papel em `finance/permissions.py`.

---

## #18 — 🟢 O histórico da planilha não gera título *(Fase 4)*

**Onde:** as 13 compras (R$ 2,46 mi) e os 3 abates importados nas Fases 2 e 3. Quase tudo já foi pago e recebido fora do sistema.

**A dúvida:** o que dessa carga ainda está em aberto? Gerar título de tudo encheria "vencidos" de 2025 — o alerta deixaria de significar alguma coisa.

**Implementado:** o importador confirma com `gerar_titulos=False`. A tela **Operações sem título** (e o botão no detalhe de cada compra/venda) gera o título só do que o produtor disser que está em aberto; os demais ficam sem título, sem prejuízo para nada.

**Custo de mudar:** baixo. Se o produtor preferir tudo gerado e quitado, é um comando de uma linha que gera e dá baixa com data do fato.

---

## #19 — 🟢 Segundo fator: o que fazer ao trocar de celular *(Fase 4)*

**A dúvida:** quantas pessoas vão usar o aplicativo, e quem faz a redefinição quando alguém perde celular **e** códigos de recuperação?

**Implementado:** O segundo fator é opcional e recomendado a todos (decisão de Warley, 03/10/2026; antes era obrigatório para `ADMIN` e `FINANCEIRO`). Códigos de recuperação (10, uso único). Perdeu tudo: um `ADMIN` redefine pela tela de usuários (nunca o próprio) ou o servidor roda `manage.py resetar_segundo_fator` — ambos auditados, e as sessões do usuário são encerradas.

**Custo de mudar:** baixo. Voltar a exigir é recolocar a checagem em `two_factor.precisa_de_segundo_fator` e `precisa_configurar`.

---

## #20 — 🟡 Como se escolhe a faixa de preço de cada linha do romaneio *(Fase 5)*

**Onde:** relatório legado `04_Conferencia_do_Acerto`: cada linha do romaneio valorizado traz classificação **e** faixa (`G2 - Gordura Mediana · FAIXA 5`, `LESAO TRAUMATICA · FAIXA 3`). A mesma classificação aparece em faixas diferentes (`Magro · FAIXA 5`, `G1 · FAIXA 4`, `G2 · FAIXA 4` e `G2 · FAIXA 5`).

**A dúvida:** a faixa depende só da classificação, do peso da carcaça, dos dois? O contrato fixa a regra (por exemplo, "acima de 16 @ = Faixa 5") ou o frigorífico decide no abate?

**Por que importa:** a faixa define o preço da @ — e portanto o valor dos animais. Errar a regra é errar o valor pago.

**Implementado:** a faixa é **informada em cada linha do romaneio**, nunca deduzida. `CarcassClass.default_band` (opcional, vazio por padrão) só **sugere** a faixa na tela. O preço da linha é copiado do contrato (preço da faixa) e fica editável — a diferença entre o contratado e o aplicado aparece no acerto.

**Custo de mudar:** médio. Uma regra de faixa por peso e classificação vira uma função em `procurement/grading.py`, que preenche o que hoje o usuário escolhe.

---

## #21 — 🔴 Tributos, taxas e descontos do acerto: quem arca com cada um *(Fase 5)*

**Onde:** `04_Conferencia_do_Acerto`: Funrural, Fundepec, GTA, ICMS, taxa de abate, indenização, Incentivo Precoce, Idaterra, crédito GR-3, desconto, adiantamento. O roadmap exige confirmar **toda** regra tributária com o contador antes de implementar.

**A dúvida:** para cada um — alíquota, base de cálculo, e **quem arca** (nós, como custo da compra, ou o vendedor, retido do valor que pagamos)? O que é desconto de preço e o que é só movimento de caixa (adiantamento)?

**Por que importa:** é o item que o roadmap chama de passivo. Errar quem arca muda o custo do lote **e** o valor pago ao produtor.

**Implementado:** **nenhuma alíquota, nenhuma fórmula.** `TaxType` é cadastro (nome e natureza). Cada valor é **digitado** na linha do acerto. A natureza decide só o efeito, em um lugar (`procurement/settlement.py::TRATAMENTO_POR_NATUREZA`):

| Natureza | Efeito | Hipótese |
|---|---|---|
| `TRIBUTO`, `TAXA` | somam ao **custo de aquisição** (`tax_value`) e viram título de impostos, a definir | arcamos com o tributo |
| `DESCONTO` | **reduz o valor dos animais** (custo e pagamento) | o desconto muda o preço |
| `ADIANTAMENTO`, `CREDITO` | **reduzem o líquido a pagar** ao vendedor; não mudam o custo | é movimento de caixa |

**Custo de mudar:** baixo para o tratamento (uma tabela). Calcular por alíquota é trabalho novo — e só começa com a resposta do contador. **Resolver antes de usar o acerto de verdade.**

---

## #22 — 🟢 Rateio de frete, comissão e tributos entre itens de categorias diferentes *(Fase 5)*

**A dúvida:** um contrato com duas categorias gera duas compras. O frete (por viagem), a comissão e os tributos são do contrato inteiro. Dividir por cabeça recebida, por peso ou por valor?

**Implementado:** por **cabeça recebida**, sem centavo perdido (`ratear_em_centavos`). Descontos se dividem por **valor** dos animais — desconto de preço acompanha o preço.

**Custo de mudar:** baixo. Uma função, `procurement/settlement.py::ratear_extras`.

---

## #23 — 🟢 Quebra de viagem: desconta do valor? qual tolerância? *(Fase 5)*

**Onde:** o texto funcional pede "quebra de viagem" e "percentual de quebra", sem dizer se vira desconto.

**Implementado:** a quebra é **medida** — `(peso de origem − peso recebido) ÷ peso de origem` — e **alertada** acima de `QUEBRA_ALERTA_PERCENTUAL` (settings, **3%**, palpite do desenvolvimento, não regra do produtor). **Não desconta nada**: o valor dos animais sai do romaneio (ou das cabeças recebidas), nunca do peso de origem.

**Custo de mudar:** baixo. Um desconto automático por quebra acima da tolerância é uma linha de acerto gerada.

---

## #24 — 🟡 Quando os animais entram no rebanho: no recebimento ou na aprovação do acerto? *(Fase 5)*

**Onde:** o roadmap diz que `CONFIRMADA` é alcançada **depois do acerto aprovado**; o texto funcional diz que "o recebimento alimenta automaticamente o rebanho".

**Por que importa:** entre as duas datas o gado está no pasto e **não está no saldo**. Pode ser uma semana, pode ser um mês.

**Implementado:** entrada **na aprovação do acerto**, como o roadmap manda. A data da compra (e do movimento) é a do **primeiro recebimento** do item, não a do acerto — o saldo histórico fica certo para trás. O painel avisa "recebido, aguardando acerto" com as cabeças.

**Custo de mudar:** médio. Dar entrada no recebimento exige compra provisória por viagem.

**🔎 Auditoria de 2026-10-02:** o documento funcional diz, na seção 15, que "o recebimento deverá alimentar automaticamente o rebanho/lote" — a decisão acima diverge dele. Continua aberta e **não foi alterada** (decisão adiada por Warley). Dois caminhos, para quando decidir:
- **(A) Compra provisória por viagem:** o recebimento cria uma compra em rascunho e confirmada com valor provisório; a aprovação do acerto a ajusta. Rebanho certo desde o recebimento; o custo muda quando o acerto fecha.
- **(B) Entrada de rebanho na viagem, convertida na aprovação:** o recebimento só dá a entrada de cabeças (sem valor); o acerto aprovado a vincula à compra. Mais simples, mas cria um movimento sem compra de origem por um tempo.
Qualquer um exige um ADR e mexe em `Receiving.aplicar_efeitos` e em `closing.py`.

---

## #25 — 🟡 Quem aprova o acerto *(Fase 5)*

**Implementado:** lançam e corrigem `ADMIN`, `GESTOR`, `ESCRITORIO`; **aprovam e reabrem** `ADMIN` e `GESTOR`. O `ESCRITORIO` não aprova o que lançou. Palpite — ajuste em `procurement/permissions.py`, uma linha por papel.

**Ver também [#28](#28--aprovação-do-compromisso-em-duas-etapas-fase-5):** a mesma pergunta vale para o compromisso, que hoje quem lança também aprova.

---

## #26 — 🟢 Base do preço do item: @ de carcaça ou cabeça *(Fase 5)*

**Onde:** o contrato legado precifica em R$/@ de carcaça por faixa. A compra de bezerro do produtor é por cabeça (a planilha só tem `MÉDIA/CAB`).

**Implementado:** cada item escolhe a base. **@ de carcaça:** valor = Σ líquido do romaneio. **Cabeça:** valor = cabeças recebidas × preço unitário, sem romaneio.

**Custo de mudar:** baixo. É um campo do item.

---

## #27 — 🟡 Dados bancários no contrato e nos relatórios *(Fase 5)*

**Onde:** o documento funcional (seção 3.1) lista "dados bancários" entre o que o compromisso/contrato deve conter, e o contrato legado `02_Contrato_Compra_Animais` os traz (banco, agência, conta do produtor). O sistema **omite de propósito** (`procurement/contract.py`, `contrato.html`): a regra de segurança do projeto é nunca pôr dado bancário em log e servir anexo só por view autenticada.

**A dúvida:** o contrato é documento interno ("uso interno", como diz o legado) ou sai da empresa? Se for só interno, o dado bancário pode ir no PDF — que já é gerado e servido por view autenticada, com hash e quem gerou. Se sai para o produtor ou terceiros, não.

**Por que importa:** o contrato sem conta obriga a conferir o pagamento em outra tela.

**Implementado:** contrato **sem** dado bancário. Os dados existem em `BankAccount` e aparecem no título, com permissão.

**Custo de mudar:** baixo. É o template do contrato e a `template_version` (`contrato-v2`), sem tocar em dado.

**Divergência nova (2026-10-02):** a regra anterior era "dado bancário não vai em relatório" (`relatorios/01-catalogo.md`). O documento funcional pede banco, agência e conta na **programação de pagamentos** (seção 10), e o relatório foi feito assim — **só para quem já vê dado bancário** (`ADMIN`, `GESTOR`, `FINANCEIRO`, as mesmas permissões da tela do título), na tela, no CSV/XLSX e no PDF. Quem não tem a permissão recebe o relatório **sem** as três colunas, e os dados não chegam a sair do servidor para ele. O PDF gerado só é baixado por quem o gerou, `ADMIN` e `GESTOR`. A pergunta que fica: **uma planilha ou PDF com conta bancária de terceiros circulando é aceitável?** Se não: remover as colunas `banco`, `agencia` e `conta` de `programacao_de_pagamentos` (três linhas) e tirar a nota do relatório. Nada mais depende delas.

---

## #28 — 🟡 Aprovação do compromisso em duas etapas *(Fase 5)*

**Onde:** o documento funcional (seções 3.1 e 14) tem "aguardando aprovação" antes de "compromisso aprovado". No sistema, `aprovar_compromisso` é um clique, e quem lança (`ADMIN`, `GESTOR`, `ESCRITORIO`) também aprova (`procurement/permissions.py`). Só o **acerto** tem separação de funções.

**A dúvida:** o compromisso precisa de alguém que **não** o lançou para aprovar? Quem aprova — `GESTOR`, `ADMIN`, o dono? O `ESCRITORIO` pode aprovar o que ele mesmo lançou quando é o único usuário?

**Por que importa:** o compromisso fixa preço, faixas e comissão (snapshot). Aprovar o próprio lançamento é o erro que a separação de funções existe para pegar.

**Implementado:** nada mudou. Aprovação direta, como na Fase 5.

**Custo de mudar:** médio. Estado novo no compromisso (`ENVIADO_PARA_APROVACAO`), tela de fila de aprovação, uma regra de papéis e o recuo da etapa derivada. Segue o padrão do financeiro ("quem aprova não paga, havendo outro").

---

## #29 — 🟡 O que faz a operação avançar depois do acerto aprovado *(Fase 5)*

**Onde:** seção 14 do documento funcional: depois de "acerto aprovado" vêm "aguardando financeiro", "pagamento programado", "pago" e "encerrada". No sistema a etapa do compromisso (`selectors.etapa_do_compromisso`) **para em "Acerto aprovado"**; programação e pagamento existem só no título.

**A dúvida:** (a) "Pago" da operação é quando **todos** os títulos do acerto estão quitados? (b) "Encerrada" é automática (tudo pago e lote vendido?) ou um ato de alguém, com motivo? (c) Os 16 status "poderão ser parametrizados" — quais a operação realmente usa? "Em conferência" e "em faturamento" separam o quê, na prática?

**Por que importa:** é o que responde "o que falta fazer nesta compra?" sem abrir cinco telas.

**Implementado:** nada. A etapa continua derivada e termina no acerto.

**Custo de mudar:** baixo a médio. Estender a função derivada com os títulos (pago = nenhum título em aberto) é pequeno; "Encerrada" como ato é um campo e uma trava.

---

## #30 — 🟡 Quem é quem na negociação: produtor, pecuarista, fornecedor, comprador *(Fase 5)*

**Onde:** o documento lista produtor, pecuarista e fornecedor como papéis distintos, e "comprador principal" e "comprador adicional". O compromisso tem **um** campo `seller` ("Produtor") que aceita Produtor ou Fornecedor, e `commissioned` ("Comprador") que exige o papel **Comissionado**, não Comprador. O relatório legado de comissão chama o mesmo personagem de "Comprador"; o histórico usa "Pecuarista" para o dono do gado.

**A dúvida:** pecuarista e produtor são a mesma pessoa com dois nomes, ou o pecuarista é o dono do gado e o produtor o proprietário da fazenda de origem? O comprador **é** o comissionado? O comprador adicional divide a comissão?

**Por que importa:** muda os campos do compromisso, o contrato e o relatório de histórico.

**Implementado:** `seller` serve de produtor e de pecuarista; `commissioned` serve de comprador; `second_buyer` só informa e não divide comissão.

**Custo de mudar:** médio. Campo novo e migração de dados, mais o contrato e três relatórios.

---

## #31 — 🟡 Programação de pagamentos antes do acerto *(Fase 4/5)*

**Onde:** seção 4.3 do documento: "saídas automáticas após aprovação: programação de embarques **e de pagamentos**". No sistema, os títulos só nascem na aprovação do **acerto**, quando o valor final é conhecido; antes, não há o que programar.

**A dúvida:** o produtor quer ver, na aprovação do compromisso, uma previsão de quanto vai pagar e quando — mesmo sem o acerto? Sendo previsão, entra no fluxo de caixa?

**Por que importa:** sem isso, o fluxo de caixa só enxerga a compra depois do acerto, que pode vir semanas após o gado chegar.

**Implementado (2026-10-02):** o relatório **Programação de pagamentos** (`reports/services.py::programacao_de_pagamentos`, slug `programacao-de-pagamentos`) reúne os títulos a pagar **que já existem**: compra, favorecido, documento, vencimento, "pagar em", valor, saldo, banco, agência, conta, situação e "atenção" (sem favorecido, sem conta). Banco, agência e conta só saem para quem vê dado bancário. **Não cria título previsto.**

**Custo de mudar:** médio. Título previsto antes do acerto pede um estado "estimado" que o acerto substitui, e cuidado para não duplicar — a chave de idempotência por compra e componente continua valendo.

---

## #32 — 🟢 Pré-programação e números separados *(Fase 5)*

**Onde:** seções 1, 3.1 e 4.1 do documento: número da compra, da programação e do compromisso são **três**, e a pré-programação é uma etapa. No sistema, a programação (retirada, abate, caminhões, distância) são campos do compromisso (ADR 0008), com um código só (`CM-…`); a compra (`CP-…`) só nasce na aprovação do acerto.

**A dúvida:** os três números são conceitos que o usuário usa de verdade (como no SisAtak, `350-CCA-1-61126`), ou o do compromisso basta?

**Implementado:** um código por compromisso; o `CP-` aparece no acerto aprovado.

**Custo de mudar:** baixo a médio. Número de programação é um campo gerado; entidade separada é decisão maior e só vale se a programação mudar de dono ou de data várias vezes.

---

## #33 — 🟡 Granularidade dos títulos do ciclo: por item, por viagem ou por transportador *(Fase 4/5)*

**Onde:** o acerto aprovado gera uma compra por item e, por compra, até 4 títulos (animais, frete, comissão, impostos). O frete é **rateado por cabeça** entre os itens; com mais de um transportador, o título fica **sem favorecido**; o título de impostos nunca tem favorecido; há **um** vencimento por título; `Invoice.document` nasce vazio. O documento funcional (seção 10) fala em título por favorecido, com documento, e em "frete lançado na viagem reaproveitado no financeiro".

**A dúvida:** o frete deve gerar **um título por transportador** (somando as viagens dele)? O imposto vai a quem — Funrural ao governo, GTA à agência? O vencimento do frete e da comissão é o mesmo dos animais? Parcelamento ([#16](#16--prazo-e-parcelamento-do-pagamento-fase-4))?

**Por que importa:** é o que o financeiro paga de fato. Hoje ele completa o favorecido à mão.

**Implementado:** título por item e componente; favorecido do frete só se houver um transportador.

**Custo de mudar:** médio. Mexe em `settlement.py::ratear_extras` e na geração de títulos do acerto; a chave de idempotência ganha o favorecido.

---

## #34 — 🟢 ADF, motorista e veículo *(Fase 5)*

**Onde:** a viagem tem `driver_name` e `vehicle_plate` como texto livre; o papel `MOTORISTA` existe no cadastro e nada o usa; "ADF/documentação" (seção 4.2) não tem campo. A aba `ADF E COMPRAS` da planilha tem status PAGO/PENDENTE e viagem CONCLUÍDA/PENDENTE, toda zerada.

**A dúvida:** o que é o ADF e o que se faz com ele — é só um número a anotar, ou um documento a anexar? Motorista e veículo se repetem entre viagens a ponto de merecerem cadastro?

**Implementado:** texto livre e `notes`.

**Custo de mudar:** baixo. Cadastro de veículo e motorista são duas tabelas pequenas; ADF começa como campo de texto e vira anexo se for preciso (anexo servido por view autenticada).

---

## #35 — 🟡 Tabela de preço, faixa por peso e condição de pagamento como cadastro *(Fase 5)*

**Onde:** seção 2.1 do documento (Comercial): tabelas de preço, faixas de preço, **critérios** das faixas, condições de pagamento e prazos, com vigência. No sistema, o preço das faixas 1 a 5 é digitado em cada item do compromisso; a faixa não tem intervalo de peso; a condição de pagamento é só `payment_days`.

**A dúvida:** o preço por faixa vem de uma tabela que se repete entre compromissos, ou é negociado caso a caso? A faixa depende do peso da carcaça ([#20](#20--como-se-escolhe-a-faixa-de-preço-de-cada-linha-do-romaneio-fase-5))? Existem condições de pagamento padronizadas (como `CA01`, `CA04` do legado)?

**Por que importa:** com cadastro, o compromisso nasce com os preços preenchidos. Sem cadastro, cada um digita cinco valores.

**Implementado:** digitação por item.

**Custo de mudar:** médio. Tabela de preço com vigência e faixa por peso é cadastro novo em `apps/commercial`; preencher o compromisso a partir dela é pequeno.

---

## #36 — 🟢 Centro de custo da aquisição: frete separado e análises por comprador, produtor e operação *(Fase 5)*

**Onde:** seção 11 do documento. Confirmar a compra lança **animais e frete no mesmo centro** (`DESPESA GADO`), comissão em `COMISSÃO` e tributos num valor só em `IMPOSTO E TAXAS` (`purchases/services.py`). `CostEntry` não tem eixo de comprador, produtor, operação ou unidade.

**A dúvida:** frete deve ter centro próprio? Quais análises por comprador, produtor e operação o produtor usa de fato — custo por cabeça por produtor? Por comprador, faz sentido sendo o comprador o comissionado?

**Implementado:** os centros fixos da Fase 2. A origem da compra (`source_purchase`) permite agregar por produtor sem campo novo.

**Custo de mudar:** baixo. Trocar o centro do frete é uma constante; as análises por produtor saem de `source_purchase__seller`.

---

## #37 — 🟢 O que é "custo total" e "custo por cabeça" no painel *(Fase 5)*

**Onde:** o cartão da safra (`dashboards/selectors.py`) soma só os custos **avulsos** (`source_purchase__isnull=True`) e divide o custo por cabeças do rebanho **atual**. O documento (12.1) pede "custo total, custo por cabeça, kg e @" junto com valor comprado, frete e comissão.

**A dúvida:** "custo total" inclui a aquisição dos animais? "Custo por cabeça" é custo de aquisição por cabeça comprada, ou custo da safra por cabeça em estoque? Os dois são úteis e diferentes — qual o painel mostra?

**Por que importa:** é o número que o produtor compara com a planilha e com o consultor ([#14](#14--margem-por--qual-denominador-e-o-que-fazer-com-lote-aberto-fase-3)).

**Implementado:** o painel atual, sem mudança.

**Custo de mudar:** baixo. Um serviço novo de indicadores por safra; o painel passa a consumi-lo.

---

## #38 — 🟢 Gestão a pasto: o que a operação usa de verdade *(Fase 6)*

**Onde:** seção 9 do documento e abas da `REPORTAGEM IVAN`: reprodução (estação de monta, prenhez, desmama), infraestrutura (curral, cocho, bebedouro), equipe, lotação em UA/ha, alocação de lote em pasto, **causa** da morte (onça, picada de cobra, acidente), chuva. O sistema tem `Paddock` (área e capacidade em UA, sem consumidor), `NASCIMENTO` como entrada simples e `MORTE` com motivo em texto livre.

**A dúvida:** a operação faz **cria** ou só recria e engorda (a planilha real só compra bezerro)? Quem alimentaria infraestrutura, equipe e chuva — e quem leria? A causa da morte vira lista fechada?

**Implementado:** nada além do que existe.

**Custo de mudar:** varia. Causa da morte como lista é baixo (campo no movimento); lotação por pasto é médio (lote ou animal em pasto); reprodução e infraestrutura são módulos novos.

---

## #39 — 🟢 Indicadores do consultor: TIR, curva ABC, inventário valorizado, eficiência biológica *(Fase 6)*

**Onde:** abas `TIR`, `PERFIL ABC PECUÁRIA`, `INVENTARIO`, `ANÁLISE PECUÁRIA` e `PLACAR` da `REPORTAGEM IVAN`: rendimento do ganho, GMD de carcaça, dias para 1 @, desfrute, custeio e desembolso por @ e por cabeça/mês, efeito de mercado no estoque.

**A dúvida:** quais o produtor quer ver no sistema, e a partir de quando? Há dado para eles — consumo e dieta, por exemplo, não são registrados.

**Implementado:** GMD, @ produzida, rendimento de carcaça e resultado por lote. Nada de TIR, ABC ou inventário valorizado.

**Custo de mudar:** o dado já está no sistema para TIR, ABC e inventário (custos, compras, vendas, estoque); só o cálculo falta, e com duas safras de histórico. Eficiência biológica pede um dado novo (consumo).

---

## #40 — 🟢 Mudança de lote e mudança de fazenda como tipos próprios *(Fase 1)*

**Onde:** a lista de movimentações do documento (seção 9) separa "mudança de lote" e "mudança de fazenda" de "transferência". No sistema as duas são `TRANSFERENCIA`, distinguidas pelos campos de origem e destino.

**A dúvida:** o produtor precisa **filtrar ou relatar** as duas separadamente? Ou transferência entre fazendas e entre lotes se lê bem pelos campos?

**Implementado:** um tipo só, com 2 linhas no razão (regra 1).

**Custo de mudar:** baixo, se for só rótulo e filtro derivado dos campos. Tipo novo no banco só se a regra de geração de linhas diferir.

---

## #41 — 🟢 Quem aprova os pedidos de acesso e quem é avisado *(Fase 0)*

**Onde:** tela pública de solicitação de acesso e aba *Solicitações de acesso* em Usuários e acessos ([regra 09](09-usuarios-e-solicitacao-de-acesso.md)).

**A dúvida:** só o `ADMIN` aprova, ou o `GESTOR` também? E o aviso por e-mail vai para todos os administradores, ou para um endereço fixo (o do dono, que pode nem usar o sistema)?

**Por que importa:** aprovar dá acesso a dado de compra, custo e financeiro. Quem aprova define quem pode abrir essa porta.

**Implementado:** só `ADMIN` (e superusuário) aprova e recusa. O aviso vai para todo administrador ativo com e-mail; `ACCESS_REQUEST_NOTIFY_EMAILS` no `.env` acrescenta endereços sem criar usuário.

**Custo de mudar:** baixo. Papéis que aprovam: `pode_gerenciar_usuarios` em `apps/accounts/permissions.py`. Destinatários: `destinatarios_dos_administradores` em `emails.py`.

---

## #42 — 🟢 O que o pedido de acesso deve conter e como confirmar quem pede *(Fase 0)*

**A dúvida:** basta nome, e-mail, telefone e uma frase de justificativa? Falta algo (fazenda, função, quem indicou)? Convém limitar a domínio de e-mail da empresa, ou o administrador decide caso a caso?

**Por que importa:** o pedido é aberto ao público. Pedir pouco deixa o administrador decidindo no escuro; pedir muito afasta quem tem sinal ruim no campo.

**Implementado:** nome completo, e-mail, telefone opcional e texto livre (10 a 1.000 caracteres). O e-mail **não é confirmado antes**: o link para definir a senha só vai ao endereço informado, então só o dono dele entra — e o aviso ao administrador diz isso. Limites: 5 pedidos/hora por IP, 20 avisos por e-mail/hora, um pedido pendente por e-mail, campo-isca contra robô. Nada de CAPTCHA.

**Custo de mudar:** baixo. Campos novos: `AccessRequest` + `SolicitacaoAcessoForm`. Restrição de domínio: um `clean_email`. CAPTCHA só se o abuso aparecer.

---

## #43 — 🟢 Exclusão de usuário e senha temporária *(Fase 0)*

**A dúvida:** (a) excluir usuário é só lógico — correto? Restaurar volta **desativado**; o e-mail do excluído fica livre para outra conta (restaurar falha se ele já foi reutilizado). (b) Quem não usa e-mail (pessoal de campo) entra com **senha temporária** definida pelo administrador: aceitável, ou todos precisam de e-mail?

**Por que importa:** (a) a auditoria e os lançamentos apontam para o usuário; apagar de verdade quebraria o histórico. (b) Senha repassada por fora é o elo mais fraco do acesso.

**Implementado:** exclusão lógica (`deleted_at`), com motivo e análise do que acontece. Senha temporária obriga a troca no primeiro acesso (`must_change_password`), derruba as sessões abertas e nunca aparece em auditoria ou log.

**Custo de mudar:** baixo. Exigir e-mail: uma validação no formulário. Prazo para a senha temporária expirar: um campo e uma checagem no middleware.

---

## #44 — 🟢 Quem exporta e o que cada papel leva *(Fase 6)*

**Onde:** tela *Exportações* ([regra 10](10-exportacao-de-dados.md)).

**A dúvida:** quem pode levar dado do sistema para fora? Hoje: `ADMIN`, `GESTOR`, `ESCRITORIO` e `FINANCEIRO`. `CAMPO` e `CONSULTA` não. E, dentro disso, cada conjunto segue a regra da tela correspondente (financeiro, ciclo de compra, conta bancária, usuários e auditoria). O `CONSULTA` já exporta **relatórios** em CSV/Excel (F3-11); a exportação de **dados** em massa é mais sensível, por isso ficou mais restrita.

**Por que importa:** exportar é o jeito mais fácil de vazar a base inteira — compra, custo, parceiros com CPF/CNPJ, contas bancárias. Um papel de consulta com a tela aberta passa a poder levar tudo, de uma vez, em Excel.

**Implementado:** só os quatro papéis acima abrem a tela. O escopo por fazenda vale sempre. Contas bancárias só para quem já vê dado bancário; usuários e auditoria só para o `ADMIN` (a auditoria acompanha `AUDIT_CONSOLE_INCLUDE_GESTOR`). Só quem pediu baixa o arquivo — nem o `ADMIN` baixa o de outro (404). Cada pedido e cada download vão para a auditoria. Perguntar ao produtor se o `GESTOR` deve ver a trilha de auditoria exportada e se algum papel de campo precisa exportar o próprio escopo.

**Custo de mudar:** baixo. Papéis da tela: `PAPEIS_QUE_EXPORTAM` em `apps/exports/permissions.py`. Papéis de um conjunto: o campo `permitido` dele em `apps/exports/catalog.py`.

---

## #45 — 🟢 Por quanto tempo o arquivo fica e o que a exportação não é *(Fase 6)*

**Onde:** tela *Exportações* e `manutencao` (Celery beat).

**A dúvida:** (a) o arquivo exportado fica disponível por **7 dias** e depois é apagado do servidor — é o prazo certo? (b) A exportação **não** é um instantâneo atômico do banco: os conjuntos são lidos um depois do outro. Para quem sai do sistema, isso basta, ou é preciso uma exportação "congelada" num instante só? (c) O PDF mostra só as colunas principais e vai até 20.000 linhas por conjunto: aceitável?

**Por que importa:** (a) o arquivo é dado do negócio parado em disco, sem a proteção de papel e escopo do sistema; quanto mais fica, maior a janela de vazamento. (b) Quem exporta "tudo" para guardar de vez espera consistência: um lançamento feito durante a leitura poderia aparecer num conjunto e faltar em outro. (c) PDF de tabela larga é ilegível; o dado completo está nos outros formatos.

**Implementado:** (a) 7 dias (`EXPORT_RETENTION_DAYS`); o dono pode apagar antes; o **pedido** e a auditoria nunca saem. (b) Sem snapshot; o `LEIA-ME` do pacote e a ajuda da tela dizem isso, e apontam o `deploy/backup.sh` para a cópia exata. (c) Como descrito.

**Custo de mudar:** (a) uma variável de ambiente. (b) médio: ler tudo numa transação `REPEATABLE READ` por uma conexão separada, com o custo de segurar o snapshot por minutos. (c) baixo: lista de colunas por conjunto (`Conjunto.pdf`) e `PdfEscritor.LIMITE_DE_LINHAS`.

---

## #46 — 🟢 Troca de e-mail pelo próprio usuário *(Fase 0)*

**Onde:** página *Conta* ([regra 09](09-usuarios-e-solicitacao-de-acesso.md#conta-o-próprio-usuário)).

**A dúvida:** o usuário deve poder trocar o próprio e-mail? E, se puder, como confirmar que o endereço novo é dele?

**Por que importa:** o e-mail é o canal de recuperação de senha. Trocá-lo sem confirmação por link permite a quem pegou uma sessão aberta redirecionar a recuperação para si e tomar a conta. Com confirmação, é seguro, mas custa um fluxo novo (link, validade, e-mail antigo avisado).

**Implementado:** somente leitura na Conta. Quem quer trocar pede ao administrador, que edita com motivo e auditoria.

**Custo de mudar:** médio. Campo `email` no `ContaForm`, serviço que grava um endereço *pendente*, e-mail com link para o endereço novo e aviso ao antigo; `CAMPOS_DA_PROPRIA_CONTA` fica como está (o e-mail só muda na confirmação).

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

## Como usar este documento

1. **Antes da Fase 1:** resolver #5 (bloqueia a carga) e #2. Confirmar #1.
2. **Antes da Fase 2:** resolver #3 e #6. *(Fase 2 construída com os padrões reversíveis acima; resolver antes da carga real, junto com #2, #5, #10 e #11.)*
3. **Antes da Fase 3:** resolver #7. *(Fase 3 construída com os padrões reversíveis acima; #12 a #15 nasceram dela. Resolver #12 e #5 antes de confiar no rendimento histórico.)*
4. **Antes da Fase 5:** resolver #4 e #8. *(Fase 5 construída antecipadamente, sem demanda confirmada, com os padrões reversíveis acima; #20 a #26 nasceram dela. **Resolver #21 com o contador antes de usar o acerto de verdade**, e #24 antes de o campo depender do saldo.)*
5. **Antes de gerar contrato de verdade:** responder #27 (dado bancário no PDF).
6. **Antes de continuar o alinhamento ao documento funcional** ([matriz](../fluxos/04-alinhamento-ao-doc-funcional.md)): as que travam a Onda 2 são **#24** (entrada do gado no recebimento), **#28** (aprovação em duas etapas), **#29** (o que avança a etapa depois do acerto), **#30** (quem é quem na negociação) e **#31** (programação antes do acerto). **#33** a **#36** decidem a Onda 3; **#37** a Onda 4. **#38** a **#40** são da Fase 6 e podem esperar.
7. **Antes de usar o financeiro de verdade:** responder #16 (prazo/parcelas), #17 (quem aprova, quem paga, a quem vai o frete) e #18 (o que do histórico está em aberto). *(Fase 4 construída com os padrões reversíveis acima.)*

8. **Usuários e acessos:** #41 a #43 são de política (quem aprova, o que o pedido contém, exclusão e senha temporária); funcionam com os padrões reversíveis e não bloqueiam nada.
9. **Exportação de dados:** #44 e #45 são de política (quem exporta, por quanto tempo o arquivo fica); funcionam com os padrões reversíveis e não bloqueiam nada. Responder #44 **antes** de liberar a tela a usuários além dos administradores.

10. **Mais de uma empresa:** #47 — a barra do topo não troca de empresa e as fazendas não são filtradas por ela. Hoje só a primeira empresa é operável; responder antes de cadastrar dado real na segunda.

#9 é de permissão, não de modelagem: pode ser ajustada a qualquer momento.

Resolvida uma pendência: registrar a resposta **aqui mesmo**, com data e quem respondeu, marcar ✅, e só então mexer no código. A pergunta e a resposta ficam no documento — apagar a pergunta é perder o motivo da regra.
