# Compra de gado

> Esta é a compra **do produtor** — comprar bezerro para engordar. Não confundir com o ciclo de compra do frigorífico, que está em [fluxos/03](../fluxos/03-fluxo-compra-frigorifico.md) e entra só na Fase 5.

## O que existe hoje

A aba `COMPRA DE GADO` tem 13 compras na safra 25/26: **954 cabeças, R$ 2.457.752,15**, todas de bezerros para São Francisco.

```
DATA | QUANT. | NOVILHAS/BOIS | VALOR TOTAL | MÉDIA/CAB | FAZENDA | MÊS |
PARCERIA | ANO | SAFRA | FRETE | COMISSÃO | OBSERVAÇÕES | IMPOSTOS
```

Distribuição por mês: julho 96 · agosto 40 · outubro 54 · novembro 190 · dezembro 174 · março 6 · abril 394.

Problemas: `MÉDIA/CAB` é `#DIV/0!` em todas as linhas vazias; `FRETE`, `COMISSÃO` e `IMPOSTOS` estão como `-` (nunca preenchidos); não há vínculo com lote; e a entrada no rebanho é lançada **de novo, à mão**, na aba da fazenda.

Esse último ponto é o mais caro: a compra de 133 bezerros de setembro aparece na aba `COMPRA DE GADO` **e** na aba `SÃO FRANCISCO` como movimentação. Dois lançamentos para um fato.

## Estados

Máquina curta e explícita. Ver [ADR 0001](../arquitetura/adr/0001-monolito-modular-django.md) sobre não construir motor de workflow.

```
RASCUNHO ──confirmar──> CONFIRMADA ──excluir──> EXCLUÍDA
    │                        ↑  │                   │
    └──excluir──> EXCLUÍDA   └──editar              └──restaurar
```

| Estado | O que significa |
|---|---|
| `RASCUNHO` | Digitada, ainda não afeta nada |
| `CONFIRMADA` | Gerou entrada no rebanho e custos |
| `EXCLUÍDA` | Efeitos desfeitos; registro preservado no banco e na auditoria |

Compra confirmada **é editável e é excluível**, com motivo obrigatório. Editar desfaz os efeitos da versão anterior e aplica os da nova, na mesma transação. Excluir desfaz tudo.

Antes de qualquer das duas, o sistema mostra a **análise de impacto**. Regra completa em [06-edicao-exclusao-e-auditoria](06-edicao-exclusao-e-auditoria.md).

> A Fase 5 acrescenta os estados do ciclo de frigorífico (compromisso, programação, embarque, recebimento, acerto) **entre** `RASCUNHO` e `CONFIRMADA`, sem quebrar o que já existe.

## O que a confirmação faz

Tudo em uma transação. Ou acontece inteiro, ou nada acontece.

```python
@transaction.atomic
def confirmar_compra(compra, *, usuario):
    # 1. Trava a compra — dois cliques no botão não podem confirmar duas vezes
    compra = Purchase.objects.select_for_update().get(pk=compra.pk)
    if compra.status != Purchase.Status.RASCUNHO:
        raise BusinessError("Esta compra já foi confirmada.")

    # 2. Lote: novo ou existente, escolha do usuário
    lote = compra.lot or criar_lote(compra)

    # 3. Entrada no rebanho — 1 linha positiva no razão
    movimento = registrar_movimento(
        tipo=MovementType.COMPRA,
        data=compra.date,
        fazenda_destino=compra.destination_farm,
        lote_destino=lote,
        categoria_destino=compra.category,
        quantidade=compra.head_count,
        peso_total_kg=compra.total_weight_kg,
        documento_origem=compra,
        usuario=usuario,
    )

    # 4. Custos — um lançamento por valor preenchido
    gerar_custos_da_compra(compra, lote=lote, usuario=usuario)

    # 5. Estado, auditoria e linha do tempo
    compra.status = Purchase.Status.CONFIRMADA
    compra.save(update_fields=["status"])
    registrar_evento(compra, "Compra confirmada", usuario=usuario)
    return movimento
```

O `select_for_update` na etapa 1 é o que impede duplicidade por clique duplo ou por duas abas do navegador — cenário real quando a conexão da fazenda está lenta.

