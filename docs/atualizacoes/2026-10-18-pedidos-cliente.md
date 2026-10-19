# Atualização solicitada pelo cliente — 18/10/2026

Fonte exclusiva: arquivos numerados de `atualizacao/`. A numeração representa a ordem das mensagens, não prioridade técnica. As imagens foram conferidas; os áudios estão disponíveis como transcrições nos arquivos TXT. Os arquivos 7 e 9 contextualizam a reunião e não criam demandas adicionais.

## Decisões confirmadas

- A aprovação do acerto continua sendo o momento de entrada no rebanho. Pagamento e frete posterior não adiam a entrada.
- O encerramento continua manual, por gestor/administrador, depois do recebimento, da conferência, dos pesos e do acerto aprovado. Não é necessário já ter pago os animais.
- Frete adicional pode ser lançado na mesma operação, mesmo encerrada e com animais pagos. A safra encerrada continua sendo bloqueante.
- Gado Próprio, Parceria e Parceria Boi Brasil são classificações. Não representam regras novas de divisão de resultado.
- Os formulários novos exigem classificação; registros históricos e integrações dos importadores preservam o vazio e o texto livre de parceria. Editar um registro antigo permite mantê-lo sem classificação.
- Importação: avaliar e testar o que existe; não construir importadores novos.

## Rastreabilidade e aceite

| Material / item do documento 8 | Entrega | Como homologar |
|---|---|---|
| 1–2; documento 8, itens 1 e 18 | Ajuda explica pré-compra, aprovação, viagem, recebimento, romaneio, acerto e compra direta | Abrir o botão de informação de Compromissos; confirmar que não é necessário criar uma compra antes |
| 3–4; documento 8, itens 6 e 8 | Filtros de unidade, fazenda, comprador, produtor, período e situação na lista; classificação adicional | Combinar filtros e navegar pelas páginas; limpar e recuperar a lista |
| 5–6 | Pendências recolhíveis, inicialmente abertas | Recolher/abrir com mouse e teclado; título e contador permanecem visíveis |
| Documento 8, itens 1 e 6 | Relatório de compromissos e previsão financeira, exportável | Conferir valores previstos e condições; exportar CSV/XLSX/PDF; verificar que não gerou título |
| Documento 8, itens 1–3 | Encerramento validado e complemento de frete | Aprovar acerto, pagar animais, encerrar operação; complementar frete sem recriar compra ou movimentar animais |
| Documento 8, itens 3–5 | Título próprio para transportadora e custo direto de frete de compra | Confirmar uma vez; repetir confirmação; conferir um título e um custo por compra rateada |
| Documento 8, itens 4–5 | Centros separados para animais, comissão, frete de compra e frete de transferência | Conferir custos gerados; lançar frete de transferência como custo manual no centro correspondente |
| Documento 8, itens 7–8 e 16 | Comprador, produtor e origem nas compras; filtros operacionais nos relatórios do ciclo | Conferir compra direta e compra proveniente de acerto; exportar com os filtros aplicados |
| Documento 8, itens 9–12 | Detalhamento com unidade/código, centro, classe, pagador, origem, compra e referência | Filtrar por centro e unidade; somar valores e confrontar a exportação |
| Documento 8, item 13 | Tipos de operação nos compromissos, compras, custos e relatórios | Criar operação com cada tipo, verificar propagação; conferir que o histórico não foi reclassificado |
| Documento 8, itens 14–15 | Mapa de Gado e relatório consolidado por unidade/fazenda/categoria | Comparar totais, ranking e machos/fêmeas; transferir entre fazendas e verificar conservação do total |
| Documento 8, item 17 | Avaliação da importação existente | Consultar matriz abaixo e executar os testes de importação em banco isolado |

## Regras do frete e dos relatórios

O complemento representa **valor adicional ainda não contabilizado**. Frete já incluído no acerto não é substituído pelo complemento. Na operação, os complementos têm rascunho, confirmação, correção com motivo e exclusão com análise de impacto. Correção/exclusão com baixa de pagamento é recusada. Um complemento com várias compras exige distribuição explícita cuja soma feche em centavos. Se o frete chegar depois da virada de safra, título e custo usam a safra da data do frete; a compra continua na safra original. As safras envolvidas devem estar abertas.

Custos do complemento carregam a compra, o lote e o próprio complemento como origem. O custo de aquisição inclui a distribuição confirmada uma única vez; os custos gerados pela compra continuam excluídos da parcela de custos avulsos do lote. O acerto original e os valores dos animais não são reescritos. Para reabrir o acerto, excluir antes os complementos, respeitando bloqueios de pagamentos. Correção, exclusão e restauração do título e dos custos passam pelo complemento; a programação e a baixa ficam no Financeiro. Restaurar um complemento confirmado recupera seu título e seus custos; restaurar um rascunho não gera obrigação financeira.

Os centros novos `FRETE DE COMPRA` e `FRETE DE TRANSFERÊNCIA` são criados sem renomear nem reclassificar lançamentos antigos no centro `FRETE`. O centro existente `DESPESA GADO` continua identificando a compra dos animais, separado de comissão e frete.

