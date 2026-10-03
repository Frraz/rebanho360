# Vocabulário

**Código em inglês. Tela em português.** Este documento é a ponte.

A regra sobre o português: usar o nome que o produtor usa. Se ele diz "acerto", a tela diz "acerto" — não "liquidação financeira".

## Organização

| Tela (pt-BR) | Código (en) | Nota |
|---|---|---|
| Empresa | `Company` | |
| Unidade | `BusinessUnit` | Agrupa fazendas |
| Safra | `Season` | Julho a junho. Eixo de todo o negócio |
| Fazenda | `Farm` | |
| Pasto / Área | `Paddock` | |
| Retiro | `Paddock` | Sinônimo regional |

## Pessoas

| Tela | Código | Nota |
|---|---|---|
| Parceiro | `Partner` | Um cadastro, vários papéis |
| Produtor | `Partner` + papel `PRODUTOR` | Quem cria o gado |
| Pecuarista | `Partner` + papel `PECUARISTA` | Termo do frigorífico para o produtor |
| Fornecedor | `Partner` + papel `FORNECEDOR` | De quem se compra |
| Comprador | `Partner` + papel `COMPRADOR` | Quem compra da gente |
| Frigorífico | `Partner` + papel `FRIGORIFICO` | Coperfrigu, Boi Brasil |
| Transportador | `Partner` + papel `TRANSPORTADOR` | |
| Comissionado / Corretor | `Partner` + papel `COMISSIONADO` | Quem recebe comissão |
| Favorecido | `Partner` + papel `FAVORECIDO` | Quem recebe o pagamento |

> **Nunca duplicar a pessoa** porque ela exerce dois papéis. Um `Partner`, vários `PartnerRole`.

## Rebanho

| Tela | Código | Nota |
|---|---|---|
| Categoria | `AnimalCategory` | Sexo + faixa etária |
| Lote | `Lot` | Unidade de custeio e de resultado |
| Raça | `Breed` | Nelore, predominante |
| Movimentação | `HerdMovement` | O evento |
| Lançamento do razão | `HerdLedgerEntry` | A linha gerada, com sinal |
| Saldo | — | **Calculado**, nunca campo |
| Posição | — | Saldo em uma data |
| Cabeça | `head` | Unidade de contagem |
| Brinco | `ear_tag` | Identificação individual |
| Pesagem | `Weighing` | Não altera saldo |
| Conferência | `Weighing` motivo `CONFERENCIA` | Recontagem com pesagem |

### Categorias reais

| Tela | `age_order` |
|---|---|
| Bezerros Mamando / Bezerras Mamando | 1 |
| Machos Desm. até 12m / Fêmeas Desm. até 12m | 2 |
| Machos 13 a 24 meses / Fêmeas 13 a 24 meses | 3 |
| Machos 25 a 36 meses / Fêmeas 25 a 36 meses | 4 |
| Touros / Fêmeas + 36 meses | 5 |
| Tropa | — |

"Desm." = desmamado. "Tropa" = equinos de trabalho, contados junto por hábito da fazenda.

### Tipos de movimento

| Tela | Código | Linhas |
|---|---|---|
| Saldo inicial | `SALDO_INICIAL` | 1 (+) |
| Compra | `COMPRA` | 1 (+) |
| Nascimento | `NASCIMENTO` | 1 (+) |
| Transferência | `TRANSFERENCIA` | **2** |
| Evolução | `EVOLUCAO` | **2** |
| Reclassificação | `RECLASSIFICACAO` | **2** |
| Abate | `ABATE` | 1 (−) |
| Venda | `VENDA` | 1 (−) |
| Morte | `MORTE` | 1 (−) |
| Consumo / Doação | `CONSUMO_DOACAO` | 1 (−) |
| Ajuste de inventário | `AJUSTE_INVENTARIO` | 1 (±) |

**Evolução** é a mudança de categoria por idade — o animal completa 12 meses e passa de "Desm. até 12m" para "13 a 24 meses".

## Operações

