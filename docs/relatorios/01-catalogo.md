# Relatórios

## Princípio

**Relatório não calcula.** Ele chama o mesmo serviço que a tela e o dashboard chamam, e apresenta.

O que não pode acontecer:

```
custo/@ calculado de um jeito no relatório de lote
custo/@ calculado de outro jeito no dashboard
```

Se dois lugares mostram o mesmo indicador com números diferentes, o usuário para de confiar nos dois. Fonte única por cálculo — ver [regras-negocio/05](../regras-negocio/05-indicadores-e-calculos.md).

## Formatos

| Formato | Quando |
|---|---|
| Tela | Sempre. É o uso principal |
| PDF (WeasyPrint) | Quando é documento — vai impresso ou assinado |
| CSV / XLSX | Quando o usuário vai analisar por fora. **Não subestimar**: hoje tudo é planilha, e tirar essa saída é tirar autonomia |

Relatório pesado roda em Celery e avisa quando fica pronto. Navegador não espera.

Todos filtráveis por: período, safra, fazenda, lote, categoria, parceiro, centro de custo. Filtro preservado ao voltar da lista.

**Implementado na Fase 3:** safra e fazenda vêm do contexto fixo no topo; cada relatório declara os demais parâmetros que aceita (`apps/reports/services.py::PARAMETROS`: período, lote, rendimento de entrada estimado). O que o usuário filtrou vira `Relatorio.filtros` — e vai **dentro** do CSV, do XLSX e do PDF.

## Catálogo por fase

### Fase 1 — Rebanho

| Relatório | Responde | Substitui |
|---|---|---|
| **Posição do rebanho** | Quantas cabeças de cada categoria, em cada fazenda, hoje ou em qualquer data | Quadro-resumo das 5 abas de fazenda |
| **Movimentações do período** | O que entrou e saiu, por tipo | Linhas 19+ das abas de fazenda |
| **Ficha do lote** | Origem, movimentações, peso, situação | Não existe hoje |
| **Conciliação de transferências** | Quais transferências não pararam | **Não existe — é o que esconde o −140** |

> O último é o que a planilha não tinha. Lista toda saída sem entrada correspondente. Numa operação saudável vem vazio.

### Fase 2 — Custos e compras

| Relatório | Responde | Substitui |
|---|---|---|
| **Custos por centro de custo** | Onde o dinheiro foi | `DASH FINANCEIRO` |
| **Custos por fazenda** | Qual fazenda consome mais | Tabela dinâmica manual |
| **Custeio × investimento** | Quanto é gasto, quanto é imobilizado | Coluna `CLASSE` |
| **Compras do período** | O que foi comprado, de quem, por quanto | `COMPRA DE GADO` + `DASH COMPRAS` |
| **Custo de aquisição por lote** | Quanto custou formar o lote | Não existe |

### Fase 3 — Vendas e desempenho

| Relatório | Responde | Estado |
|---|---|---|
| **Vendas e abates** | Quanto saiu, para quem, a que preço — substitui `VENDAS` e `DASH VENDAS` (com seções "por mês" e "por comprador") | ✅ |
| **Desempenho do lote** | GMD, @ produzida, dias, rendimento | ✅ |
| **Resultado do lote** | Receita − custos = resultado, e margem por @ | ✅ |
| **Pesagens** | Histórico por lote, com evolução de peso e GMD do trecho | ✅ |
| **Programado × realizado** | Onde a operação divergiu do previsto | ✅ na Fase 5 (a fonte do "programado" é o compromisso) |

> **Programado × realizado** não existe ainda: não há fonte do "programado" — a programação de abate é da Fase 5 (`03_Relatorio_Programacao_de_Abate`). Construir agora seria inventar um modelo de planejamento.

Os quatro chamam os serviços de cálculo (`CarcassService`, `SaleResultService`, `WeightGainService`); há teste que troca o serviço por um falso e prova que o relatório mostra o valor dele. Indicador sem dado aparece como "—" **com a coluna "Por que há —"**.

### Fase 4 — Financeiro

Mapa financeiro · Contas a pagar (e a receber) · Pagamentos realizados · Fluxo de caixa projetado — substituem a `DASH CAIXA`, hoje vazia.

