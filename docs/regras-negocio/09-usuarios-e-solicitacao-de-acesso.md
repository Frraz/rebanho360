# Usuários e solicitação de acesso

Quem entra no sistema, com que papel e em quais fazendas — e como uma pessoa nova chega até aí. Aplica a regra 5 do projeto (tudo editável, excluível e auditado) à conta de usuário. Código em `apps/accounts` (`user_management.py`, `access_requests.py`, `emails.py`, `user_views.py`).

Tela: **Sistema → Usuários e acessos** (`/contas/usuarios/`), só para `ADMIN` (e superusuário). `is_staff` sozinho não basta.

---

## O que o administrador faz

| Ação | O que acontece | Trava |
|---|---|---|
| **Criar** | Cadastra nome, e-mail, telefone, papel e fazendas. Dois jeitos de dar o primeiro acesso: **convite por e-mail** (a pessoa define a própria senha) ou **senha temporária** (o administrador repassa; a pessoa é obrigada a trocar ao entrar) | **E-mail obrigatório** para todo usuário (cliente, 2026-10-03): identifica a conta — dá para entrar por usuário **ou** e-mail —, recebe o convite e redefine a senha. Papel sem acesso amplo exige ao menos uma fazenda |
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
| **Aparência** | Escolhe o tema **Claro** ou **Escuro** da própria interface | Preferência **por usuário**, gravada no cadastro (`User.theme`, padrão `light`) e válida em qualquer aparelho. **Só existe aqui**: nenhum alternador no cabeçalho nem nas telas de trabalho. Ao escolher, a tela já mostra a prévia (Alpine, só troca o `data-theme`); só **Salvar aparência** grava (`TemaView`, POST `accounts:tema`, `definir_tema`). Valor fora de `light`/`dark` é recusado. **Sem auditoria**: é preferência, não dado de negócio. Um cookie (`r360_tema`, `HttpOnly`, `SameSite=Lax`) guarda o último tema do navegador só para a tela de entrar, que não sabe quem é o usuário; o `TemaCookieMiddleware` o mantém igual ao do usuário logado. Detalhes visuais: [design system, seção 14](../ux/02-design-system.md#14-tema-escuro) |
| **Senha** | Senha atual + nova (validadores do projeto) | A troca **é auditada** (`changed_fields = ["password"]`, nunca o valor nem o hash) e encerra as outras sessões e **revoga os outros dispositivos confiáveis**. A troca obrigatória (senha temporária) segue com tela própria, sem menu |
| **Segundo fator** | Vê o estado, ativa, gera novos códigos de recuperação, vê e **revoga os dispositivos confiáveis** (um ou todos) e **desativa** | Ativar e regenerar seguem as telas e regras do 2FA (código do aplicativo para regenerar). **Desativar** (`two_factor.desativar_segundo_fator`) exige **a senha e um código** do aplicativo (ou de recuperação) — quem deixou a sessão aberta não tira a proteção; apaga aplicativo e códigos, **revoga os dispositivos confiáveis**, audita (`TOTPDevice`, "Segundo fator desativado pelo próprio usuário") e **mantém a sessão** de quem pediu. Erro conta para o limite de 5 tentativas em 15 min. Não se oferece (nem se aceita) com `TWO_FACTOR_OBRIGATORIO` ligado. A lista de dispositivos mostra navegador, último uso, último IP e validade, e avisa quando o IP mudou ([ADR 0009](../arquitetura/adr/0009-dispositivo-confiavel-2fa.md)) |

- **CPF:** só dígitos no banco; confere os dígitos verificadores e rejeita sequência repetida; **um CPF, uma conta** (constraint parcial que ignora o vazio e o excluído). Na auditoria entra **mascarado** (`***.***.***-25`). Só o dono o vê inteiro; não vai para a exportação nem para a tela do administrador.
- **E-mail é somente leitura** para o próprio usuário: é por ele que a senha se recupera, então a troca passa pelo administrador (pendência [#46](99-pendencias-resolvidas.md#46--troca-de-e-mail-pelo-próprio-usuário-fase-0)).
- **Organização da tela:** cinco blocos (`.form-section`: título e explicação à esquerda, cartões à direita), com atalhos no topo — **Perfil** (identidade e acesso, somente leitura), **Dados pessoais**, **Aparência**, **Senha** e **Segundo fator** (códigos de recuperação, dispositivos confiáveis e, por último, *Desativar*, recolhido e com o que vai acontecer escrito antes do botão).
- Código: `ContaView`, `TemaView`, `PasswordChangeView` e `DesativarSegundoFatorView` em `views.py`, `ContaForm` em `forms.py`, `atualizar_propria_conta`, `definir_tema` e `auditar_troca_de_senha` em `user_management.py`, `tema_da_interface` em `apps/core/context_processors.py`, `validar_cpf` em `apps/core/validators.py`.

---

## Pedido de acesso (tela pública)

`/contas/solicitar-acesso/`, com link na tela de entrada. Quem ainda não tem conta informa **nome completo, e-mail, telefone (opcional) e quem é / por que precisa de acesso**. Não escolhe papel, fazenda, usuário nem senha.

1. O pedido nasce **Pendente** (`AccessRequest`) e fica na aba **Solicitações de acesso**, com contagem no menu e na aba.
2. Os administradores **e gestores** ativos com e-mail cadastrado recebem um e-mail com os dados e o link da tela. `ACCESS_REQUEST_NOTIFY_EMAILS` (no `.env`) acrescenta destinatários.
3. Um **administrador ou gestor** **aprova** — escolhe usuário (sugerido a partir do e-mail), papel e fazendas — ou **recusa**, com motivo. O gestor não concede o papel de Administrador, e a lista de usuários segue só do administrador.
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

**O pedido de acesso fica como está** (decisão de Warley, 2026-10-03, [#42](99-pendencias-resolvidas.md#42--o-que-o-pedido-de-acesso-deve-conter-e-como-confirmar-quem-pede-fase-0)): nome, e-mail, telefone opcional e texto livre; quem pede é confirmado pelo e-mail e pelo nome. O sistema é privado e não é indexado em buscadores — só quem foi autorizado conhece o endereço e pode pedir acesso. Sem restrição de domínio e sem CAPTCHA.

Pendências deste módulo (todas respondidas): [#41](99-pendencias-resolvidas.md#41--quem-aprova-os-pedidos-de-acesso-e-quem-é-avisado-fase-0), [#42](99-pendencias-resolvidas.md#42--o-que-o-pedido-de-acesso-deve-conter-e-como-confirmar-quem-pede-fase-0) e [#43](99-pendencias-resolvidas.md#43--exclusão-de-usuário-e-senha-temporária-fase-0).
