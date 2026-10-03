# Segurança

## O que estamos protegendo

| Ativo | Risco se vazar ou for corrompido |
|---|---|
| Dados bancários de parceiros | Fraude direta, dano a terceiro |
| Valores de compra e venda | R$ 4,7 milhões por safra em informação comercial |
| Saldo do rebanho | Patrimônio; base de garantia e de seguro |
| Custos e resultado | Informação estratégica do negócio |
| Dados pessoais (CPF, endereço) | LGPD |

E a ameaça mais provável não é invasão: é **erro humano**. Clique duplo que duplica pagamento, edição acidental de operação encerrada, senha compartilhada entre a equipe.

## Controles por camada

### Rede e transporte
HTTPS obrigatório · HSTS depois de confirmado o TLS · PostgreSQL e Redis sem porta publicada · firewall com 22, 80 e 443 apenas.

### Sessão
Cookies `Secure`, `HttpOnly`, `SameSite=Lax` · sessão expira em 12 horas · `SESSION_EXPIRE_AT_BROWSER_CLOSE` para perfis sensíveis · logout invalida a sessão no servidor.

### Autenticação
Argon2 (`PASSWORD_HASHERS` com `Argon2PasswordHasher` primeiro) · mínimo 10 caracteres com validadores do Django · **rate limit de 5 tentativas por usuário e por IP em 15 minutos** · usuário inativo não autentica, mesmo com senha correta · todo login, logout e falha vai para `AuditEvent`.

**2FA (TOTP) opcional, altamente recomendado a todos** (Fase 4; deixou de ser obrigatório em 03/10/2026 — decisão de Warley). Quem não ativa entra só com a senha; a tela de Início sugere ativar (dispensável por 14 dias) e a página Conta explica. Implementado em `apps/accounts/two_factor.py`, sem biblioteca de OTP (RFC 6238, testado contra os vetores da própria RFC; o QR vem de `segno`):

- **Quem ativou, é cobrado em todas as rotas**, inclusive `/admin/`: é middleware, não decorador — impossível esquecer uma view. Só ficam livres login, logout, as telas do 2FA, `/health/` e estáticos.
- Segredo nunca em log, auditoria ou URL; QR embutido na página. Código só vale uma vez (`last_used_step`) e tolera ±1 passo de 30 s.
- 5 tentativas erradas em 15 minutos bloqueiam (como o login); toda falha vai para `AuditEvent`.
- 10 códigos de recuperação de uso único, guardados só como HMAC. Gerar novos exige um código do aplicativo.
- Perdeu celular **e** códigos: outro `ADMIN` redefine pela tela de usuários (**Usuários e acessos**), ou `manage.py resetar_segundo_fator`. Ambos auditados; as sessões do usuário são encerradas.
- Com o 2FA ativo, a sessão de `ADMIN`/`FINANCEIRO` (`TWO_FACTOR_ROLES`) expira ao fechar o navegador.
- Não existe mais o interruptor `TWO_FACTOR_ENFORCED`. `manage.py conferir_segundo_fator` mostra a hora do servidor (os códigos dependem do relógio) e quem já usa.

### Autorização
Papel define a ação, `UserFarmAccess` define o alcance — [ADR 0003](../arquitetura/adr/0003-escopo-por-fazenda-desde-a-fase-0.md).

Duas regras que não se negociam:

1. **Nunca confiar em `is_staff`.** Permissão explícita sempre. Gerenciar usuários é do `ADMIN` ([regra 09](../regras-negocio/09-usuarios-e-solicitacao-de-acesso.md)).
2. **Registro fora do escopo devolve `404`, não `403`.** `403` confirma que o registro existe — vaza informação.

**Gestão de contas e pedido de acesso** ([regra 09](../regras-negocio/09-usuarios-e-solicitacao-de-acesso.md)): ninguém desativa, exclui ou rebaixa a si mesmo, nem o último administrador ativo; senha temporária obriga a troca e derruba as sessões; senha nunca vai por e-mail nem para a auditoria; a tela pública de pedido responde igual exista ou não conta com o e-mail (sem enumeração), com limite por IP, teto de avisos e campo-isca.