> **Fase 4 — confirmar também gera os títulos a pagar** (um por valor preenchido; só o dos animais tem favorecido, o vendedor), idempotente por `(compra, componente)`. O vencimento é a data da compra + `payment_days` (campo opcional novo, que a spec chamava `payment_terms`). Corrigir a compra atualiza os títulos; excluir cancela os que ainda não foram pagos; **baixa existente bloqueia** editar e excluir. A importação do histórico não gera título. Ver [07-financeiro](07-financeiro.md).

## Custos gerados

| Campo da compra | Centro de custo | Gerado quando |
|---|---|---|
| `animal_value` | DESPESA GADO | sempre |
| `freight_value` | DESPESA GADO | se > 0 |
| `commission_value` | COMISSÃO | se > 0 |
| `tax_value` | IMPOSTO E TAXAS | se > 0 |

Todos com `lot` preenchido — são custo **direto**, não entram em rateio. Todos com `source_purchase` apontando para a compra, e por isso não editáveis fora dela.

```
custo_aquisicao = animal_value + freight_value + commission_value + tax_value
```

Calculado por `PurchaseCostService`. Nunca gravado.

## Derivados

| Indicador | Fórmula | Hoje na planilha |
|---|---|---|
| Média por cabeça | `valor_total ÷ cabeças` | coluna `MÉDIA/CAB`, com `#DIV/0!` |
| Peso médio | `peso_total ÷ cabeças` | ausente |
| Custo por @ | `custo_aquisicao ÷ (peso_total ÷ 15)` | ausente |
| Custo por kg | `custo_aquisicao ÷ peso_total` | ausente |

Sem cabeças informadas, todos devolvem `None` → "—" na tela.

Conferência com a planilha: compra de dezembro, 105 cabeças, R$ 260.172,15 → R$ 2.477,83/cabeça. Bate.

## Peso na compra

`total_weight_kg` é **opcional**, porque nem toda compra é pesada na entrada. Consequências:

- Sem peso: custo/@ e custo/kg ficam indisponíveis; GMD do lote só começa a contar na primeira pesagem
- Com peso: o sistema sugere criar uma `Weighing` de motivo `COMPRA` junto, para que o dado entre no histórico do lote

Das 954 cabeças compradas na safra, nenhuma tem peso na aba de compras — mas há pesagens com motivo `COMPRA` na aba `PESAGENS E CONFERENCIA`. São o mesmo fato registrado em dois lugares sem ligação. O sistema junta os dois.

## Validações

1. `head_count > 0`
2. `animal_value > 0`
3. `date` não pode ser futura
4. `date` dentro de uma safra aberta (fora disso exige permissão)
5. Fazenda de destino dentro do escopo do usuário
6. Categoria ativa
7. Vendedor com papel `FORNECEDOR` ou `PRODUTOR`
8. Confirmar exige permissão `purchases.confirm_purchase`

## Tela

Formulário curto. A compra de bezerro é uma operação simples e não deve parecer complexa.

```
NOVA COMPRA                                    Safra 2025/2026

Data ............ [ 15/04/2026 ]
Vendedor ........ [ busca por nome/CPF        ▾ ]
Fazenda destino . [ São Francisco             ▾ ]
Categoria ....... [ Machos Desm. até 12m      ▾ ]
Cabeças ......... [ 126 ]      Peso total (kg) [ opcional ]

Valor dos animais [ 388.080,00 ]
Frete ........... [        0,00 ]
Comissão ........ [        0,00 ]
Impostos ........ [        0,00 ]
                   ───────────────
Custo total ...... R$ 388.080,00        ← calculado ao digitar
Média por cabeça . R$   3.080,00        ← calculado ao digitar

Lote ............ ( ) Criar novo: LT-SFR-014
                  ( ) Adicionar a lote existente [ ▾ ]

               [ Salvar rascunho ]  [ Confirmar compra ]
```

Confirmar mostra o impacto antes de executar:

> **Confirmar esta compra vai:**
> · dar entrada de 126 cabeças em São Francisco, no lote LT-SFR-014
> · lançar R$ 388.080,00 em DESPESA GADO
>
> Depois de confirmada, ela continua editável — a correção desfaz e reaplica os efeitos, com motivo registrado.

## Pendências

- **#3** — `PARCERIA`, sempre `-`. Existe compra em parceria? Muda quem é dono do animal e de quanto do custo.
- **#8** — O produtor compra por faixa de preço, como o contrato do frigorífico (Faixa 1 a 5)? Na planilha o preço é um valor único por cabeça.
