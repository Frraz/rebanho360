# Desempenho

Como medir, o que foi corrigido e por quê, as metas, e como não regredir. Escrito em 2026-10-04, depois de o seed grande ([01](01-seed-operacao-grande.md)) deixar o dashboard em 5 a 30 s.

> **Princípio:** medir antes de mexer. A primeira medição mudou o diagnóstico: boa parte do que parecia lentidão do sistema era o *django-debug-toolbar* formatando milhares de consultas (a metade do tempo, em dev) e o cliente de teste do Django instrumentando cada template. Os números abaixo são **sem** essas ferramentas.

---

## 1. Como medir

```bash
# banco de carga à parte (não toque no banco de dev)
docker compose exec db psql -U rebanho360 -d postgres -c "CREATE DATABASE rebanho360_perf"
docker compose exec db sh -c "pg_dump -U rebanho360 rebanho360 | psql -q -U rebanho360 -d rebanho360_perf"
DB=postgres://rebanho360:rebanho360@db:5432/rebanho360_perf
docker compose run --rm --no-deps -e DATABASE_URL=$DB web python manage.py seed_operacao_grande --force   # ~10 min, escala 1

# a medição
docker compose run --rm --no-deps -e DATABASE_URL=$DB web \
    python manage.py medir_desempenho --usuario admin@teste
```

`medir_desempenho` abre cada tela pesada como um usuário (dashboard em 9 abas, Início e as listas) e imprime **tempo, número de consultas, tempo no banco** e as consultas que mais se repetem. Opções úteis:

| Opção | Para quê |
|---|---|
| `--so TEXTO` | só as telas cujo nome contém o texto (ex.: `--so Lotes`) |
| `--repetidas N` | quantas consultas repetidas listar por tela (0 desliga) |
| `--salvar PASTA` / `--comparar PASTA` | guarda o conteúdo das abas antes de mexer e **confere que continua idêntico depois**: otimização não muda número |
| `--safra`, `--fazenda` | recorte |

Para ver onde o tempo vai dentro de uma tela, use `cProfile` por um `manage.py shell` com o toolbar desligado (`override_settings(DEBUG_TOOLBAR_CONFIG={"SHOW_TOOLBAR_CALLBACK": lambda r: False})`). No Postgres de dev, `log_min_duration_statement=200` já registra toda consulta acima de 200 ms (`docker compose logs db | grep duration`).

---

## 2. O que estava errado

Não era "muito dado": o seed tem **1.452 linhas** no razão. Era custo que crescia com *lotes × centros de custo × linhas do razão*:

1. **Rateio de custo** relia o razão inteiro da fazenda em Python, uma vez por centro de custo, **por lote**.
2. **N+1 por lote**: desempenho (GMD), entradas, saldo, custo e resultado faziam de 20 a 30 consultas cada, em laço.
3. **Somas em Python** onde devia haver `SUM` (saldo, entradas, posição do rebanho).
4. Trabalho duplicado entre abas (o rateio calculado para a aba de vendas era refeito na de lotes).
5. Ciclo de compra, contas a pagar e tela Início com consulta por compromisso, viagem e título.
6. Índices que as consultas pediam e não existiam.

## 3. O que foi feito

**Cada indicador continua em um único serviço** (regra 6). O serviço ganhou uma versão em lote e a de um lote virou um caso dela:

| Serviço | Em lote | Um lote |
|---|---|---|
| Cabeças que entraram | `cabecas_que_entraram_por_lote` | `cabecas_que_entraram` |
| GMD e @ produzida | `desempenho_dos_lotes` | `desempenho_do_lote` |
| Aquisição, custos, rateio | `financeiro_dos_lotes` | `financeiro_do_lote` |
| Resultado do lote | `resultados_dos_lotes` | `resultado_do_lote` |
| Saldo | `saldo_por_lote` | `saldo` |
| Etapa do compromisso | `etapas_dos_compromissos` | `etapa_do_compromisso` |