**Superusuário de suporte (oculto).** Conta de quem observa a produção e corrige bugs; criada só por linha de comando (`manage.py criar_superusuario_oculto <usuário>`; a senha é perguntada, ou vem de `DJANGO_SUPERUSER_PASSWORD` com `--noinput`). É `ADMIN` + `is_superuser`: acesso a todas as fazendas e a todas as telas (`User.has_broad_access`), segundo fator opcional, como para todos (ative na página Conta). **Invisível para os demais:** não sai na lista de usuários, no detalhe e nas ações (404), no filtro da auditoria, no admin do Django, nas exportações (`usuarios`, `acessos-por-fazenda`) nem como "outro usuário financeiro" que justificaria recusar uma baixa. Nos registros de auditoria aparece só como "Suporte Técnico" (o nome genérico é gravado pelo comando). A auditoria dele segue imutável, como a de todos. Ele conta como administrador na regra "nunca o último administrador". Código: `accounts.selectors.usuarios_visiveis`.

### Entrada
Validação no servidor sempre, no cliente só para experiência · ORM com queries parametrizadas, nunca SQL montado por concatenação · CSRF em todo POST, sem exceção · autoescape do Django ligado, `|safe` só em conteúdo que o sistema gerou.

### Arquivos
Extensão e MIME validados · tamanho limitado (10 MB anexo, 50 MB planilha) · nome interno gerado, **jamais o nome enviado pelo usuário** como caminho · servidos por view que checa autorização, nunca por URL pública · nunca executados.

**Arquivos de exportação** ([regra 10](../regras-negocio/10-exportacao-de-dados.md)): gerados fora do navegador (Celery), no escopo de quem pediu e **conferido de novo ao executar**; só o dono baixa (outro usuário, inclusive o `ADMIN`, recebe 404); `attachment` com `Cache-Control: no-store`; expiram em 7 dias e o dono pode apagá-los antes; senha, segredo do 2FA e códigos de recuperação não existem no catálogo; um teste barra modelo novo sem decisão de escopo e permissão; o pedido e cada download vão para a auditoria, o conteúdo nunca.

### Banco
Constraints como último guardião: FK, `UNIQUE`, `CHECK`, `NOT NULL`.
`transaction.atomic()` e `select_for_update()` nas operações críticas: confirmar compra, confirmar venda, gerar título, dar baixa, importar.

## Proteção contra mau uso

Tão importante quanto a proteção contra ataque.

| Risco | Controle |
|---|---|
| Clique duplo duplica lançamento | `select_for_update` + verificação de estado dentro da transação |
| Edição ou exclusão indevida | Motivo obrigatório + análise de impacto + auditoria imutável |
| Saldo de rebanho impossível | Invariante de saldo não negativo, verificada sob trava |
| Pagamento duplicado | Chave de idempotência por operação |
| Importar a mesma planilha duas vezes | `file_hash` no `ImportBatch` |
| Exclusão acidental | Exclusão é lógica e restaurável; `DELETE` físico não existe em nenhum caminho de código |
| Aprovação indevida | Permissão específica + auditoria + linha do tempo visível |

Ação destrutiva sempre informa o impacto antes:

> **Excluir esta compra vai:**
> · retirar 126 cabeças do lote LT-SFR-014
> · desfazer R$ 388.080,00 em DESPESA GADO
>
> Informe o motivo: [_________]

## Auditoria

Como **toda ação é editável e excluível** ([regras-negocio/06](../regras-negocio/06-edicao-exclusao-e-auditoria.md)), a auditoria deixa de ser registro complementar e passa a ser **a única garantia de que o histórico é verdadeiro**. Ela precisa ser mais forte que os dados que protege.

Duas coisas distintas:

**`AuditEvent`** — trilha técnica. `timestamp`, `actor`, `action`, `entity_type`, `entity_id`, `before`, `after`, `changed_fields`, `reason`, `cascade_root`, `ip_address`, `user_agent`, `request_id`. Gravada no servidor, na **mesma transação** da ação, **nunca** dependente do front-end.

**`OperationEvent`** — linha do tempo que o usuário lê. "Compra confirmada", "150 cabeças transferidas para o Baixão".

