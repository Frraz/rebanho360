# Usuários e solicitação de acesso

Quem entra no sistema, com que papel e em quais fazendas — e como uma pessoa nova chega até aí. Aplica a regra 5 do projeto (tudo editável, excluível e auditado) à conta de usuário. Código em `apps/accounts` (`user_management.py`, `access_requests.py`, `emails.py`, `user_views.py`).

Tela: **Sistema → Usuários e acessos** (`/contas/usuarios/`), só para `ADMIN` (e superusuário). `is_staff` sozinho não basta.

---

## O que o administrador faz

| Ação | O que acontece | Trava |
|---|---|---|
| **Criar** | Cadastra nome, e-mail, telefone, papel e fazendas. Dois jeitos de dar o primeiro acesso: **convite por e-mail** (a pessoa define a própria senha) ou **senha temporária** (o administrador repassa; a pessoa é obrigada a trocar ao entrar) | Sem e-mail, só senha temporária. Papel sem acesso amplo exige ao menos uma fazenda |
| **Editar** | Nome, e-mail, telefone, papel, fazendas (por fazenda: *só consulta* ou *consulta e lançamento*) | **Motivo obrigatório**. O `username` não muda. Não muda o próprio papel |
| **Redefinir senha** | Link por e-mail, ou senha temporária (derruba as sessões abertas dele) | Nunca a própria — para isso há a seção *Senha* da [Conta](#conta-o-próprio-usuário) |
| **Encerrar sessões** | Derruba as sessões abertas; a conta segue ativa | — |
| **Redefinir segundo fator** | Apaga aplicativo e códigos; ele volta a entrar só com a senha e pode ativar de novo | Nunca o próprio |
| **Desativar / Reativar** | Bloqueia/devolve o login; desativar derruba as sessões | Nunca a própria conta; nunca o último administrador ativo |
| **Excluir / Restaurar** | **Exclusão lógica**: sai da lista e do login, nada sai do banco; o e-mail fica livre. Restaurar devolve a conta **desativada**, para conferir antes de reativar | Nunca a própria conta; nunca o último administrador ativo. Restaurar falha se o e-mail já é de outra conta |

Toda ação mostra **o que vai acontecer** antes de confirmar e **explica o bloqueio** (com o caminho) em vez de só recusar. Toda ação vai para a auditoria com antes/depois e motivo. **Senha nunca vai para a auditoria** — nem o hash.

Papel de acesso amplo (`ADMIN`, `GESTOR`) não guarda linha de fazenda: vê todas por definição (ADR 0003).

---

## Conta: o próprio usuário

Menu do avatar → **Conta** (`/contas/conta/`, `accounts:conta`). Qualquer papel, sempre o próprio registro (a URL não tem id, então não há como abrir a conta de outro). Fica atrás do segundo fator e da troca obrigatória de senha, como o resto do sistema.

| Seção | O que o usuário faz | Regra |
|---|---|---|
| **Perfil** | Nome, sobrenome, telefone, data de nascimento e **CPF (opcional)** | Lista fechada no serviço (`CAMPOS_DA_PROPRIA_CONTA`): `role`, `email`, `username` e situação **não** mudam por aqui, nem com POST adulterado. Sem motivo (é a pessoa cuidando dos próprios dados), mas **audita antes/depois** com ela como autora, e só se algo mudou |
| **Senha** | Senha atual + nova (validadores do projeto) | A troca **é auditada** (`changed_fields = ["password"]`, nunca o valor nem o hash) e encerra as outras sessões. A troca obrigatória (senha temporária) segue com tela própria, sem menu |
| **Segundo fator** | Vê o estado, ativa e gera novos códigos de recuperação | Ativar e regenerar seguem as telas e regras do 2FA (código do aplicativo para regenerar) |

- **CPF:** só dígitos no banco; confere os dígitos verificadores e rejeita sequência repetida; **um CPF, uma conta** (constraint parcial que ignora o vazio e o excluído). Na auditoria entra **mascarado** (`***.***.***-25`). Só o dono o vê inteiro; não vai para a exportação nem para a tela do administrador.
- **E-mail é somente leitura** para o próprio usuário: é por ele que a senha se recupera, então a troca passa pelo administrador (pendência [#46](99-pendencias.md#46--troca-de-e-mail-pelo-próprio-usuário-fase-0)).
- Código: `ContaView` e `PasswordChangeView` em `views.py`, `ContaForm` em `forms.py`, `atualizar_propria_conta` e `auditar_troca_de_senha` em `user_management.py`, `validar_cpf` em `apps/core/validators.py`.

---

## Pedido de acesso (tela pública)

`/contas/solicitar-acesso/`, com link na tela de entrada. Quem ainda não tem conta informa **nome completo, e-mail, telefone (opcional) e quem é / por que precisa de acesso**. Não escolhe papel, fazenda, usuário nem senha.

1. O pedido nasce **Pendente** (`AccessRequest`) e fica na aba **Solicitações de acesso**, com contagem no menu e na aba.
2. Os administradores ativos com e-mail cadastrado recebem um e-mail com os dados e o link da tela. `ACCESS_REQUEST_NOTIFY_EMAILS` (no `.env`) acrescenta destinatários.
3. O administrador **aprova** — escolhe usuário (sugerido a partir do e-mail), papel e fazendas — ou **recusa**, com motivo.
4. **Aprovar** cria a conta **sem senha** e envia ao e-mail do pedido a confirmação: usuário, papel e o link para **definir a senha** (vale 3 dias, uma vez). **Recusar** avisa por e-mail se o administrador deixar marcado, **sem o motivo** (anotação interna).

O e-mail da conta é sempre o do pedido: é para ele que o link vai, e só o dono do e-mail consegue definir a senha — é assim que o endereço é confirmado. O pedido nunca é apagado.

### Defesas da tela pública

- Resposta **igual** exista ou não conta com o e-mail, e haja ou não pedido pendente: não dá para descobrir quem tem acesso.
- Um pedido pendente por e-mail (constraint no banco, sem diferenciar maiúsculas). Quem foi recusado pode pedir de novo.
- **5 pedidos por hora por IP**; passou disso, `429`.
- **Teto de 20 avisos por e-mail por hora**: acima disso o pedido é gravado e aparece na tela, só o e-mail é suprimido — um enxame de pedidos não vira enxurrada na caixa dos administradores.
- Campo-isca invisível para robôs (responde sucesso e não grava), CSRF obrigatório, assunto do e-mail sem quebra de linha (sem injeção de cabeçalho).
- Duas pessoas decidindo o mesmo pedido: a segunda recebe o que a primeira fez, em vez de criar duas contas.

---

## E-mail

Envio pela fila (Celery), **só depois do commit**; se o broker estiver fora, tenta na hora; se também falhar, vai para o log. Falha de e-mail nunca desfaz a ação nem perde o pedido. **Nunca vai senha por e-mail.** Configuração: `EMAIL_*`, `DEFAULT_FROM_EMAIL` e `ACCESS_REQUEST_NOTIFY_EMAILS` no `.env`; em desenvolvimento os e-mails saem no console do contêiner `web`.

---

## Integridade (banco)

- `uniq_user_email_ci`: um e-mail por conta, sem diferenciar maiúsculas, ignorando conta sem e-mail e conta excluída.
- `uniq_pending_access_request_email`: um pedido pendente por e-mail.
- `access_request_decision_matches_status`: pedido decidido tem data de decisão; pendente não tem.
- O último administrador ativo é protegido com `select_for_update` nos administradores antes de contar: duas desativações simultâneas não passam juntas.

Pendências deste módulo: [#41](99-pendencias.md#41--quem-aprova-os-pedidos-de-acesso-e-quem-é-avisado-fase-0), [#42](99-pendencias.md#42--o-que-o-pedido-de-acesso-deve-conter-e-como-confirmar-quem-pede-fase-0) e [#43](99-pendencias.md#43--exclusão-de-usuário-e-senha-temporária-fase-0).
