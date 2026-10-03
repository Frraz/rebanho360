# Venda e abate

## O que existe hoje

A aba `VENDAS` tem 3 operações na safra 25/26, todas do tipo `ABATE`, todas de `MACHOS 25 - 36` de São Francisco II para a **COPERFRIGU**, na forma `PASTO`:

| Data | Cabeças | Peso vivo | Carcaça | Rend. | Valor | R$/@ |
|---|---|---|---|---|---|---|
| ago/2025 | 84 | 43.540 kg | 22.350,40 kg | 51,33% | R$ 401.502,68 | 269,46 |
| mar/2026 | 189 | 106.680 kg | 60.225,00 kg | 56,45% | R$ 1.302.000,00 | 324,28 |
| abr/2026 | 81 | 45.000 kg | 25.555,00 kg | 56,79% | R$ 595.083,55 | 349,30 |

Colunas da planilha:
```
DATA | TIPO DE VENDA | CATEGORIA | ANIMAIS | PESO TOTAL | PESO MÉDIO | CARCAÇA TOTAL |
CARCAÇA MÉDIA | RENDIMENTO % | VALOR TOTAL | VALOR CABEÇA | VALOR POR @ | COMPRADOR |
MÊS | ANO | FORMA | SOMA RENDIMENTO | FAZENDA | STATUS | PARCERIA | SAFRA
```

Sete dessas colunas são derivadas e estão gravadas como valor: peso médio, carcaça média, rendimento %, valor cabeça, valor por @, mês, ano. No sistema, nenhuma existe como campo.

> **Divergência encontrada:** na linha de agosto, `RENDIMENTO %` = 0,5133 e `SOMA RENDIMENTO` = 43,12. Não são a mesma grandeza e não está documentado o que a segunda mede. Pendência #7.

## Modelo

`Sale` — usada tanto para abate quanto para venda de animal vivo. A diferença está no campo `type`, não em duas tabelas.

| Campo | Obrigatório | Nota |
|---|---|---|
| `code` | auto | `VD-2025/26-0003` |
| `date` | sim | |
| `type` | sim | `ABATE` ou `VENDA` |
| `buyer` | sim | `Partner` com papel `FRIGORIFICO` ou `COMPRADOR` |
| `farm`, `lot`, `category` | sim | De onde saem os animais |
| `head_count` | sim | |
| `total_weight_kg` | sim | Peso vivo de saída |
| `carcass_weight_kg` | só em `ABATE` | Vem do frigorífico |
| `total_value` | sim | |
| `sale_form` | sim | `PASTO` ou `CONFINAMENTO` |
| `season`, `partnership`, `notes` | | |
| `status` | | `RASCUNHO` → `CONFIRMADA` → `EXCLUÍDA` (editável e restaurável) |

## Derivados — `CarcassService`

Nenhum é campo. Todos calculados, todos testados contra os números reais acima.

```
peso_medio_vivo   = total_weight_kg   ÷ head_count
carcaca_media     = carcass_weight_kg ÷ head_count
rendimento        = carcass_weight_kg ÷ total_weight_kg
arrobas_carcaca   = carcass_weight_kg ÷ 15
valor_por_cabeca  = total_value       ÷ head_count
valor_por_arroba  = total_value       ÷ arrobas_carcaca
```

Verificação com o abate de agosto/2025 — é o teste que trava o serviço:

```
43.540 ÷ 84                = 518,33 kg        ✓ planilha: 518,33
22.350,40 ÷ 84             = 266,08 kg        ✓ planilha: 266,08
22.350,40 ÷ 43.540         = 51,33 %          ✓ planilha: 51,33
22.350,40 ÷ 15             = 1.490,03 @
401.502,68 ÷ 84            = 4.779,79         ✓ planilha: 4.779,79
401.502,68 ÷ 1.490,03      = 269,46           ✓ planilha: 269,46
```

Em venda de animal vivo, sem carcaça, os indicadores de carcaça devolvem `None` e a tela mostra "—". O preço passa a ser por cabeça ou por kg vivo.

## Confirmação

Mesma disciplina da compra: transacional, travada, com saída no rebanho gerada automaticamente.

```python
@transaction.atomic
def confirmar_venda(venda, *, usuario):
    venda = Sale.objects.select_for_update().get(pk=venda.pk)
    if venda.status != Sale.Status.RASCUNHO:
        raise BusinessError("Esta venda já foi confirmada.")

    # Saldo suficiente? Verificado DENTRO da transação.
    saldo = HerdBalanceService.saldo(
        fazenda=venda.farm, lote=venda.lot, categoria=venda.category
    )
    if saldo["cabecas"] < venda.head_count:
        raise BusinessError(
            f"Saldo insuficiente: há {saldo['cabecas']} cabeças de "
            f"{venda.category} no lote {venda.lot.code}, "
            f"foram informadas {venda.head_count}."
        )

    tipo = MovementType.ABATE if venda.type == Sale.Type.ABATE else MovementType.VENDA
    registrar_movimento(
        tipo=tipo, data=venda.date,
        fazenda_origem=venda.farm, lote_origem=venda.lot,
        categoria_origem=venda.category,
        quantidade=venda.head_count, peso_total_kg=venda.total_weight_kg,
        parceiro=venda.buyer, documento_origem=venda, usuario=usuario,
    )

    venda.status = Sale.Status.CONFIRMADA
    venda.save(update_fields=["status"])
    registrar_evento(venda, "Venda confirmada", usuario=usuario)
```

