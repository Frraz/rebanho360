# ADR 0004 — Saldo por lote agora, brinco individual depois

**Data:** 2026-09-30 · **Status:** Aceita

## Problema

A aba `PESAGENS E CONFERENCIA` tem centenas de pesagens individuais por brinco, em oito blocos paralelos de colunas `(data, brinco, peso, movimentação)`. Os brincos existem e são usados.

A v1 deve controlar animal por animal, ou saldo por lote e categoria?

## Decisão

**Saldo por lote e categoria na v1.** Sem entidade `Animal`.

Os dados de brinco **são importados e preservados** numa tabela `WeighingAnimal` com `(pesagem, brinco, peso_kg)` — texto puro, sem chave estrangeira para animal algum.

## Alternativas descartadas

**Entidade `Animal` desde o início.** Cada animal um registro, com histórico próprio de peso, lote, fazenda e categoria. É mais poderoso e é o que muitos sistemas de pecuária fazem. Duas razões para não fazer agora:

*Custo de construção.* Movimentação deixa de ser "150 cabeças" e passa a ser a seleção de 150 animais. Toda tela de lançamento muda de natureza. Transferência, evolução, abate — tudo vira operação em conjunto de indivíduos.

*Custo de operação, que é o decisivo.* A operação hoje lança "12 mortes em outubro", não "morreu o animal 1.632". Exigir brinco em todo lançamento significa exigir do campo uma disciplina que a operação ainda não tem — e o resultado provável é o sistema ser contornado, com o lançamento indo parar de volta no WhatsApp.

**Descartar os dados de brinco.** Seria perder dado real já coletado, e a coleta é a parte cara. Os brincos ficam guardados.

## Consequências

**Boas:** o sistema fica proporcional à operação. Lançamento de campo continua rápido no celular — que é o que determina se ele é usado. Os dados de brinco estão salvos para quando a entidade `Animal` existir.

**Ruins:** não há rastreabilidade individual na v1 — não se responde "onde está o animal 948". A pesagem por brinco entra como dado bruto, sem alimentar cálculo. GMD é por lote, não por animal, o que esconde variação dentro do lote.

## Caminho para a Fase 6

O modelo foi desenhado para receber `Animal` sem reescrita:

1. Criar `Animal` com `ear_tag`, `lot`, `category`, `birth_date`, `status`
2. Popular a partir dos `WeighingAnimal` já importados — os brincos históricos viram animais reais com histórico de peso
3. Acrescentar `HerdMovementAnimal` (movimento × animal), **opcional**: movimento pode continuar sendo por quantidade
4. Saldo continua saindo do razão — `HerdLedgerEntry` não muda

O ponto que torna isso possível é o do [ADR 0002](0002-rebanho-como-razao-de-movimentacoes.md): saldo derivado de eventos. Identificação individual vira um detalhamento do evento, não uma nova forma de contar.