| Tela | Código | Nota |
|---|---|---|
| Compra | `Purchase` | |
| Venda | `Sale` tipo `VENDA` | Animal vivo |
| Abate | `Sale` tipo `ABATE` | Vendido para frigorífico |
| Custo / Despesa | `CostEntry` | |
| Centro de custo | `CostCenter` | |
| Classe | `CostClass` | Custeio ou Investimento |
| Custeio | `CUSTEIO` | Gasto da safra |
| Investimento | `INVESTIMENTO` | Imobilizado |

## Medidas

| Tela | Código | Definição |
|---|---|---|
| Arroba (@) | `arroba` | **15 kg de carcaça** |
| Peso vivo | `live_weight_kg` | Animal em pé |
| Peso de carcaça | `carcass_weight_kg` | Após abate |
| Rendimento | `yield_rate` | carcaça ÷ peso vivo |
| GMD | `daily_gain_kg` | Ganho médio diário |
| @ produzida | `arrobas_produced` | Ganho de carcaça ÷ 15 |
| Quebra | `shrinkage` | Perda de peso no transporte |
| Cabeça-dia | `head_day` | Base de rateio de custo |
| UA | `animal_unit` | Unidade animal: 450 kg de peso vivo |

> Onde o documento disser "@" sem qualificar, é **arroba de carcaça**. É como o negócio precifica.

## Financeiro

| Tela | Código |
|---|---|
| Título | `Invoice` |
| A pagar | `A_PAGAR` |
| Programado | `PROGRAMADO` |
| Aprovado | `APROVADO` |
| Pago | `PAGO` |
| Parcial | `PARCIAL` |
| Baixa | `settle` |
| Desfazer / Excluir | `undo` / `delete` |
| Adiantamento | `advance` |
| Baixa (pagamento ou recebimento) | `Payment` |
| Favorecido do título | `payee` |
| Segundo fator | `TOTPDevice` |

## Termos do frigorífico (Fase 5)

Usados no ciclo de compra ([08](../regras-negocio/08-ciclo-de-compra.md)). Em código: `Commitment` (compromisso), `Trip` (viagem), `Receiving` (recebimento), `GradingLine` (linha do romaneio), `Settlement` (acerto).

| Termo | Significado |
|---|---|
| Romaneio | Documento do abate, com pesos e classificação |
| Acerto | Fechamento de conta entre frigorífico e produtor |
| Compromisso | Contrato de compra |
| Faixa de preço | Preço por classificação de carcaça (Faixa 1 a 5) |
| Classificação | Grau de acabamento: magro, gordura escassa, mediana, uniforme |
| ADF | Autorização de compra |
| GTA | Guia de Trânsito Animal |
| Funrural | Contribuição sobre a venda de produto rural |
| Fundepec | Fundo de desenvolvimento da pecuária |
| Precoce | Incentivo fiscal para abate de animal jovem |

## Convenções de código

```python
# Modelo: singular, PascalCase, inglês
class HerdMovement(models.Model):
    # Campo: snake_case, inglês
    head_count = models.PositiveIntegerField()

    # verbose_name em português — é o que aparece na tela
    class Meta:
        verbose_name = "Movimentação de rebanho"
        verbose_name_plural = "Movimentações de rebanho"

# Serviço: verbo em português quando é ação de negócio
def confirmar_compra(compra, *, usuario): ...

# Seletor: substantivo
def saldo_por_fazenda(*, safra): ...
```

Nomes de **estrutura** em inglês; nomes de **ação de negócio** em português, porque é assim que se conversa sobre eles com quem usa o sistema. Misturar os dois é deliberado e tem regra: se o termo aparece na tela, o código o escreve em português.

## Grafias da planilha

Preservadas na importação, corrigidas no cadastro:

| Planilha | Sistema |
|---|---|
| `VACINA COFERENCIA` | Vacina / Conferência |
| `SAO JOSE DO GROTAO` | São José do Grotão |
| `FRANSCICO` (nome do arquivo) | Francisco |
| `EVOLUÇ` | Evolução |
| `TRANSF. E` / `TRANSF. S` | Transferência (entrada/saída) |