- **Cabeça-dia em forma fechada.** Cada linha do razão com quantidade *q* na data *d* vale `q × (fim − max(d, início) + 1)`. O banco soma isso num único `GROUP BY` (`cabecas_dia_por_lote`); e `BaseDeRateio` guarda o razão e os custos indiretos de uma fazenda em memória, como somas acumuladas, para responder qualquer janela por busca binária. Ratear 300 lotes deixou de reler a fazenda 300 vezes.
- **Maior resto com inteiros.** `ratear_em_centavos` usa aritmética inteira quando os pesos são inteiros (cabeças e cabeça-dia são). Mesma regra, sem o contexto decimal de 60 dígitos. *Efeito colateral documentado:* nos empates exatos de fração, a conta antiga decidia por ruído de arredondamento; a nova segue a regra que o código sempre dizia (empate pela ordem de entrada). A soma continua exata.
- **Somas no banco**: `saldo`, entradas, posição do rebanho (uma consulta, não duas por categoria).
- **`Escopo`** (dashboard): `financeiro_dos_lotes` e `fazendas()` calculados uma vez por requisição e compartilhados entre abas; base do razão por fazenda.
- **Financeiro**: contas a pagar/receber pagina no banco; o resumo de vencimentos e o total listado são `aggregate`; o aviso de operações sem título é um `COUNT`. A aba Financeiro do dashboard e o fluxo de caixa somam o que falta pagar **no banco**, agrupado por vencimento, favorecido, tipo e etapa (`titulos_em_aberto_com_saldo`, `saldo_agrupado`), em vez de carregar cada título; os alertas da tela Início (vencidos, a aprovar) contam e somam do mesmo jeito.
- **Início**: vendas sem carcaça contam no banco e trazem só os exemplos.
- **Tabelas gêmeas dos gráficos** limitadas a 100 linhas (aviso de quantas faltam; o gráfico tem todos os pontos): a aba Lotes devolvia 1,3 MB de HTML com 585 lotes.
- **Listas**: lotes paginados (50 por página); auditoria filtra data por faixa de instantes (usa o índice) e guarda 10 min a lista de tipos do filtro.
- **Seed** roda `ANALYZE` no fim.

### Índices (com uso conferido por `EXPLAIN`)

Só ficaram os que o planejador usa (índice custa escrita). Os outros candidatos, `(safra, data)` em compras, vendas e custos, e `(fazenda, data)` em compras e pesagens, **não foram escolhidos** pelo planejador — o índice da chave estrangeira já resolve — e foram descartados.

| Índice | Atende |
|---|---|
| `herd_ledger_farm_date_inc` — razão `(farm, date) INCLUDE (lot, quantity)` | rateio, cabeça-dia, saldo por fazenda: leitura só no índice |
| `herd_mov_date_id_desc`, `herd_mov_type_date` — movimentos | lista de movimentações (`ORDER BY -date, -id LIMIT 30`), filtros do dashboard |
| `weighing_lot_date` — pesagens `(lot, date)` | GMD |
| `costentry_indireto_farm_date` — custos parcial `(farm, date)` onde `lot IS NULL` e confirmado | base do rateio |
| `partner_name_trgm`, `costentry_description_trgm` — trigram em `UPPER(col)` | busca por nome e descrição (o `icontains` do Django vira `UPPER(col) LIKE`) |

Criados com `CREATE INDEX CONCURRENTLY` (não travam a escrita no deploy). Os dois de trigram são `RunSQL` porque o Django 5.0 monta errado o índice de expressão com classe de operador.

### O que **não** foi feito, e por quê

- **Sessão em cache (`cached_db`)**: rejeitado. `encerrar_sessoes` revoga apagando linhas de `django_session`; com sessão em cache, a revogada continuaria válida no Redis. Ganharia 1 consulta por requisição e custaria uma falha de segurança.
- **Hash nos arquivos estáticos**: o nginx já trata `output.css` e `icons.svg` sem hash com cache de 1 h por escolha; trocar exige que toda referência passe por `{% static %}`. Risco sem ganho claro.
- **Cache de resultado do dashboard**: só se, com as consultas corrigidas, alguma aba ainda passar de ~1 s. Se vier, com chave versionada e invalidação a cada escrita, nunca por tempo.
- **Rendimento fora da faixa (tela Início)** continua percorrendo as vendas de abate: reescrevê-lo em SQL duplicaria a fórmula oficial de rendimento (informado × calculado), e a regra 6 manda um lugar só. Custo proporcional ao número de vendas; medir antes de mexer.
- **Relatórios** (PDF e planilha) que listam título a título continuam trazendo as linhas: é o que eles mostram. Rodam em fila (Celery), fora do clique do usuário.

---

## 4. Resultados

Mesmo banco, mesma máquina, sem toolbar. "Consultas" é o número de comandos SQL por requisição.

**Banco 1×** = seed na escala 1: 262 lotes, 941 títulos. **Banco 3×** = escala 3: 585 lotes, 2.508 títulos. Cada célula é *tempo · consultas*.