### Imutável, inclusive para o administrador

Quatro camadas, porque uma só não basta:

1. Sem tela de edição ou exclusão de evento — nem no admin do Django
2. Sem método de serviço que altere ou remova evento
3. **No banco, o papel da aplicação tem apenas `INSERT` e `SELECT` na tabela** — sem `UPDATE`, sem `DELETE`
4. Teste que garante a inexistência de qualquer caminho de escrita

> O administrador pode apagar qualquer dado de negócio do sistema. **Não pode apagar o registro de que apagou.**

Eventos nunca são expurgados. Se a tabela crescer, particiona-se por ano.

### Console de auditoria — Fase 0

Registro que ninguém lê não protege. O console entra junto com a fundação, não como tela adiada.

Para `ADMIN` (configurável para incluir `GESTOR`): filtro por usuário, ação, entidade, período e IP · diff campo a campo do `before`/`after` · agrupamento de exclusão em cascata por `cascade_root` · **restaurar a partir do evento** · exportação CSV · linha do tempo de um registro específico.

### Auditar obrigatoriamente

Login, logout e falha de autenticação · criação, **edição, exclusão e restauração** · confirmação e aprovação · movimentação de rebanho · lançamento e alteração de custo · **alteração de dado bancário** (severidade alta) · geração de documento · importação · mudança de permissão ou de escopo · reabertura de safra · exportação de dado em massa.

**Motivo é obrigatório** em toda edição e exclusão de registro confirmado. Sem motivo, a operação é recusada — é o que torna a auditoria legível meses depois.

## Segredos

Nunca no Git: `.env`, senha, `SECRET_KEY`, chave de API, credencial bancária, dump de banco.

`.gitignore` cobre. Confirmar com `git status` antes do primeiro commit — e considerar um hook de pre-commit varrendo padrão de segredo.

Nunca em log: senha, token, `SECRET_KEY`, segredo de 2FA, dado bancário completo, CPF/CNPJ integral. Filtro no formatter, não na lembrança de quem escreve.

Nunca em URL: token, identificador de sessão, dado sensível. URL vai para log de acesso, histórico do navegador e `Referer`.

## Erros

Usuário nunca vê traceback. Erro inesperado mostra:

> Ocorreu um erro inesperado.
> Código de referência: **ABC-123456**

O código vai junto no log e no Sentry, e liga o relato do usuário ao erro real.

Quatro tipos, tratados diferente: erro de validação (campo destacado), erro de negócio (mensagem clara — *"Saldo insuficiente: há 12 cabeças…"*), erro de permissão (`404` fora de escopo, `403` dentro), erro inesperado (código de referência).

## Testes de segurança obrigatórios

Não é cobertura artificial — é a parte que protege dinheiro:

1. Usuário sem permissão recebe `403` na ação
2. Usuário fora do escopo recebe `404` no registro de outra fazenda
3. Usuário inativo não autentica
4. POST sem CSRF é recusado
5. Anexo só é baixado por quem tem acesso à entidade
6. Login em excesso é bloqueado por rate limit
7. Alteração de dado bancário gera `AuditEvent`
8. Confirmação concorrente da mesma compra cria **um** movimento, não dois
9. Venda maior que o saldo é recusada
10. Importação do mesmo arquivo duas vezes é detectada
11. **Não existe caminho de código que altere ou apague um `AuditEvent`**
12. Edição ou exclusão sem motivo é recusada
13. Exclusão em cascata desfaz tudo ou nada — falha no meio não deixa resíduo
14. Usuário sem permissão não exclui registro confirmado

## LGPD

Há CPF, endereço, telefone e dado bancário de terceiros. Sistema interno, mas a lei vale.

O **CPF do usuário** (página Conta) é opcional, só dígitos, único por conta, visível inteiro só para o dono e **mascarado na auditoria**; não entra na exportação de usuários. A data de nascimento segue o mesmo cuidado (só o dono edita; vai para a auditoria como data).

Mínimo: coletar só o necessário · acesso restrito por papel e escopo · auditar quem consultou dado bancário · backup também protegido · exclusão a pedido do titular, quando não houver obrigação legal de retenção.