A verificação de saldo **dentro** da transação, com a posição travada, é o que impede duas vendas simultâneas de derrubarem o saldo abaixo de zero. Fora da transação, as duas passariam na validação.

## Pesagem de saída

Confirmar uma venda sugere criar uma `Weighing` de motivo `ABATE` ou `VENDA` com o peso de saída. É o que fecha o cálculo de GMD e de @ produzida do lote.

Sem essa pesagem, o desempenho do lote fica incompleto — e o sistema avisa na tela do lote em vez de mostrar número errado.

## Resultado do lote

Confirmar a venda é o que permite fechar a conta:

```
resultado = receita − custo_aquisicao − custos_diretos − custos_rateados
margem/@  = (valor recebido por @) − (custo por @)
```

Com o lote a saldo zero, ele é encerrado (`status = ENCERRADO`, `exit_date` preenchida) e o resultado fica congelado para consulta histórica.

## Validações

1. `head_count > 0`, `total_weight_kg > 0`, `total_value > 0`
2. Saldo suficiente na posição, verificado sob trava
3. `carcass_weight_kg < total_weight_kg` — rendimento acima de 100% é erro de digitação
4. Rendimento fora de 40%–65% gera **alerta**, não bloqueio: valor atípico deve ser conferido por gente, não recusado pela máquina
5. Data não futura, safra aberta
6. Fazenda dentro do escopo do usuário
7. Confirmar exige `sales.confirm_sale`

> **Fase 4 — confirmar a venda gera o título a receber** (`VENDA`, do comprador, valor total), vencendo na data da venda + `payment_days` (opcional). Recebimento baixado bloqueia editar e excluir a venda — e excluir a compra do lote. Ver [07-financeiro](07-financeiro.md).

## Decisões de implementação da Fase 3

O que a spec acima não cobria e a planilha real obrigou a decidir (todas reversíveis; pendências #12 a #14 em [99-pendencias](99-pendencias.md)):

- **Abate confirma sem carcaça.** "Carcaça obrigatória só em `ABATE`" vale como *só existe em abate* (constraint no banco: venda de animal vivo não aceita carcaça). O romaneio chega depois da saída; exigir a carcaça para confirmar deixaria no saldo animais que já foram embora. Abate sem carcaça é pendência no painel, e os indicadores de carcaça mostram "—".
- **Carcaça < peso vivo**, também constraint no banco (rendimento acima de 100% é erro de digitação).
- **Confirmar encerra o lote** quando o saldo zera (`ENCERRADO`, `exit_date` = data da venda); **excluir ou corrigir reabre**. O lote nunca é encerrado "à mão".
- **A venda pode adotar uma saída que já está no razão.** A aba da fazenda registra o abate como movimento e a aba `VENDAS` o registra como venda: são a *mesma* saída. `vincular_a_saida_existente` faz a venda ser o documento de origem do movimento, **sem debitar de novo** e sem mexer na data nem no peso dele — a diferença é aviso (#12). Só vale para venda em rascunho e movimento confirmado, de saída, de mesma fazenda, lote, categoria e quantidade, que ninguém reivindicou.
- **Peso na venda × peso no razão:** a venda guarda o peso da aba `VENDAS` (é o documento comercial); o movimento mantém o dele; a tela da venda avisa quando diferem. Corrigir a venda depois sincroniza o movimento com ela.
- **Nada depende de uma venda além do pagamento (Fase 4).** Devolver os animais ao lote só *acrescenta* saldo na data original: não há saldo posterior que possa ficar negativo. O "lote já usado em algo posterior" da F3-04 é pego na **edição** — reaplicar a saída confere o saldo sob trava e recusa com a mensagem específica. O gancho para "pagamento baixado" está em `Sale.bloqueios()` — **ligado na Fase 4**: recebimento baixado do título da venda bloqueia editar e excluir ([07](07-financeiro.md)).
- **Escopo e papéis:** lançar e confirmar = `ADMIN`, `GESTOR`, `ESCRITORIO`; editar confirmada = os mesmos; excluir confirmada = `GESTOR`, `ADMIN` ([#9](99-pendencias.md)). `CAMPO` não lança venda.

## Pendências

- **#5** — As vendas saem de "SÃO FRANCISCO II", as compras entram em "SÃO FRANCISCO". São duas fazendas ou fazenda e retiro? Sem isso, o resultado do lote atravessa duas unidades sem explicação.
- **#7** — `RENDIMENTO %` versus `SOMA RENDIMENTO`: o que a segunda mede? O rendimento é informado pelo frigorífico ou calculado?
- **#3** — `PARCERIA`, sempre `-`. Se houver parceria, o resultado precisa ser dividido.
