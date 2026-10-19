# Validação para publicação — 19/10/2026

Complementa a [rastreabilidade dos pedidos e roteiro de homologação](2026-10-18-pedidos-cliente.md). Esta validação foi feita localmente, com PostgreSQL 16, Redis e dados fictícios em ambiente Docker isolado. Nenhum deploy, push ou alteração no banco de produção foi realizado.

## Correções encontradas na revisão

- O título de um complemento de frete não pode ser editado, excluído ou restaurado isoladamente pelo Financeiro. Essas ações passam pelo complemento, mantendo título, distribuição e custos juntos. Programação, aprovação e baixa continuam no Financeiro. A tela indica e oferece acesso à origem.
- Complementos excluídos podem ser restaurados pela própria operação. Um complemento confirmado recupera o mesmo título e seus custos; um rascunho volta como rascunho, sem gerar dívida. A restauração repetida é recusada.
- O custo de aquisição também considera o complemento quando a compra foi carregada por uma relação com `select_related`, sem a anotação do gerenciador de compras.

As correções seguem os pedidos de integridade, auditoria e reversibilidade do frete. Não exigem novas migrações além das cinco já preparadas.

## Evidências

- **26 testes de aceite passaram com as configurações padrão de autenticação**, em 31,81 s. Incluem animais pagos e operação encerrada, rateio e centavos, concorrência, rollback, preservação do razão, bloqueio por pagamento, correção, exclusão, restauração, filtros, exportações e escopo de acesso.
- A versão anterior foi obtida do `HEAD` anterior às mudanças, recebeu suas migrações e dados fictícios: compra confirmada, movimentação de rebanho, custos, título pago e auditoria. Após aplicar as cinco migrações novas, os hashes dos registros e colunas preexistentes permaneceram idênticos em **56 tabelas, com 114 registros**. Apenas os dois novos centros de frete foram acrescentados ao cadastro verificado.
- Um backup PostgreSQL em formato customizado foi criado antes das migrações, restaurado em outro banco descartável e conferido pelos mesmos hashes: todos os registros anteriores permaneceram idênticos.
- A imagem do estágio `prod` foi construída, incluindo CSS e coleta de estáticos, sob uma tag exclusiva de validação. Na imagem, `check --deploy --fail-level WARNING`, `makemigrations --check --dry-run` e `migrate --check` passaram. Foram usadas variáveis fictícias válidas e HSTS habilitado; isso não certifica o `.env` real do servidor.
- A imagem iniciou com Gunicorn. Login respondeu HTTP 200; `/health/` e `/ready/` responderam com sucesso, incluindo banco e Redis. O worker Celery da imagem iniciou em fila isolada e respondeu `pong`.
- Chromium verificou autenticação e dez telas em **360, 390 e 1.366 px**: lista/detalhe/novo compromisso, novo/detalhe de frete, compra direta, dashboard de rebanho e relatórios de compromissos, rebanho consolidado e custos detalhados. Todas responderam HTTP 200, sem erros de JavaScript ou transbordamento horizontal da página. A rolagem interna das tabelas é preservada.
- Pendências começam abertas, recolhem com Enter e reabrem com Espaço, mantendo o resumo visível. A confirmação de um frete fictício também foi executada pelo navegador em 360 px, com CSRF e acesso ao título vinculado.
- Ruff nos módulos afetados, checks do Django e `git diff --check` passaram.

A regressão completa terminou com **1.934 testes aprovados, nenhuma falha e 80 testes pulados**, em 7 min 9,65 s. Os testes pulados dependem das planilhas reais locais indisponíveis. A execução ampla usou hash rápido de senha somente em uma configuração temporária fora do repositório, além de banco e Redis descartáveis. Os 26 cenários de aceite foram repetidos separadamente com a configuração padrão do projeto. Não há bloqueio encontrado nesta validação local para publicar pelo procedimento abaixo.

## Sequência de publicação e conferência

1. Incluir no commit todos os arquivos novos da atualização, especialmente as cinco migrações, serviços, filtros e templates. `git commit -am` sozinho não inclui arquivos novos. Conferir o commit antes do push.
2. No VPS, seguir o procedimento existente pela raiz do projeto: `./atualizar.sh`. O script chama o deploy com backup, build, migrações, estáticos, reinício de web/worker/beat e healthcheck. O backup deve terminar com sucesso antes da migração. Não executar `seed_demo` em produção.
3. Ao terminar, conferir `docker compose -f docker-compose.prod.yml ps` e `./deploy/healthcheck.sh`. Confirmar que web, worker e beat estão ativos e sem erros de inicialização nos logs; conferir CSS, login e navegação pelo domínio HTTPS real.
4. Conferir primeiro registros já existentes: saldo de rebanho, títulos pagos e valores de uma compra conhecida. O histórico deve continuar sem classificação automática.
5. Executar o roteiro de homologação ligado aos materiais do cliente. Para testes com lançamentos, identificar os registros de homologação e usar os fluxos normais de correção/exclusão; não apagar linhas diretamente do banco. Validar frete posterior, filtros e exportações, mapa consolidado e pendências no celular.

Se a publicação falhar, o procedimento existente pode voltar a imagem e mantém o esquema do banco. Depois que houver complementos efetivamente lançados, a versão antiga pode deixar de mostrar esses custos nos indicadores. Não remover tabelas, reverter migrações nem restaurar um backup antigo sobre movimentos novos sem uma análise dos dados posteriores ao backup.

## Limites desta liberação

A homologação operacional do cliente e a conferência do servidor após o deploy continuam necessárias. Não foi acessado o VPS nem validado seu domínio, `.env`, espaço em disco ou backup real. As planilhas reais dos importadores não estão disponíveis neste ambiente; a suíte cobre os arquivos sintéticos e os fluxos existentes, sem certificar uma carga real do cliente. A medição do dashboard e seus limites estão no documento de rastreabilidade.