**Como ficou:** os cinco estão no catálogo (`contas-a-pagar`, `contas-a-receber`, `pagamentos-realizados`, `fluxo-de-caixa`, `mapa-financeiro`), com tela, CSV, XLSX e PDF. Só abre quem vê títulos (`403` para os demais, inclusive no PDF); o índice esconde o que o papel não abre. Contas e mapa não dependem da safra do topo (dívida de uma safra se paga em outra); o fluxo percorre os meses da safra escolhida. Dado bancário não vai em relatório — com uma exceção, a **Programação de pagamentos** (abaixo), que mostra banco, agência e conta **só para quem vê dado bancário** ([#27](../regras-negocio/99-pendencias-resolvidas.md)).

**Programação de pagamentos** (`programacao-de-pagamentos`, 2026-10-02, seções 4.3 e 10 do documento funcional): tudo o que há a pagar, com compra, favorecido, documento, vencimento, "pagar em", valor, saldo, banco, agência, conta, situação e **atenção** (sem favorecido, sem conta bancária). Ordem: o que já tem data de pagamento primeiro, depois pelo vencimento. Mesmo recorte de Contas a pagar (em aberto, todas as safras; período filtra o vencimento). Não cria título previsto antes do acerto ([#31](../regras-negocio/99-pendencias-resolvidas.md)).

### Fase 5 — Ciclo de compra

Sete relatórios, com tela, CSV, XLSX e PDF, do mesmo serviço que a tela (`calcular_acerto`, viagem, recebimento). Escopo por fazenda; **negados ao `CAMPO`** (preço, comissão e frete são dado comercial). Não levam dado bancário.

| Relatório | Legado de referência |
|---|---|
| Programação de embarque | `03` |
| Programação de abate | `03` |
| Conferência do acerto (abre pelo acerto: `?acerto=`) | `04` |
| Comissão por comprador — a regra **gravada** no compromisso | `05` |
| Fretes e quebra de viagem | — |
| Histórico por pecuarista | `06` |
| **Programado × realizado** (o que a Fase 3 deixou de fora), com "Por que há —" | — |

Os cinco legados abaixo foram a especificação.

---

## Os relatórios legados (SisAtak / Boi Brasil)

Em `docs/fontes/relatorios-legado/`. São de **outro negócio** — a mesa de compra de um frigorífico. Guardados como especificação da Fase 5.

### `02_Contrato_Compra_Animais_Boi_Brasil.png`
Contrato de compra. Emitente, produtor com CPF/endereço/banco, comprador 1 e 2, datas de movimento/retirada/abate, condição de pagamento, e itens com **preço unitário por faixa** (Faixa 1 a 5: 216,00 / 237,60 / 248,40 / 270,00 / 270,00).

→ Especifica o documento de compromisso e o modelo de preço por faixa. **Pendência #8.**

### `03_Relatorio_Programacao_de_Abate.png`
Programação por contrato: produtor, propriedade, comprador, cidade, datas, quantidade de caminhões, distância, comissão, condição de pagamento, prazo médio, e itens com cabeças e preços por faixa.

→ Especifica a programação logística da Fase 5.

### `04_Conferencia_do_Acerto.png`
O mais denso. Três blocos:

- **Resumo financeiro/tributário** — líquido de NF, Funrural, frete, ICMS, crédito, desconto, romaneio, comissão, comissão extra, Fundepec, GTA, outras taxas, taxas de abate, adiantamento
- **Detalhamento financeiro** — títulos com emissão, vencimento, valor, favorecido, banco, agência, conta
- **Romaneio de abate valorizado** — por produto, classificação e faixa de peso: cabeças, peso, média @, valor/@, valor/kg, % desconto, valor líquido

Classificações observadas: Magro, Gordura Ausente, Gordura Escassa, Gordura Mediana, Gordura Uniforme, Lesão Traumática. **Parametrizáveis**, nunca fixas no código.

→ Especifica o acerto da Fase 5, e é a evidência de que classificação de carcaça precisa ser cadastro.

### `05_Relatorio_Comissao_por_Comprador.png`
Por comprador: romaneio, data de abate, pecuarista, machos, fêmeas, cabeças, regra, valor. **Pendência #4.**

### `06_Historico_de_Abate_por_Pecuarista.png`
O mais próximo do nosso negócio. Por pecuarista: romaneio, data, cidade, condição de pagamento, cabeças, sexo, peso, média @, valor, comissão, frete, distância, R$/@ e **custo/@**.

→ O bloco de indicadores finais (`R$ @`, `Icms`, `Custo @`) é praticamente o que o nosso relatório de resultado por lote precisa mostrar. Vale como referência **já na Fase 3**, mesmo sem a Fase 5.

---

## Padrão visual

Cabeçalho com sistema, nome do relatório, data/hora de emissão, período e filtros aplicados, página x/y. Rodapé com quem emitiu.

Os filtros aplicados **impressos no relatório** — sem isso, papel na mesa não diz a que se refere. É a falha mais comum, e os legados acertam nela.

Aparência profissional e sóbria. **Não** reproduzir o SisAtak pixel a pixel: reproduzir os conceitos e os números.

## Exportação (Fase 3)

| Formato | Detalhe |
|---|---|
| CSV | `;` como separador, vírgula decimal, BOM UTF-8. Título, **filtros aplicados** e notas no topo. |
| XLSX | Números como **números**, com formato de moeda, milhar e %. Dado ausente vai como "—" (célula vazia pareceria zero numa tabela dinâmica). Cada seção do relatório vira uma aba. Filtros, notas e "emitido em… por…" no topo. |
| PDF | WeasyPrint. A4, paisagem quando há mais de 7 colunas. Cabeçalho repetido em **toda página**: sistema, relatório, emissão e filtros aplicados; rodapé com quem emitiu e "Página x de y". |

Toda exportação é auditada (`EXPORT`) com os filtros.

## Documentos gerados

Todo PDF que vira documento registra: `document_id`, tipo, entidade, `template_version`, quem gerou, quando, hash do arquivo, caminho.

Assim se responde "qual documento foi gerado quando esta compra foi confirmada?" — e o documento é reproduzível exatamente como era, mesmo que o template tenha mudado depois.

**Implementado (`apps/documents`):** `GeneratedDocument` com `document_id` (UUID), tipo, entidade, `template_version` (hoje `relatorio-v1`), quem gerou, quando, hash SHA-256, filtros impressos, parâmetros (para gerar de novo) e o **arquivo guardado** — o arquivo é a reprodução exata. Só é servido por view autenticada, ao dono e a quem enxerga tudo; para os demais, 404. Relatório pesado (resultado, desempenho, pesagens) vai para o Celery e a tela do documento atualiza sozinha por HTMX; a tarefa é idempotente. Falha mostra o motivo e o código do documento, nunca traceback.