O relatório de compromissos abre por padrão nos compromissos não excluídos e ainda não encerrados. Valor previsto incompleto aparece como `—`, inclusive no total; previsão de pagamento depende de retirada prevista e prazo e não equivale ao vencimento definitivo. Condições parceladas permanecem identificadas pela condição de pagamento.

Relatórios por item aplicam categoria às linhas. Relatórios cujo objeto é a operação, comissão ou viagem selecionam operações que contêm a categoria e mantêm os valores completos da operação, com nota explicativa. Não se inventa rateio financeiro por categoria. O custo detalhado permite selecionar a natureza da despesa pelo centro de custo.

O mapa e o relatório consolidado usam o mesmo serviço sobre o razão até a data de corte da safra. A visão geral respeita empresa e fazendas autorizadas. Fazendas antigas sem unidade são preservadas no saldo quando o razão identifica a empresa pela safra; o filtro de unidade não lhes atribui um código fictício.

## Avaliação da importação existente

Formato aceito: Excel `.xlsx`, até 20 MB, com validação de assinatura. O fluxo existente é upload → staging → opções/mapeamento → validação por linha → prévia → confirmação transacional. Não há importação genérica de qualquer planilha.

| Uso citado pelo cliente | Situação encontrada | Limite |
|---|---|---|
| Rebanho e histórico de movimentações | Importador existente | Exige formato/mapeamento suportado e cadastros relacionados; transferência deve fechar origem e destino |
| Compras históricas | Importador existente | Confirma compras sem gerar títulos financeiros históricos; não importa o ciclo completo compromisso/viagem/acerto |
| Despesas históricas | Importador existente | Requer resolver fazenda, classe e centro; não é cadastro em lote de centros de custo |
| Pesagens e vendas históricas | Importadores existentes | Exigem vínculo e validação operacional dos registros |
| Cadastros iniciais genéricos | Sem importador dedicado | Não considerar suportado como carga genérica |
| Unidades e fazendas | Sem importador dedicado | Cadastrar antes de importar os movimentos dependentes |
| Centros de custo | Sem importador dedicado | Cadastrar e mapear os centros antes da confirmação dos custos |
| Dados históricos arbitrários | Suporte limitado aos cinco importadores | Validar o layout real e a prévia antes de qualquer carga |

A suíte existente cobre arquivos de teste gerados em memória, datas/decimais, erros de célula, staging sem efeitos, duplicidade por conteúdo, cancelamento, rollback e rastreabilidade por linha. Testes que dependem das planilhas reais locais são identificados separadamente quando esses arquivos não estiverem disponíveis. Nenhuma planilha de produção foi importada nesta atualização.

## Entrega e publicação

Migrações aditivas: novos campos preservam o histórico vazio; novos modelos registram complementos e distribuições; novos centros não alteram os lançamentos antigos. Nenhuma migração dá baixa, recria compra ou recalcula o razão histórico.

Antes de publicar: homologar os cenários da tabela, fazer backup pelo procedimento existente e aplicar migrações antes de iniciar os processos com o código novo. Recompilar o CSS para as classes usadas nos templates. A publicação deve seguir o guia de produção existente; não executar seed de demonstração no servidor. Se for necessário voltar o código após uso dos complementos, preservar o banco e os registros financeiros; um rollback de código antigo pode deixar de exibir custos complementares nos indicadores. Não apagar tabelas ou lançamentos para reverter a implantação.

## Validação local

- Regressão final dos módulos afetados: **1.318 testes passaram**, sem falhas. Abrange core, custos, compras, ciclo de compra, relatórios, dashboard, documentos, exportação, lotes e financeiro.
- Aceite com a configuração padrão do projeto: **20 testes passaram**, incluindo concorrência real em PostgreSQL, preservação de pagamentos e do razão, rollback, rateio, filtros, exportação, cache e virada de safra.
- A suíte geral também foi executada. As oito falhas encontradas foram corrigidas e os oito testes passaram no reteste; o caso de data futura do financeiro havia atravessado a meia-noite durante a execução e passou ao ser reexecutado. **80 testes foram pulados por ausência das planilhas reais locais**. Isso não valida uma carga real do cliente.
- A regressão ampla usou PostgreSQL/Redis descartáveis e hash rápido somente nas configurações temporárias de teste, fora do repositório. A aplicação continua com sua configuração de autenticação original; o aceite foi repetido com ela.
- Ruff, checks do Django, consistência das migrações e compilação do CSS concluídos. O aviso do Browserslist sobre sua base antiga não impediu a compilação; não foram atualizadas dependências fora do pedido.
- O comando `medir_desempenho --comparar` conferiu que os dados dos gráficos existentes permaneceram iguais aos da linha de base. O novo mapa acrescenta uma consolidação e seletores: a aba Rebanho passou de 26 para 30 consultas; o conjunto medido passou de 321 para 329. O tempo total no pequeno banco demonstrativo foi de 0,70 s para 0,77 s, sem representar medição de capacidade de produção. Os testes de quantidade de consultas por lote continuam passando.

Os resultados acima registram a primeira etapa da validação. A [revisão para publicação de 19/10/2026](2026-10-19-validacao-producao.md) acrescenta os testes de integridade, migração, restauração e navegador em celular. A aceitação operacional pelo cliente permanece necessária, sem publicação automática.
