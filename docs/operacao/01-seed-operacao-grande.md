# Dados de demonstração: o seed de uma operação grande

Para ver o sistema cheio — dashboard, relatórios, ciclo de compra, financeiro — sem digitar nada, existem dois comandos que se complementam:

```bash
docker compose exec web python manage.py seed_operacao_grande
docker compose exec web python manage.py desfazer_seed_operacao_grande
```

**Só para desenvolvimento.** Os dois recusam `DEBUG=False` (a não ser com `--force`, por sua conta e risco). Nunca rodar em produção: o seed inventa compras, vendas e pagamentos.

## O que o seed cria

Uma operação pecuária de grande porte, de **01/07/2024 até hoje**, em três safras (2024/2025, 2025/2026 e 2026/2027 em andamento):

| Área | O que aparece |
|---|---|
| Fazendas | 12, em 4 perfis: **cria** (4), **recria** (3), **engorda a pasto** (3) e **confinamento** (2), em duas unidades, com pastos, estruturas e máquinas |
| Parceiros | ~35: produtores, frigoríficos, compradores, transportadoras, comissionados e favorecidos de tributo, com papéis múltiplos e contas bancárias fictícias |
| Rebanho | saldo inicial, nascimentos (agosto a novembro), desmama, evolução de categoria, transferência cria → recria → engorda, mortes por causa, descarte de matrizes |
| Compras | diretas (frete, comissão e tributo digitados; à vista, 30 dias e parcelado), de touros e o **ciclo completo OP**: compromisso → viagem → recebimento → romaneio → acerto, em todas as etapas |
| Vendas | abates (com carcaça e rendimento) e venda de animal vivo, a vários frigoríficos |
| Reprodução | um ciclo por fazenda de cria e safra, com números coerentes com os nascidos |
| Custos | mensais por fazenda e centro (rateados entre os lotes), custo direto de entrada e dieta de confinamento, uso de máquinas |
| Financeiro | títulos programados, aprovados e baixados (PIX, TED, boleto, cheque), baixas parciais, títulos **em aberto e vencidos** |
| Casos propositais | lote sem pesagem há mais de 90 dias, abate sem peso de carcaça, rendimento fora da faixa, lote no prejuízo, correções e exclusões com motivo, uma baixa desfeita, operação cancelada |

Tudo nasce **pelos serviços do sistema** (os mesmos das telas), então o razão fecha, os títulos são gerados, o rateio vale e a auditoria registra. O resultado é determinístico: a mesma `--semente` produz o mesmo histórico.

## O que o seed NÃO faz

- **Não cria nem altera usuário.** Lança em nome de um `ADMIN` e aprova em nome de um `GESTOR` que já existam (se não houver `GESTOR`, o `ADMIN` aprova e o comando avisa). Sem `ADMIN` ativo ele para.
- Não muda `is_current` de nenhuma safra e não toca nas safras, categorias, fazendas ou parceiros que já existem.
- Não concede acesso às fazendas novas, a menos que se peça: `ADMIN` e `GESTOR` veem tudo; os demais papéis só veem as fazendas do seed com `--vincular-acessos`.

## Opções

| Opção | Efeito |
|---|---|
| `--semente N` | Muda a sequência aleatória (padrão 360) |
| `--escala 0.2` | Volume reduzido (1 = completo). Bom para testar rápido |
| `--vincular-acessos` | Dá acesso às fazendas do seed aos usuários de papel restrito que já existem |
| `--manter-safras-abertas` | Não encerra as safras passadas que o seed criou |
| `--force` | Permite rodar com `DEBUG=False` |

## O período termina antes de hoje, às vezes

O sistema escolhe a safra de um lançamento **só pela data**, sem olhar a empresa. Se outra empresa do mesmo banco tiver uma safra que começa dentro do período (por exemplo, uma safra 2026/2027 iniciada em 01/10/2026), os lançamentos a partir dessa data cairiam na safra errada. Por isso o seed para na **véspera** do começo dessa safra e diz isso na saída.

## Como o seed é reconhecido

Os modelos não têm coluna de marca; o seed é identificado por:

- **fazendas** com código `S3-…` (e unidades `S3-…`) — tudo que ele lança pertence a uma delas;
- **parceiros** com `[seed-3safras]` em `notes`;
- **safras, raças e categorias que ele criou** — pela auditoria: cada criação grava um evento `CREATE` com um `request_id` fixo do seed. O que já existia antes não tem esse evento e nunca é apagado.

## O desfazer

```bash
python manage.py desfazer_seed_operacao_grande --simular   # mostra o que sairia, não apaga
python manage.py desfazer_seed_operacao_grande             # pede para digitar 'desfazer'
python manage.py desfazer_seed_operacao_grande --sim       # sem perguntar
```

- **Apaga de verdade** (não é exclusão lógica): o sistema volta ao estado anterior ao seed. Isso exige desligar, dentro da transação, o gatilho que torna o razão append-only; por isso o comando só roda com `DEBUG` ligado.
- **Tudo ou nada.** As chaves estrangeiras são conferidas no fim (`SET CONSTRAINTS ALL IMMEDIATE`). Se algum dado **seu** (fora do seed) ainda depender de algo que seria apagado — por exemplo, um custo real pago a um parceiro do seed —, o comando para e **não apaga nada**, dizendo o que impede.
- **Usuários e seus acessos não são tocados.**
- **A auditoria nunca é apagada** (regra 5 do projeto): os eventos do seed continuam lá, e o desfazer grava mais um (`SeedOperacaoGrande`, ação `DELETE`) dizendo quem apagou quanto. A linha do tempo de operação (`OperationEvent`) dos registros apagados sai junto.
- Pode rodar o seed de novo depois.

## Cuidados

- `conferir_importacao` compara os números do banco com a planilha real e **passa a divergir** enquanto o seed estiver no banco.
- O dashboard calcula resultado e rateio por lote na hora. Com centenas de lotes ele fica mais lento que os ~2 s medidos com ~60 lotes ([11-dashboard-analitico](../regras-negocio/11-dashboard-analitico.md#desempenho)). É esperado; use `--escala` para um volume menor.
- Os dados são fictícios, inclusive CPF/CNPJ, telefone e conta bancária.

## Testes

`apps/organizations/tests/test_seed_operacao.py` (escala 0,05): razão sem posição negativa e transferências conciliadas · usuários e acessos idênticos antes e depois · rodar duas vezes é recusado · `--simular` não apaga · desfazer devolve **todas** as tabelas à contagem anterior (exceto a auditoria, que só cresce) · dado real que não é do seed sobrevive · dado real que depende do seed **impede** o desfazer · `DEBUG=False` é recusado · sem `ADMIN` não cria usuário.