| Tela | 1× antes | 1× depois | 3× antes | 3× depois |
|---|---|---|---|---|
| Dashboard · Visão geral | 5,69 s · 5.515 | **0,57 s · 232** | 15,00 s · 12.263 | **1,01 s · 238** |
| Dashboard · Rebanho | 0,19 s · 127 | **0,18 s · 98** | 0,21 s · 127 | **0,21 s · 98** |
| Dashboard · Lotes | 6,81 s · 6.453 | **0,47 s · 96** | 17,30 s · 15.168 | **0,93 s · 99** |
| Dashboard · Compras | 0,07 s · 12 | **0,06 s · 12** | 0,16 s · 12 | **0,08 s · 12** |
| Dashboard · Vendas e resultado | 2,32 s · 2.184 | **0,17 s · 52** | 5,38 s · 5.111 | **0,33 s · 55** |
| Dashboard · Custos | 0,55 s · 480 | **0,12 s · 61** | 0,59 s · 480 | **0,13 s · 61** |
| Dashboard · Financeiro | 0,29 s · 17 | **0,09 s · 21** | 0,53 s · 17 | **0,14 s · 21** |
| Dashboard · Ciclo de compra | 0,14 s · 64 | **0,06 s · 19** | 0,32 s · 151 | **0,14 s · 19** |
| Início | 2,17 s · 2.081 | **0,23 s · 71** | 5,38 s · 4.972 | **0,34 s · 74** |
| **Soma** | 18,2 s · 16.933 | **1,95 s · 662** | 44,9 s · 38.301 | **3,31 s · 677** |

O que a tabela mostra:

- **O número de consultas parou de crescer com o volume.** Depois: 662 → 677 consultas no total ao ir de 262 para 585 lotes; antes, 16.933 → 38.301. Aba de lotes: 96 consultas com 262 lotes, 99 com 585.
- **O tempo cresce de forma linear**, e o que sobra é Python montando tabelas e gráficos (no banco, a aba mais pesada gasta 0,09 s de 0,93 s). Dobrar o volume dobra o tempo da aba mais pesada; não o multiplica por 10.
- **O conteúdo não mudou.** No banco 1×, `medir_desempenho --comparar` confirma que o JSON de cada aba do dashboard é idêntico ao do código original.
- Como o dashboard abre nas abas pesadas: Visão geral 0,57 s e Lotes 0,47 s com 262 lotes (eram 5,7 s e 6,8 s); com 585 lotes, 1,0 s e 0,9 s (eram 15 s e 17 s).

> *Ressalva sobre o "3× antes":* essa medição (código original, 585 lotes) rodou em parte com a suíte de testes ocupando a mesma máquina, então os tempos dela podem estar um pouco inflados. O número de **consultas**, que não depende da carga da máquina, é o dado firme: 12 a 15 mil por aba.
>
> As listas (lotes, movimentações, compras, vendas, custos…) já respondiam em 30 a 250 ms e seguem assim; não aparecem na tabela.

---

## 5. Metas e como não regredir

| Meta (escala 1, ~300 a 500 lotes) | Situação |
|---|---|
| Aba do dashboard < 1 s | atingida |
| Início < 400 ms | atingida |
| Listas < 200 ms | atingida |
| **Nº de consultas por aba não cresce com os lotes** | garantido por teste |

`apps/dashboards/tests/test_desempenho.py` mede **consultas, não relógio** (relógio muda de máquina para máquina, contagem não): monta poucos lotes, depois mais, e exige o **mesmo** número de consultas. Um laço com consulta dentro (N+1 novo) faz o segundo cenário executar mais e o teste quebra. Os testes de equivalência (`costs/tests/test_allocation_em_lote.py`, mesmo arquivo de desempenho e `finance/tests/test_selectors.py`) comparam as versões novas com a conta original e com a versão de um lote.

**Regras para código novo:**

1. Consulta dentro de laço (`for x in ...: Model.objects.filter(x=...)`) é bug. Carregue com `__in`, `GROUP BY`, `prefetch_related` ou `select_related`.
2. `sum(... for linha in queryset)` é `aggregate(Sum(...))`.
3. Indicador por lote vai para a versão em lote; a de um lote chama a de lote.
4. Índice novo só com `EXPLAIN` mostrando uso; índice que não é usado só encarece a escrita.
5. Mexeu em consulta do dashboard? `medir_desempenho --salvar` antes e `--comparar` depois.
