# Exportação de dados

Leva os dados do sistema para fora — tudo, ou só o que o usuário escolher — em CSV, Excel, JSON e PDF. Serve a quem quer guardar uma cópia, analisar em outra ferramenta ou, um dia, deixar de usar o sistema **sem perder nada**. Código em `apps/exports` (`catalog.py`, `tabular.py`, `writers.py`, `packaging.py`, `services.py`, `tasks.py`).

Tela: **Sistema → Exportações** (`/exportacoes/`). Papéis: `ADMIN`, `GESTOR`, `ESCRITORIO` e `FINANCEIRO` ([#44](99-pendencias.md#44--🟢-quem-exporta-e-o-que-cada-papel-leva-fase-6)). `CAMPO` e `CONSULTA` não entram.

É o espelho da [importação](../migracao/01-planilhas-e-importacao.md): lá, planilha → prévia → confirmação → sistema; aqui, sistema → escolha → processamento em segundo plano → arquivo.

---

## O que se pode exportar

Duas famílias, escolhidas na mesma tela:

| Família | O que é | De onde vem |
|---|---|---|
| **Dados do sistema** | Cada tabela como está gravada: compras, lotes, razão do rebanho, títulos, parceiros, auditoria... (44 conjuntos, em 10 grupos que seguem o menu) | `catalog.CONJUNTOS` — um modelo por conjunto |
| **Relatórios prontos** | Os mesmos relatórios das telas (custo por centro, desempenho do lote, resultado, contas a pagar...) | `reports.services` — **o mesmo serviço da tela** |

Os dois existem por causa da regra 6: o que é **derivado** (peso médio, custo por @, GMD, margem) não está gravado em lugar nenhum, é calculado por um serviço. Quem exporta só os dados não leva o indicador; quem quer o número pronto exporta o relatório, e o número do arquivo é o da tela. Não há segundo cálculo escondido na exportação.

**Opcionalmente**, junto: os **arquivos anexos** — as planilhas que foram importadas e os PDFs que foram gerados.

### Filtros (opcionais)

Fazenda · safra · período (de/até) · incluir registros excluídos. Valem para o que tem fazenda, safra ou data (cada conjunto declara por qual caminho); cadastros gerais — parceiros, categorias, raças, classes — saem completos. A tela diz isso.

**Registros excluídos** (regra 5: a exclusão é lógica) só saem se o usuário pedir, e saem marcados (`Situação = Excluída`, com data e motivo). Linhas retiradas de um documento (itens de compromisso, cargas, linhas de acerto) seguem a mesma opção. Documento excluído esconde as linhas dele.

---

## Formatos

| Formato | Como sai | Para quê |
|---|---|---|
| **CSV** | Um arquivo por conjunto. Dois estilos: *Excel brasileiro* (`;`, vírgula decimal, `dd/mm/aaaa`, BOM) ou *internacional* (`,`, ponto, ISO-8601) | Abrir em qualquer ferramenta |
| **Excel (XLSX)** | **Um** arquivo, uma aba por conjunto, mais a aba *Resumo*. Número é número, data é data; cabeçalho congelado | Analisar |
| **JSON** | Um arquivo por conjunto, que **se descreve sozinho** (`colunas` com tipo e para onde cada vínculo aponta) e traz os `registros` | Reimportar, processar por programa |
| **PDF** | Um por conjunto, só com as **colunas principais**; tabela grande vira partes de 2.000 linhas, até 20.000 | Ler e imprimir |

Cada conjunto é lido **uma vez só** do banco e alimenta todos os formatos pedidos.

### Dois jeitos de ler o mesmo dado

- **Técnico (JSON):** o dado como está no banco. Vínculo é o `id`, escolha é o código (`CONFIRMADA`), `Decimal` é **texto exato** (`"90000.50"`, nunca `float` — [ADR 0005](../arquitetura/adr/0005-decimal-e-arredondamento.md)), data é ISO-8601.
- **Legível (CSV, Excel, PDF):** vínculo é o nome (`LT-SFR-014`), escolha é o rótulo (`Confirmada`). No CSV e no Excel, **cada vínculo ganha uma coluna `(ID)` ao lado**, e toda tabela tem a coluna `ID`: é assim que se religam as tabelas fora do sistema.

Campo vazio sai **vazio**, nunca `0` (regra 3). O "—" é coisa de tela e só aparece no PDF. Nada é arredondado para exportar: as casas decimais são as do banco.

---

## Como roda (e o que o usuário vê)

```
PENDENTE ──► PROCESSANDO ──► PRONTO ──► EXPIRADO
   │              │             ▲
   │              ├──► ERRO     └── baixar (quantas vezes quiser, até expirar)
   └──► CANCELADO ◄┘
```

1. **Pedir** valida contra o acesso do usuário, grava o pedido (com tudo que é preciso para repetir) e põe na fila (`transaction.on_commit` → Celery). A tela de andamento abre na hora.
2. **Andamento.** A tela pergunta a cada 2 s (HTMX) e mostra: a etapa (*"Lendo Razão do rebanho (2 de 5)"*), a barra de progresso, e, **item a item**, a situação e quantos registros saíram. O usuário pode sair e voltar: o pedido continua em **Exportações**.
3. **Pronto.** Botão de baixar. Mais de um arquivo vira **ZIP**; um arquivo só sai **sem ZIP** (quem pediu "os lotes em Excel" recebe um `.xlsx`).
4. **O ZIP leva** os arquivos, um `LEIA-ME.txt` em português (como ler, o que significa cada pasta, as limitações) e um `manifesto.json` com tamanho e **SHA-256** de cada arquivo, os filtros e o **dicionário de colunas** de cada conjunto.

### Falhas

| Situação | O que acontece |
|---|---|
| **Falha ao ler um conjunto** | A exportação **inteira** falha, nomeando o conjunto. Nada é entregue. *Backup que perdeu uma tabela sem avisar é pior que backup nenhum.* O traceback vai para o log; a tela mostra o motivo e o código do pedido |
| **Relatório que não monta, anexo que sumiu do disco** | Vira **aviso**; o resto segue, e o aviso aparece na tela e no `LEIA-ME` |
| **Processador parou no meio** | Sem sinal de vida por 30 min, a manutenção (Celery beat, a cada 15 min) marca **Com erro**: "interrompida". Nada fica pela metade. A tela avisa já aos 10 min |
| **Fila fora do ar** | O pedido vira erro na hora ("não foi possível colocar na fila"), em vez de esperar para sempre |
| **Passou de 1 hora** | Interrompida, com a mensagem de como repartir |
| **Cancelar** | Na fila, na hora. Rodando, o processador percebe em segundos e para; nada é entregue |

Em todos os casos há **"Pedir de novo, com os mesmos parâmetros"**. O processamento é **idempotente**: a fila pode entregar a mesma tarefa duas vezes e só uma roda.

Cada usuário tem no máximo **2 exportações em andamento** (`EXPORT_MAX_ACTIVE_PER_USER`). O limite é conferido com o usuário travado: dois cliques juntos não o furam.

---

## O que protege o dado

Exportar em massa é o jeito mais fácil de vazar dado. Por isso:

1. **Escopo por fazenda, sempre** (regra 4). Cada conjunto declara por onde chega a uma fazenda (`escopo`). Onde o modelo tem `ScopedManager`, a exportação usa `for_user()`; nos demais (linhas de documento, viagens, recebimentos...), o caminho declarado até a fazenda. Quem só enxerga o Baixão só exporta o Baixão, em todos os formatos.
2. **Permissão por conjunto.** Financeiro (`pode_ver_titulos`), ciclo de compra (`pode_ver_o_ciclo`), contas bancárias (`pode_ver_dado_bancario`), usuários (`ADMIN`), auditoria (`pode_ver_auditoria`), importações (`pode_importar`) seguem **a regra da tela correspondente**. A conta bancária **dentro** do título só sai para quem pode vê-la.
3. **Conferido de novo ao executar.** O papel pode ter mudado entre o pedido e o processamento: o conjunto perdido sai do pacote, com aviso — não vaza.
4. **Segredos nunca saem.** `TOTPDevice` e `RecoveryCode` **não estão no catálogo**; `User` só exporta uma lista branca de campos (sem senha, sem `is_superuser`). Nome de campo que lembre `password`, `secret`, `token`, `totp`, `recovery` é barrado por uma rede de segurança, mesmo que alguém o ponha por engano.
5. **Tabela nova não passa batido.** Um teste obriga todo modelo do sistema a estar no catálogo **ou** em `NAO_EXPORTAVEIS`, com o motivo.
6. **Injeção de fórmula.** Texto digitado por gente (parceiro, observação) que começa com `=`, `+`, `-`, `@` é neutralizado no CSV e no Excel, como já era nos relatórios.
7. **Só o dono baixa.** Outro usuário — até o `ADMIN` — recebe **404**, não 403. O arquivo tem os dados do escopo de quem pediu; outro papel não herda isso. Download só por view autenticada, `attachment`, `Cache-Control: no-store`. O arquivo nunca é servido como estático.
8. **O arquivo é temporário.** Fica **7 dias** (`EXPORT_RETENTION_DAYS`), e o dono pode apagá-lo antes. Depois, o arquivo sai do disco; **o pedido e a auditoria ficam** ([#45](99-pendencias.md#45--🟢-por-quanto-tempo-o-arquivo-fica-e-o-que-a-exportação-não-é-fase-6)).
9. **Auditoria** (`EXPORT`): o pedido (conjuntos, formatos, filtros), a conclusão (nome, tamanho, SHA-256) e **cada download**, com quem, quando e IP. **O conteúdo exportado nunca vai para a auditoria nem para o log.**

---

## O que a exportação não é

- **Não é um backup atômico do banco.** Os conjuntos são lidos um depois do outro, não num instante único; um lançamento feito durante a exportação pode estar num conjunto e não em outro. O `LEIA-ME` diz isso. Para a cópia completa e exata do banco, o caminho é o `deploy/backup.sh` ([infra](../arquitetura/02-infra-e-deploy.md)).
- **Não substitui a auditoria.** A trilha é exportável (para o `ADMIN`), mas ela continua só de leitura: ninguém altera nem apaga um evento, nem por aqui.
- **Não reimporta sozinha.** O JSON traz tudo para isso (valores exatos, vínculos por `id`, dicionário de colunas), mas a importação de um arquivo desses é outra tarefa.

---

## Decisões e o que ficou aberto

| Decisão | Por quê | Custo de mudar |
|---|---|---|
| Quem exporta: `ADMIN`, `GESTOR`, `ESCRITORIO`, `FINANCEIRO` | Exportar é levar dado para fora; `CAMPO` e `CONSULTA` ficam de fora até alguém dizer o contrário (#44) | Uma linha em `permissions.py` |
| Falha de **dado** derruba tudo; falha de **relatório/anexo** vira aviso | Pacote incompleto sem aviso é o pior caso | Um `except` em `services._produzir` |
| Arquivo expira em 7 dias | O arquivo tem dado do negócio parado no disco (#45) | `EXPORT_RETENTION_DAYS` |
| Sem snapshot atômico | Segurar uma transação de minutos tem custo no banco inteiro; para cópia exata há o backup | Conexão de leitura com `REPEATABLE READ` |
| PDF só com colunas principais, até 20.000 linhas | PDF de tabela larga é ilegível; o CSV/Excel/JSON têm tudo | `Conjunto.pdf`, `PdfEscritor.LIMITE_DE_LINHAS` |

## Testes

`apps/exports/tests/`: catálogo (modelo fora do catálogo, escopo, segredo, matriz de papéis, `for_user` equivalente) · ponta a ponta nos quatro formatos (SHA-256 do manifesto, JSON exato, planilha com número de verdade) · escopo por fazenda e por papel · cancelar, falhar, expirar, idempotência · telas, andamento por HTMX, download, 404 de outro usuário, CSRF.
