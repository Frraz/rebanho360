# ADR 0008 — Ciclo de compra por composição: o núcleo não muda

**Data:** 2026-10-02 · **Status:** Aceita

## Problema

A Fase 5 acrescenta, entre "negociei" e "o gado entrou no rebanho", o ciclo do SisAtak: compromisso, programação, viagem, recebimento, classificação de carcaça e acerto. O roadmap promete que isso se encaixa **sem alterar nenhuma tabela do núcleo** e sem quebrar `RASCUNHO → CONFIRMADA`.

Ao desenhar, três pontos do texto original não fecham com o código que existe:

1. O roadmap diz "tudo pendurado em `Purchase`". Mas `Purchase` tem **uma categoria**, e um contrato do legado mistura "Vaca viva" e "Boi marruco".
2. Os estados do legado são 16. O projeto proíbe motor de workflow e estado digitado à mão.
3. A "trava de fechamento" do acerto, no legado, é um estado. Aqui ela deve ser **bloqueio na análise de impacto** (regras-negocio/06).

## Decisão

**1. O compromisso gera as compras; não é uma compra.** `Commitment` tem itens (`CommitmentItem`), cada item com uma categoria. Ao **aprovar o acerto**, cada item vira uma `Purchase` normal, confirmada pelo mesmo `confirmar_compra` de sempre — que dá a entrada no rebanho, lança os custos e gera os títulos. `CommitmentItem.purchase` é a única ligação. Nenhuma coluna de `Purchase`, `Lot`, `CostEntry`, `HerdMovement` ou `Invoice` foi acrescentada; `CONFIRMADA` passa a ser alcançada **depois** do acerto aprovado, como o roadmap pede.

> Desvio do texto do roadmap: a ligação é **item → compra**, e não compromisso → compra. É o que permite um contrato com duas categorias sem tocar em `Purchase`.

**2. A etapa do ciclo é derivada, nunca gravada** (regra 6). "Em negociação", "aprovado", "em viagem", "recebido", "em acerto", "acerto aprovado" saem de `etapa_do_compromisso()`, lendo o que existe: aprovação, viagens, recebimentos, acerto. Desfazer um recebimento faz a etapa recuar sozinha, sem transição para escrever e sem estado que possa ficar para trás.

**3. Cada peça do ciclo segue o ciclo padrão** (`ReversibleModel`): `Commitment`, `Trip`, `Receiving` e `Settlement` são editáveis, excluíveis e restauráveis, com motivo, impacto e auditoria. As linhas (itens, cargas, linhas do romaneio, linhas do acerto, notas fiscais) são `LineModel`: nunca saem do banco — recebem `removed_at` — e mudam sempre **pela operação do pai**, com um motivo só.

**4. Trava de fechamento = `bloqueios()`.** Com o acerto aprovado, tudo que alimenta o valor consolidado (itens, viagens, recebimentos, romaneio, linhas, comissão) recusa edição e diz o caminho: **reabrir o acerto**. A reabertura é formal — motivo obrigatório, quem e quando na auditoria — e desfaz os efeitos (as compras saem em cascata, com movimento, custos e títulos). Baixa de título já feita **continua bloqueando** a reabertura, com o link para o pagamento, como na Fase 4.

**5. Snapshot da comissão na aprovação do compromisso.** `Commission` copia a regra aplicada (tipo, base, valor, favorecido) e a guarda no compromisso. Mudar `CommissionRule` depois não toca a operação de janeiro.

**6. Programação é dado do compromisso, não entidade.** Data de retirada, data de abate, caminhões, distância e prazo médio são campos do `Commitment`. Uma entidade `Shipment` não teria ciclo de vida próprio — seria uma segunda tabela para o mesmo documento. O relatório "Programação de abate" lê o compromisso.

**7. Tributos só como valor digitado.** Sem alíquota, sem fórmula, sem base de cálculo no código — a confirmação com o contador não aconteceu ([#21](../../regras-negocio/99-pendencias.md)). `TaxType` é cadastro; cada valor é digitado no acerto.

## Alternativas descartadas

**`Commitment` com a `Purchase` dentro (1:1), estendendo a compra.** Era o texto do roadmap. Obriga `Purchase` a ter várias categorias — mexe no núcleo, na entrada de rebanho (que é por categoria) e no lote.

**Máquina de estados de 16 passos em um campo `stage`.** É o legado. Um campo gravado que pode discordar do que existe de fato (um recebimento excluído e a etapa continuando "recebido"), com 16 transições para testar. A derivação dá o mesmo rótulo sem o defeito.

**Estado `ACERTO_FECHADO` separado do bloqueio.** Duplica o que `bloqueios()` já faz para pagamento baixado e safra encerrada, e abre um segundo caminho de "exceção" ao "tudo é editável".

**Entrada no rebanho a cada recebimento.** O texto funcional diz que "o recebimento alimenta o rebanho". O roadmap diz que `CONFIRMADA` vem depois do acerto. As duas frases só convivem com um intermediário (compra provisória por viagem), que reintroduz a compra de uma categoria só e o rateio por viagem. Fica como a pendência [#24](../../regras-negocio/99-pendencias-resolvidas.md): construído como o roadmap manda, reversível.

**Tabela de alíquotas por tributo, com vigência.** Tecnicamente simples, e é exatamente o que o roadmap proíbe fazer sem o contador: regra tributária implementada por dedução.

## Consequências

**Boas:** o que já funciona não é tocado (compra direta, importadores, relatórios). O ciclo reaproveita 100% da mecânica de efeitos, impacto, bloqueio e auditoria. Nada gravado pode divergir do que existe.

**Ruins, e precisam de atenção:**

*Entre o recebimento e o acerto aprovado, o gado está na fazenda e não está no saldo.* É a pendência #24, e é o ponto que mais pode incomodar o campo. Mitigação: o painel mostra "recebido, aguardando acerto" com as cabeças.

*Uma compra nascida do acerto não se corrige direto.* Edição e exclusão diretas são recusadas com o caminho (a reabertura do acerto), como o movimento gerado por compra não se corrige direto.

*Rateio de frete, comissão e tributos entre itens* é regra inventada ([#22](../../regras-negocio/99-pendencias-resolvidas.md)): por cabeça recebida, isolada em uma função.
