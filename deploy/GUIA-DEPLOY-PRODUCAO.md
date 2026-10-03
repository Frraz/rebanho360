# Guia de deploy em produção — do zero

Passo a passo para colocar o Rebanho360 no ar num **VPS Ubuntu compartilhado**, partindo de um servidor sem o sistema: entrar por SSH, baixar o código do GitHub, configurar, subir, ligar o HTTPS, criar o primeiro acesso e deixar o backup rodando.

> **Como usar este guia.** Siga na ordem. Cada etapa termina com um bloco **✔ Confere se** — só avance quando ele estiver verdadeiro.

### Valores deste deploy (demonstração)

O guia já está preenchido com os valores reais do VPS onde o sistema roda. Para outro servidor, troque estes:

| O quê | Valor |
|---|---|
| Domínio | `rebanho360-demo.ferzion.com.br` |
| IP do VPS | `147.93.15.214` |
| Usuário SSH | `deploy` |
| Pasta do projeto | `/var/www/docker-instances/rebanho360` |
| Porta local do `web` | `8013` — a `8010` (padrão) já é do `agi_nginx`. Vem de `WEB_HOST_PORT` no `.env` |

No VPS há **vários outros sistemas** (agi, byakugan, escolar, rh, safralog, ontime, fretes, conftech…) e até um Rebanho antigo (`rebanho_web`, `rebanho_db`, vhost `rebanho`, porta 8080). **Nada disso é nosso**: os nomes do Rebanho360 sempre levam o prefixo `rebanho360_`, que não colide com `rebanho_`.

**Tempo estimado:** 1,5 a 3 horas (a maior parte é DNS, certificado e e-mail).

**Documentos relacionados:** [docs/arquitetura/02-infra-e-deploy.md](../docs/arquitetura/02-infra-e-deploy.md) (a arquitetura e o porquê) · [nginx.conf.example](nginx.conf.example) · [firewall.md](firewall.md) · [restore-log.md](restore-log.md).

---

## Sumário

0. [O que você vai ter no final](#0-o-que-você-vai-ter-no-final)
1. [Antes de começar](#1-antes-de-começar)
2. [Preparar o VPS](#2-preparar-o-vps)
3. [Baixar o código do GitHub](#3-baixar-o-código-do-github)
4. [Criar o `.env` de produção](#4-criar-o-env-de-produção)
5. [Pastas do host](#5-pastas-do-host)
6. [Primeiro deploy](#6-primeiro-deploy)
7. [Nginx e HTTPS](#7-nginx-e-https)
8. [Primeiro acesso e dados iniciais](#8-primeiro-acesso-e-dados-iniciais)
9. [Verificação final](#9-verificação-final)
10. [Backup automático e restauração](#10-backup-automático-e-restauração)
11. [Ligar o HSTS](#11-ligar-o-hsts)
12. [Rotina: atualizar, reverter, olhar logs](#12-rotina-atualizar-reverter-olhar-logs)
13. [Solução de problemas](#13-solução-de-problemas)
14. [Lacunas conhecidas](#14-lacunas-conhecidas)
15. [Checklist final](#15-checklist-final)

---

## 0. O que você vai ter no final

```
Internet ──443──► Nginx do host (já existe, compartilhado)
                     ├── /static/  → pasta do host  (/var/www/rebanho360/static)
                     └── tudo mais → 127.0.0.1:8013
                                         │
                       ┌─────────────────┴─────────────────────┐
                       │ Docker Compose (docker-compose.prod)  │
                       │  web (Gunicorn) · worker · beat       │
                       │  db (Postgres 16) · redis             │
                       └───────────────────────────────────────┘
```

Regras que valem o tempo todo (o VPS é **compartilhado** com outros sistemas):

- Só o `web` publica porta, e **só em `127.0.0.1:8013`** (porta definida por `WEB_HOST_PORT` no `.env`; o padrão do compose é 8010). Postgres e Redis não têm porta publicada.
- **Não altere** vhosts, containers, volumes ou regras de firewall de outros sistemas.
- Tudo nosso tem prefixo `rebanho360_`.
- **Nunca rode `docker compose down -v`** nem `docker volume prune`: apagam o banco.

---

## 1. Antes de começar

Reúna estes itens. Sem eles o deploy trava no meio.

| Item | Para quê | Observação |
|---|---|---|
| Acesso SSH ao VPS com um usuário `sudo` | Tudo | Prefira chave SSH; senha desabilitada |
| **Domínio ou subdomínio** | HTTPS e `ALLOWED_HOSTS` | `rebanho360-demo.ferzion.com.br` |
| Acesso ao **DNS** do domínio | Apontar para o VPS | Registro `A` (e `AAAA` se o VPS tiver IPv6) |
| Conta de **e-mail SMTP** | Convites, redefinição de senha, aviso de pedido de acesso | Precisa de **STARTTLS na porta 587** (ver [4.2](#42-e-mail-smtp)) |
| Destino de **backup fora do VPS** | Backup de verdade | Backblaze B2, S3, Google Drive etc., via `rclone` |
| Acesso ao repositório do GitHub | `git clone` | O repositório é **privado** → precisa de *deploy key* (etapa 3). **Neste VPS o clone já existe e o `git pull` funciona** |
| Um **gerenciador de senhas** | Guardar `.env`, senhas e códigos de recuperação | O `.env` **não** está no Git; se o servidor morrer, ele se perde |

### Requisitos do servidor

- Ubuntu 22.04 ou 24.04, arquitetura `x86_64` ou `aarch64` (o build do Tailwind só conhece essas duas).
- **Memória:** os limites do compose somam ~2,8 GB (web 768M + worker 512M + beat 256M + db 1G + redis 256M). Com os outros sistemas do VPS, o ideal é **4 GB ou mais** livres. Confira com `free -h`.
  - *Neste VPS (7,8 GB; ~3,9 GB em uso pelos outros sistemas; 2 GB de swap) cabe, mas sem folga: acompanhe `docker stats` e `free -h` nas primeiras semanas.*
- **Disco:** pelo menos 10 GB livres para imagens, banco e backups.
- **Saída para a internet** durante o build: a imagem baixa o Tailwind do GitHub e as dependências do PyPI/apt.

---

## 2. Preparar o VPS

### 2.1 Entrar e atualizar

```bash
ssh deploy@147.93.15.214

sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ca-certificates ufw
```

> Em VPS compartilhado, se `apt upgrade` pedir para reiniciar serviços ou o kernel, combine a janela com quem usa os outros sistemas.

### 2.2 Relógio sincronizado (obrigatório para o 2FA)

Os códigos do aplicativo autenticador dependem da hora do servidor.

```bash
timedatectl
```

Precisa mostrar `System clock synchronized: yes` e `NTP service: active`. Se não:

```bash
sudo timedatectl set-ntp true
```

### 2.3 Docker e Compose

Verifique o que já existe (o VPS já hospeda outros sistemas, então provavelmente já há Docker):

```bash
docker --version
docker compose version        # Compose v2 ou superior (aqui: Docker 29.8.2, Compose v5.6.0)
```

**Se não estiverem instalados**, use o repositório oficial da Docker:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

**Seu usuário precisa poder falar com o Docker sem `sudo`** — os scripts de `deploy/` assumem isso (e o cron do backup também):

```bash
sudo usermod -aG docker $USER
# saia e entre de novo no SSH para o grupo valer:
exit
ssh deploy@147.93.15.214
docker ps        # tem que funcionar sem sudo
```

### 2.4 Conhecer o que já roda no servidor (sem mexer)

Antes de subir qualquer coisa, olhe o terreno:

```bash
docker ps                                   # containers dos outros sistemas
sudo ss -ltnp                               # portas em uso
sudo ss -ltnp | grep -E ':8013\b' || echo "8013 livre"
sudo nginx -v && ls /etc/nginx/sites-enabled /etc/nginx/conf.d
sudo ufw status verbose
df -h /                                     # espaço em disco
free -h                                     # memória
```

- **Porta ocupada?** O padrão do compose é `8010`, e **neste VPS ela já é do `agi_nginx`** (`0.0.0.0:8010`). Em uso aqui: 3000, 8001–8007, 8010–8012, 8080, 8110, 8120, 9000. Usamos a **`8013`**, que estava livre. Para outra porta, mude em **dois** lugares: `WEB_HOST_PORT` no `.env` (ver [4.3](#43-editar-o-env)) e o `proxy_pass` do vhost do Nginx. O `docker-compose.prod.yml` e o `healthcheck.sh` leem a porta do `.env` — **não edite arquivos do projeto no servidor**.
- **Nginx não existe?** O guia assume o Nginx do host. Instale com `sudo apt install -y nginx` (e só nesse caso).

### 2.5 Firewall

Estado esperado ([firewall.md](firewall.md)): **22, 80 e 443** — nada mais.

```bash
sudo ufw status verbose
```

- Se o `ufw` já está ativo com 22/80/443: não faça nada.
- Se está **inativo** e o VPS é só seu, ative **liberando o SSH antes**, senão você se tranca para fora:

  ```bash
  sudo ufw allow 22/tcp
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
  sudo ufw enable
  ```

- Se o VPS tem outros sistemas que usam outras portas, **não habilite o ufw às cegas**: liste o que está em uso (`ss -ltnp`) e combine antes.
- **Neste VPS** o `ufw` estava inativo e foi ativado com 22/80/443 (em 2026-10-03). Efeitos a conferir logo depois — o servidor é compartilhado:
  - **Abra os outros sistemas** no navegador (agi, byakugan, escolar, rh, safralog…) e confirme que seguem no ar. Containers que falam com serviços do host por IP/porta podem ser barrados.
  - A porta **3000** (`next-server`, escuta em `*:3000`) deixou de ser acessível de fora. Se alguém a usava direto, em vez de pelo Nginx, deixou de funcionar.
  - Portas que o Docker publica em `0.0.0.0` (ex.: `agi_nginx` na 8010) **continuam abertas**: o Docker insere as próprias regras antes do `ufw`. O `ufw` não as protege.
- Registre qualquer mudança na tabela de histórico de [firewall.md](firewall.md).

> Postgres (5432) e Redis (6379) não precisam de regra: não estão publicados. A porta 8013 está presa a `127.0.0.1`, então também não é alcançável de fora (o Docker costuma furar o `ufw` em portas publicadas em `0.0.0.0`; por isso o bind em `127.0.0.1` é essencial — não o altere).

### 2.6 DNS

No painel do seu domínio, crie o registro apontando para o IP do VPS:

| Tipo | Nome | Valor |
|---|---|---|
| `A` | `rebanho360-demo` (em `ferzion.com.br`) | `147.93.15.214` |

Confira a propagação (pode levar de minutos a horas):

```bash
dig +short rebanho360-demo.ferzion.com.br      # tem que devolver 147.93.15.214
```

> ✔ **Confere se:** `docker ps` funciona sem sudo · `timedatectl` mostra relógio sincronizado · porta 8013 livre · o domínio resolve para o IP do VPS.

---

## 3. Baixar o código do GitHub

O repositório é **privado**, então o servidor precisa de uma credencial própria, **somente leitura**: uma *deploy key*.

### 3.1 Criar a deploy key no servidor

```bash
ssh-keygen -t ed25519 -C "deploy-rebanho360@vps" -f ~/.ssh/rebanho360_deploy -N ""
cat ~/.ssh/rebanho360_deploy.pub
```

No GitHub: repositório → **Settings → Deploy keys → Add deploy key** → cole a chave pública, dê um título (ex.: `vps-producao`) e **deixe "Allow write access" desmarcado**.

Diga ao SSH para usar essa chave com o GitHub:

```bash
cat >> ~/.ssh/config <<'EOF'

Host github-rebanho360
    HostName github.com
    User git
    IdentityFile ~/.ssh/rebanho360_deploy
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

ssh -T git@github-rebanho360
# 1ª vez pergunta se confia no host: digite "yes".
# Esperado: "Hi Frraz/rebanho360! You've successfully authenticated..."
```

### 3.2 Clonar

> **Neste VPS esta etapa já foi feita:** `/var/www/docker-instances/rebanho360` já é o clone (o `git pull` responde `Already up to date`). Pule para a 3.3. Os comandos abaixo valem para um servidor novo.

A pasta do projeto é **`/var/www/docker-instances/rebanho360`** (o nome da pasta importa — veja o aviso abaixo):

```bash
sudo mkdir -p /var/www/docker-instances/rebanho360
sudo chown $USER:$USER /var/www/docker-instances/rebanho360
git clone git@github-rebanho360:Frraz/rebanho360.git /var/www/docker-instances/rebanho360
cd /var/www/docker-instances/rebanho360
git log --oneline | head -3
git branch --show-current          # tem que ser "main"
```

> ⚠️ **Não renomeie nem mova a pasta depois.** O Docker Compose usa o nome da pasta como nome do projeto e prefixa os volumes com ele (`rebanho360_rebanho360_pgdata`; no clone, `ls` mostra a pasta chamada `rebanho360`, e é ela que dá o prefixo). Renomear a pasta faz o Compose criar volumes **novos e vazios**, e o sistema sobe com banco em branco. Os scripts de backup descobrem o volume pelo container, mas o banco em si fica atrelado a esse nome.

### 3.3 Um atalho importante

Na raiz do projeto há **dois** arquivos de Compose: `docker-compose.yml` (**desenvolvimento**, com bind mount e `runserver`) e `docker-compose.prod.yml` (**produção**). Um `docker compose up` sem `-f` sobe o de desenvolvimento — com `DEBUG`, código em bind mount e outro estágio do Dockerfile. Para nunca errar, crie um atalho:

```bash
echo "alias dc='docker compose -f docker-compose.prod.yml'" >> ~/.bashrc
source ~/.bashrc
cd /var/www/docker-instances/rebanho360 && dc ps        # lista vazia por enquanto: tudo bem
```

O resto do guia usa `dc` (sempre dentro de `/var/www/docker-instances/rebanho360`). Os scripts de `deploy/` já usam `-f docker-compose.prod.yml` por conta própria.

> ✔ **Confere se:** `git log` mostra os commits · `dc ps` roda sem erro.

---

## 4. Criar o `.env` de produção

O `.env` guarda segredos, **não está no Git** e precisa ser criado à mão no servidor.

```bash
cd /var/www/docker-instances/rebanho360
cp .env.example .env
chmod 600 .env
```

### 4.1 Gerar os segredos

```bash
# SECRET_KEY (100 caracteres hexadecimais)
openssl rand -hex 50

# Senha do Postgres (48 hex — sem caracteres especiais de propósito, ela vai dentro de uma URL)
openssl rand -hex 24
```

Guarde os dois no gerenciador de senhas **agora**.

> ⚠️ **A `DJANGO_SECRET_KEY` não pode mudar depois.** Trocar derruba todas as sessões, invalida os links de "definir senha" em circulação e **inutiliza os códigos de recuperação do 2FA** (são derivados dela). Faça backup do `.env` em local seguro.

### 4.2 E-mail SMTP

O sistema envia e-mail em convite de usuário, redefinição de senha e aviso de pedido de acesso. O envio usa **STARTTLS (`EMAIL_USE_TLS=True`)**, então:

- use a **porta 587** (padrão no `.env.example`);
- a **porta 465 (SSL direto) não funciona** com a configuração atual.

Sem SMTP o sistema funciona, mas só dá para criar usuário com **senha temporária** (o administrador repassa) e não chegam avisos.

### 4.3 Editar o `.env`

Abra com `nano .env` e preencha. **Substitua tudo que está em MAIÚSCULAS.**

```dotenv
# --- Django ---
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_SECRET_KEY=COLE_AQUI_O_HEX_DE_100_CARACTERES
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=rebanho360-demo.ferzion.com.br

# --- Banco ---
POSTGRES_DB=rebanho360
POSTGRES_USER=rebanho360
POSTGRES_PASSWORD=COLE_AQUI_A_SENHA_DO_POSTGRES
# A senha daqui TEM que ser a mesma de POSTGRES_PASSWORD. Host é "db" (nome do serviço).
DATABASE_URL=postgres://rebanho360:COLE_AQUI_A_SENHA_DO_POSTGRES@db:5432/rebanho360

# --- Redis ---
REDIS_URL=redis://redis:6379/0

# --- E-mail ---
EMAIL_HOST=smtp.seuprovedor.com
EMAIL_PORT=587
EMAIL_HOST_USER=usuario-smtp
EMAIL_HOST_PASSWORD=senha-smtp
DEFAULT_FROM_EMAIL=Rebanho360 <nao-responda@ferzion.com.br>
ACCESS_REQUEST_NOTIFY_EMAILS=

# --- Observabilidade (opcional) ---
SENTRY_DSN=

# --- HSTS: deixe 0 até confirmar o HTTPS (etapa 11) ---
DJANGO_HSTS_SECONDS=0

# --- Console de auditoria ---
AUDIT_CONSOLE_INCLUDE_GESTOR=False

# --- Scripts de deploy ---
# Porta local do web (o Nginx do host aponta para ela). A 8010 padrão já é do agi_nginx.
WEB_HOST_PORT=8013
STATIC_HOST_DIR=/var/www/rebanho360/static
# RCLONE_REMOTE=meu-remoto:bucket/rebanho360     (etapa 10)
# HEALTHCHECK_HOST=                              (padrão: o 1º de DJANGO_ALLOWED_HOSTS)

```

Pontos que mais dão erro:

| Variável | Regra |
|---|---|
| `DJANGO_DEBUG` | **`False`**. O `.env.example` vem com `True`; com `True` a aplicação **recusa subir** em produção |
| `DJANGO_ALLOWED_HOSTS` | Só o **domínio**, sem `https://` e sem `*` (com `*` ou vazio, a aplicação recusa subir). Vários domínios separados por vírgula; o **primeiro** é o que o `healthcheck.sh` usa |
| `DATABASE_URL` | Senha idêntica à de `POSTGRES_PASSWORD`; host `db`. Senha com `@ : / # %` quebra a URL — por isso o `openssl rand -hex` |
| `POSTGRES_PASSWORD` | **Só vale na primeira criação do volume do banco.** Mudar depois no `.env` não troca a senha do Postgres (ver [13](#13-solução-de-problemas)) |
| Senhas com `$`, `#` ou espaço (SMTP, por exemplo) | Coloque o valor entre **aspas simples**: `EMAIL_HOST_PASSWORD='abc$123'` |
| `WEB_HOST_PORT` | Porta livre no host (aqui `8013`). Tem que ser a **mesma** do `proxy_pass` no Nginx. Sem a variável, o compose usa 8010 |
| `DJANGO_HSTS_SECONDS` | `0` por enquanto |

Confira que não ficou nada vazio por esquecimento e que a permissão está certa:

```bash
grep -E '^(DJANGO_SECRET_KEY|POSTGRES_PASSWORD|DATABASE_URL|DJANGO_ALLOWED_HOSTS|DJANGO_DEBUG)=' .env | sed -E 's/(KEY|PASSWORD)=.*/\1=***/; s#://([^:]+):[^@]+@#://\1:***@#'
ls -l .env        # -rw------- (600)
```

> ✔ **Confere se:** `DJANGO_DEBUG=False` · `ALLOWED_HOSTS` é o domínio real · a senha do Postgres é a mesma nas duas linhas · `.env` com permissão `600`.

---

## 5. Pastas do host

Duas pastas fora do projeto — uma para os estáticos (o Nginx serve), outra para os backups. Ambas precisam existir **antes** do primeiro deploy.

```bash
# Estáticos (CSS, fontes, ícones) — mesmo caminho de STATIC_HOST_DIR no .env
sudo mkdir -p /var/www/rebanho360/static
sudo chown -R $USER:$USER /var/www/rebanho360

# Backups — o backup.sh grava aqui por padrão (/backups)
sudo mkdir -p /backups
sudo chown $USER:$USER /backups
chmod 700 /backups
```

> `/backups` guarda **todos os dados da fazenda** (dump do banco e anexos). Por isso `700`: só o seu usuário lê.

> ⚠️ O `backup.sh` lê `BACKUP_ROOT` só do **ambiente do shell**, não do `.env`. Se quiser outra pasta, defina `BACKUP_ROOT=/outra/pasta` no `crontab` (etapa 10) e ao rodar o script à mão. Sem isso ele usa `/backups`.

> ✔ **Confere se:** `ls -ld /var/www/rebanho360/static /backups` mostra o seu usuário como dono.

---

## 6. Primeiro deploy

Tudo pronto para subir. O script faz, nesta ordem: backup (ignorado no primeiro deploy, pois ainda não há banco) → `git pull` → build → `migrate` → `collectstatic` → copia os estáticos para o host → sobe `web worker beat` → healthcheck.

```bash
cd /var/www/docker-instances/rebanho360
./deploy/deploy.sh
```

Se der `Permission denied`: `chmod +x deploy/*.sh` (e confira com `git status` se isso virou alteração — não precisa commitar).

### O que esperar

| Passo | Saída | Observação |
|---|---|---|
| `1/6 Backup` | `Container rebanho360_db não está rodando ... Backup ignorado.` | **Normal** no primeiro deploy |
| `2/6 Código` | `Already up to date.` | |
| `3/6 Build` | Vários minutos | Baixa imagem do Python, dependências do sistema (WeasyPrint), pacotes pip e o Tailwind. Se falhar aqui, **nada foi alterado** |
| `4/6 Migrações e estáticos` | Lista `Applying ... OK` | Sobe o `db` e o `redis` como dependência. As migrações criam também as classes de carcaça, tributos e centros de custo |
| `4/6` (estáticos) | `Publicando estáticos em /var/www/rebanho360/static` | Se aparecer `AVISO: STATIC_HOST_DIR não definido`, volte ao `.env` |
| `5/6 Subindo` | `Started` ×3 | |
| `6/6 Healthcheck` | `Pronto após N tentativa(s): {"status": "ok", ...}` e `Deploy OK.` | |

> Se o healthcheck falhar no **primeiro** deploy, o script tenta o rollback e avisa `Nenhuma imagem 'rebanho360_web:previous'` — é esperado, não há versão anterior. Vá direto aos logs: `dc logs --tail=80 web`. Causas mais comuns: [seção 13](#13-solução-de-problemas).

### Conferir

```bash
dc ps                                   # db, redis, web, worker, beat: "Up"
curl -fsS -H "Host: rebanho360-demo.ferzion.com.br" -H "X-Forwarded-Proto: https" \
     http://127.0.0.1:8013/ready/
# → {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}
ls /var/www/rebanho360/static | head    # css, fonts, img, admin...
```

> ℹ️ **`web` aparecendo como `unhealthy` no `docker ps` é um defeito conhecido** do healthcheck embutido no compose (ver [seção 14](#14-lacunas-conhecidas)). O que vale é o `healthcheck.sh` e o `/ready/` acima. Se o `/ready/` responde `ok`, o sistema está saudável.

> ✔ **Confere se:** `Deploy OK.` apareceu · `/ready/` devolve `"status": "ok"` · há arquivos em `/var/www/rebanho360/static`.

---

## 7. Nginx e HTTPS

O sistema já está respondendo em `127.0.0.1:8013`. Agora o Nginx do host o expõe com HTTPS. **Não toque nos vhosts dos outros sistemas** — você só adiciona um arquivo novo.

Veja como os vhosts existentes estão organizados e **siga o mesmo padrão**:

```bash
ls /etc/nginx/sites-enabled /etc/nginx/conf.d
```

Os comandos abaixo usam `sites-available` + `sites-enabled` (padrão do Ubuntu). Se o servidor usa `conf.d/*.conf`, grave lá.

**Neste VPS** os vhosts estão em `/etc/nginx/sites-enabled/` (`conf.d/` está vazio), um arquivo por domínio (`rh-demo.ferzion.com.br`, `safralog.ferzion.com.br`…), e o nosso segue o padrão: `rebanho360-demo.ferzion.com.br`. Já existe um vhost `rebanho` (o sistema antigo, porta 8080): **não o toque**; só confirme que ele não declara o nosso `server_name`:

```bash
sudo grep -rn "rebanho360-demo" /etc/nginx/sites-enabled/ || echo "domínio livre no nginx"
```

### 7.1 Vhost provisório (só HTTP)

O vhost definitivo ([nginx.conf.example](nginx.conf.example)) referencia o certificado, que ainda não existe — então o `nginx -t` falharia. Primeiro suba um vhost mínimo só na porta 80, para o Certbot poder validar o domínio:

```bash
sudo tee /etc/nginx/sites-available/rebanho360-demo.ferzion.com.br > /dev/null <<'EOF'
server {
    listen 80;
    server_name rebanho360-demo.ferzion.com.br;
    location / { return 404; }
}
EOF
sudo ln -s /etc/nginx/sites-available/rebanho360-demo.ferzion.com.br /etc/nginx/sites-enabled/rebanho360-demo.ferzion.com.br
sudo nginx -t && sudo systemctl reload nginx
```

### 7.2 Certificado (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx     # se ainda não houver certbot
sudo certbot certonly --nginx -d rebanho360-demo.ferzion.com.br \
     -m seu-email@dominio.com --agree-tos --no-eff-email
```

O DNS (etapa 2.6) precisa estar apontando para o VPS, e as portas 80/443 abertas. Ao terminar, o certificado fica em `/etc/letsencrypt/live/rebanho360-demo.ferzion.com.br/`.

Confira a renovação automática:

```bash
systemctl list-timers | grep -i certbot       # tem que existir um timer ativo
sudo certbot renew --dry-run                  # simula a renovação
```

### 7.3 Vhost definitivo

Gere o vhost final a partir do exemplo do repositório, trocando o domínio **e a porta** (o exemplo usa 8010):

```bash
sudo sed -e 's/rebanho360\.exemplo\.com/rebanho360-demo.ferzion.com.br/g' \
         -e 's/127\.0\.0\.1:8010/127.0.0.1:8013/g' \
    /var/www/docker-instances/rebanho360/deploy/nginx.conf.example \
  | sudo tee /etc/nginx/sites-available/rebanho360-demo.ferzion.com.br > /dev/null

sudo nginx -t                  # tem que dizer "syntax is ok" e "test is successful"
sudo systemctl reload nginx
```

O que esse vhost faz — e não deve ser alterado sem entender:

- **`/static/`** vem da pasta do host (`/var/www/rebanho360/static/`, a mesma de `STATIC_HOST_DIR`). Sem isso a tela abre **sem estilo, fontes e ícones**.
- **Sem `/media/`**: anexos e PDFs só saem por view autenticada. Não crie essa rota.
- **`X-Forwarded-Proto $scheme`** é obrigatório: o Django só sabe que está em HTTPS por esse cabeçalho. Sem ele, o login entra em laço de redirecionamento.
- **`client_max_body_size 20m`**: limite de upload de planilhas/anexos.
- `/health/` e `/ready/` ficam fora do log de acesso.

> Em Nginx ≥ 1.25.1, `listen 443 ssl http2;` gera apenas um *warning* de depreciação. Se quiser silenciar: troque por `listen 443 ssl;` e adicione `http2 on;` dentro do bloco `server`.

### 7.4 Testar

```bash
curl -I http://rebanho360-demo.ferzion.com.br/             # 301 → https
curl -I https://rebanho360-demo.ferzion.com.br/contas/entrar/   # 200
curl -I https://rebanho360-demo.ferzion.com.br/static/css/output.css   # 200, content-type text/css
```

Abra `https://rebanho360-demo.ferzion.com.br/` no navegador **e no celular**. A tela de login precisa aparecer **com estilo, fontes e ícones**.

> ✔ **Confere se:** cadeado válido no navegador · tela de login estilizada · `output.css` responde 200 · os outros sistemas do VPS continuam abrindo normalmente.

---

## 8. Primeiro acesso e dados iniciais

> ⛔ **NUNCA rode `seed_demo` em produção.** Ele cria seis usuários (`admin@teste`, `gestor@teste`...) com a senha pública `demo12345`, uma empresa fictícia e fazendas de teste.

Banco recém-migrado tem: classes de carcaça, tipos de tributo, classes e centros de custo (vêm nas migrações). **Não tem** usuários, empresa, safra, fazendas, categorias nem raças — você cria agora.

### 8.1 Superusuário de suporte

```bash
cd /var/www/docker-instances/rebanho360
dc exec web python manage.py criar_superusuario_oculto SEU_USUARIO --email seu-email@dominio.com
```

Ele pede a senha duas vezes (mínimo de 10 caracteres, sem ser comum nem só números). Esse usuário:

- tem acesso a **tudo** (todas as fazendas) e **não aparece** para os outros usuários — nem em listas, filtros, exportações ou no admin;
- aparece na auditoria apenas como **"Suporte Técnico"**.

Use-o como conta de **suporte/emergência**, não como seu login do dia a dia (veja 8.3).

### 8.2 Entrar e ativar o segundo fator

1. Abra `https://rebanho360-demo.ferzion.com.br/contas/entrar/` e entre com o superusuário.
2. Menu do avatar → **Conta → Segundo fator** → ative, leia o QR no aplicativo autenticador e **guarde os códigos de recuperação** no gerenciador de senhas.

O 2FA é opcional, mas **altamente recomendado** a todos. Para conferir o relógio e ver quem já usa:

```bash
dc exec web python manage.py conferir_segundo_fator
```

### 8.3 Cadastros básicos (pela tela)

Logado como superusuário, crie **nesta ordem** (cada item depende do anterior):

| # | O quê | Onde |
|---|---|---|
| 1 | **Empresa** | Organização → Empresas (`/organizacao/empresas/nova/`) |
| 2 | **Unidade** de negócio | Organização → Unidades (`/organizacao/unidades/nova/`) |
| 3 | **Safra** (marque como atual) | Organização → Safras (`/organizacao/safras/nova/`) |
| 4 | **Fazendas** | Propriedades → Fazendas (`/propriedades/fazendas/nova/`) |
| 5 | **Categorias** de animal | Rebanho → Categorias (`/rebanho/categorias/`) |
| 6 | **Raça** | Rebanho → Raças (`/rebanho/racas/nova/`) |
| 7 | **Usuários** e acesso por fazenda | Sistema → Usuários e acessos (`/contas/usuarios/`) |

Pastos, lotes e parceiros podem vir depois, junto com a importação da planilha ([docs/migracao/01-planilhas-e-importacao.md](../docs/migracao/01-planilhas-e-importacao.md)).

**Atalho opcional para as categorias** — as 11 categorias do `seed_demo` (Bezerros Mamando … Tropa), sem criar mais nada do demo. Confirme com o produtor se é essa a lista antes de usar; ela se edita depois pela tela:

```bash
dc exec web python manage.py shell -c "
from apps.livestock.models import AnimalCategory, Breed
from apps.organizations.management.commands.seed_demo import CATEGORIES
for ordem, (nome, sexo, idade) in enumerate(CATEGORIES, start=1):
    AnimalCategory.objects.get_or_create(
        name=nome, defaults={'sex': sexo, 'age_order': idade, 'display_order': ordem})
Breed.objects.get_or_create(name='Nelore')
print(AnimalCategory.objects.count(), 'categorias;', Breed.objects.count(), 'raça(s)')
"
```

(Importar `CATEGORIES` só lê a lista — não executa o `seed_demo`.)

### 8.4 Criar os administradores de verdade

Em **Usuários e acessos → Novo usuário**, crie o seu usuário (papel `ADMIN`) e os dos demais. Dois jeitos de dar o primeiro acesso:

- **Convite por e-mail** — a pessoa recebe um link (vale 3 dias, uso único) para definir a própria senha. Exige SMTP funcionando.
- **Senha temporária** — você repassa; a pessoa é obrigada a trocar ao entrar.

Papéis sem acesso amplo (`ESCRITORIO`, `CAMPO`, `FINANCEIRO`, `CONSULTA`) precisam de **ao menos uma fazenda** vinculada. `ADMIN` e `GESTOR` veem todas por definição. Detalhes em [docs/regras-negocio/09-usuarios-e-solicitacao-de-acesso.md](../docs/regras-negocio/09-usuarios-e-solicitacao-de-acesso.md).

### 8.5 Testar o e-mail

Convide a si mesmo (ou rode abaixo) e confira que a mensagem chega:

```bash
dc exec web python manage.py shell -c "
from django.core.mail import send_mail
n = send_mail('Teste Rebanho360', 'Se você leu isto, o SMTP está funcionando.', None,
              ['seu-email@dominio.com'])
print('enviados:', n)
"
```

- `enviados: 1` e a mensagem chega → ok (olhe também o spam).
- Erro de conexão/autenticação → revise `EMAIL_*` no `.env`; depois aplique com `dc up -d --force-recreate web worker beat` (um `restart` simples **não** relê o `.env`).

> ✔ **Confere se:** você consegue entrar com o seu usuário `ADMIN` · o segundo fator foi ativado e os códigos de recuperação estão guardados · o e-mail de teste chegou · existem empresa, safra atual, fazendas e categorias.

---

## 9. Verificação final

Rode esta lista inteira antes de dar o sistema como entregue.

```bash
cd /var/www/docker-instances/rebanho360

# 1. Todos os containers de pé
dc ps

# 2. Saúde de verdade (banco + Redis)
./deploy/healthcheck.sh

# 3. Nada exposto além do necessário — só 127.0.0.1:8013 do projeto
docker ps --format '{{.Names}}\t{{.Ports}}' | grep rebanho360
sudo ss -ltnp | grep -E ':(5432|6379)\b' || echo "5432/6379 não expostos: OK"

# 4. Limites de memória em uso
docker stats --no-stream | grep rebanho360

# 5. Worker e beat funcionando
dc logs --tail=20 worker | grep -i "ready"
dc logs --tail=20 beat   | grep -i "beat: Starting"

# 6. Migrações todas aplicadas
dc exec web python manage.py showmigrations | grep -c '\[ \]' || true    # esperado: 0
```

No navegador (desktop **e celular de verdade**, com a conexão do campo se possível):

- [ ] `http://` redireciona para `https://`
- [ ] Login funciona; segundo fator pede o código
- [ ] Telas com estilo, fontes e ícones
- [ ] Dá para lançar algo (ex.: cadastrar uma fazenda de teste e excluí-la com motivo)
- [ ] Os outros sistemas do VPS continuam no ar

> ✔ **Confere se:** todos os itens acima estão ok.

---

## 10. Backup automático e restauração

> **Backup no mesmo VPS não é backup.** Se o disco morrer, o banco e a cópia vão juntos. A cópia **fora do VPS** é a que conta.

O `beat` do Celery **não** faz backup (ele só cuida da manutenção das exportações). O backup é o `deploy/backup.sh`, agendado no **cron do host**.

### 10.1 Cópia externa com rclone

```bash
sudo apt install -y rclone        # ou: curl https://rclone.org/install.sh | sudo bash
rclone config                     # crie um "remote" (ex.: nome "backup-b2")
rclone lsd backup-b2:             # teste: lista os buckets
```

Depois, no `.env`:

```dotenv
RCLONE_REMOTE=backup-b2:nome-do-bucket/rebanho360
```

> A configuração do `rclone` fica no `~/.config/rclone/` **do usuário que roda o cron** — configure com o mesmo usuário.
> O `backup.sh` envia mas **não apaga** nada no destino. Configure uma regra de retenção no próprio bucket (ex.: apagar após 90 dias) para o custo não crescer sem limite.

### 10.2 Rodar o primeiro backup à mão

```bash
cd /var/www/docker-instances/rebanho360
./deploy/backup.sh
ls -lh /backups/db /backups/media
rclone ls "$(grep ^RCLONE_REMOTE= .env | cut -d= -f2-)"     # o dump está lá fora?
```

Se aparecer `RCLONE_REMOTE não configurado — backup ficou só local`, o passo 10.1 não foi concluído.

### 10.3 Agendar (cron)

```bash
crontab -e
```

```cron
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Backup diário às 03:00 (horário do servidor)
0 3 * * * /var/www/docker-instances/rebanho360/deploy/backup.sh >> $HOME/rebanho360-backup.log 2>&1
```

Se usar outra pasta de backup: `0 3 * * * BACKUP_ROOT=/outra/pasta /var/www/docker-instances/rebanho360/deploy/backup.sh ...`.

Confira no dia seguinte: `tail -20 ~/rebanho360-backup.log` e se há um dump novo em `/backups/db/`.

Retenção local: o script apaga o que tem mais de 90 dias. O `deploy.sh` também roda um backup antes de cada atualização.

### 10.4 Restauração testada (mensal)

Backup nunca restaurado é hipótese. Faça **uma restauração de teste logo após o primeiro deploy** e depois todo mês, seguindo [restore-log.md](restore-log.md) (sobe um Postgres descartável, restaura o dump, roda [restore-check.sql](restore-check.sql) e compara com a produção). **Anote data, duração e resultado** na tabela do `restore-log.md` — o tempo é o número que importa num dia ruim.

> A seção 5 do `restore-check.sql` (transferências que não fecham em zero) tem que voltar **vazia**.

### 10.5 Restaurar em produção (desastre)

Só em emergência. Pare a aplicação para ninguém gravar durante a restauração:

```bash
cd /var/www/docker-instances/rebanho360
dc stop web worker beat

# Escolha o dump (use o mais recente que você confia)
DUMP=/backups/db/rebanho360_AAAAMMDD_HHMMSS.dump        # ou baixe do rclone

# Recria o banco vazio e restaura (ajuste usuário/banco se não forem os padrões)
dc exec -T db psql -U rebanho360 -d postgres -c "DROP DATABASE IF EXISTS rebanho360;"
dc exec -T db psql -U rebanho360 -d postgres -c "CREATE DATABASE rebanho360 OWNER rebanho360;"
dc exec -T db pg_restore -U rebanho360 -d rebanho360 --no-owner < "$DUMP"

dc up -d web worker beat
./deploy/healthcheck.sh
```

Anexos (media), se também se perderam:

```bash
MEDIA_VOLUME="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/media"}}{{.Name}}{{end}}{{end}}' rebanho360_web)"
docker run --rm -v "${MEDIA_VOLUME}:/data" -v /backups/media:/backup alpine \
  tar xzf /backup/media_AAAAMMDD_HHMMSS.tar.gz -C /data
```

Depois confira com `restore-check.sql` (rodando contra o banco de produção) e **registre o incidente**.

> O `DROP DATABASE` falha com "being accessed by other users" se algo ainda estiver conectado: confirme que `web`, `worker` e `beat` estão parados (`dc ps`).

> ✔ **Confere se:** existe dump em `/backups/db/` **e** cópia no destino externo · o cron está agendado · a primeira restauração de teste foi feita e anotada.

---

## 11. Ligar o HSTS

O HSTS manda o navegador **nunca mais** abrir o site por HTTP. Só ligue **depois** de confirmar que o HTTPS está estável (etapas 7 e 9) e **suba aos poucos**, pois um HSTS errado, depois de visto pelo navegador, não se desfaz rápido.

1. Primeiro, um valor curto (1 hora):

   ```bash
   cd /var/www/docker-instances/rebanho360
   sed -i 's/^DJANGO_HSTS_SECONDS=.*/DJANGO_HSTS_SECONDS=3600/' .env
   dc up -d --force-recreate web worker beat
   curl -sI https://rebanho360-demo.ferzion.com.br/contas/entrar/ | grep -i strict-transport
   # → strict-transport-security: max-age=3600; includeSubDomains; preload
   ```

2. Depois de alguns dias sem problema: `86400` (1 dia) → e por fim `31536000` (1 ano).

> Com HSTS ligado, o `includeSubDomains` vale para **subdomínios do `rebanho360-demo.ferzion.com.br`**, não para os outros subdomínios do seu domínio. Mesmo assim, não ligue se algum subdomínio abaixo dele precisar de HTTP.

---

## 12. Rotina: atualizar, reverter, olhar logs

### 12.1 Atualizar para uma versão nova

Você sobe a mudança para o GitHub (`main`) e, no VPS:

```bash
ssh deploy@147.93.15.214
cd /var/www/docker-instances/rebanho360
./deploy/deploy.sh
```

O script faz backup, `git pull --ff-only origin main`, build, migrações, estáticos, sobe e testa; se o healthcheck falhar, **volta sozinho** para a imagem anterior.

Regras:

- **Não edite arquivos dentro de `/var/www/docker-instances/rebanho360`.** Alteração local faz o `git pull --ff-only` recusar. Mudou algo à mão? `git status` e `git diff` para ver; `git checkout -- arquivo` descarta.
- O `deploy.sh` puxa a branch **`main`**.
- Migração destrutiva (apaga coluna/tabela) exige janela combinada e backup recente.
- Leia o que mudou antes: `git fetch && git log --oneline HEAD..origin/main`.
- Variável nova no `.env.example`? Copie para o `.env` do servidor **antes** de rodar o deploy.

### 12.2 Reverter

O healthcheck falhando já reverte sozinho. Para reverter à mão (ex.: deu ok, mas você percebeu um erro depois):

```bash
./deploy/rollback.sh
```

> ⚠️ O rollback reverte o **código**, não o **banco**. Migração já aplicada continua aplicada. Se a migração for o problema, restaure o backup da véspera ([10.5](#105-restaurar-em-produção-desastre)) ou escreva uma migração de correção.

### 12.3 Logs

```bash
dc logs -f --tail=100 web        # aplicação (JSON, sem dado sensível)
dc logs -f --tail=100 worker     # tarefas: e-mail, exportações
dc logs --tail=100 beat
dc logs --tail=100 db
sudo tail -f /var/log/nginx/error.log
```

### 12.4 Comandos úteis

```bash
dc ps                                                       # situação
dc restart web                                              # reinicia (NÃO relê o .env)
dc up -d --force-recreate web worker beat                   # recria (relê o .env)
dc exec web python manage.py shell                          # shell Django
dc exec db psql -U rebanho360 -d rebanho360                 # SQL no banco
dc exec web python manage.py conferir_segundo_fator         # quem usa 2FA + hora do servidor
dc exec web python manage.py resetar_segundo_fator USUARIO --motivo "perdeu o celular"
docker stats --no-stream | grep rebanho360                  # consumo
df -h / /backups                                            # disco
```

O que **nunca** fazer em produção: `dc down -v` · `docker volume rm` · `docker system prune --volumes` · `seed_demo` · editar o banco à mão (a auditoria é imutável e o razão do rebanho é append-only: o banco recusa alteração de auditoria).

### 12.5 Monitoramento mínimo

- Monitor externo (UptimeRobot, Healthchecks, etc.) em `https://rebanho360-demo.ferzion.com.br/ready/` — alerta se falhar por mais de 2 minutos.
- Alerta de **disco acima de 80%** (dump enche disco calado).
- Alerta se o backup externo parar de chegar.
- `SENTRY_DSN` no `.env`, se quiser captura de erro não tratado.

---

## 13. Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `permission denied ... docker.sock` | Usuário fora do grupo `docker` | `sudo usermod -aG docker $USER` e entrar de novo no SSH |
| `./deploy/deploy.sh: Permission denied` | Script sem bit de execução | `chmod +x deploy/*.sh` |
| Build falha ao baixar o Tailwind | Sem acesso a `github.com` no build | Testar `curl -I https://github.com`; o deploy para antes de alterar o que está no ar |
| `Arquitetura não suportada` no build | CPU que não é x86_64/aarch64 | Fora do suporte atual do `build_css.sh` |
| Container `web` reinicia sem parar; log com `ImproperlyConfigured` | `.env` incompleto: `SECRET_KEY` vazia, `DEBUG=True`, `ALLOWED_HOSTS` vazio ou com `*` | Corrigir o `.env` e `dc up -d --force-recreate web worker beat` |
| Healthcheck do deploy falha; `/ready/` devolve `400` | `DJANGO_ALLOWED_HOSTS` não tem o domínio que o script usa | O 1º domínio do `ALLOWED_HOSTS` é o do teste; ou defina `HEALTHCHECK_HOST` |
| `/ready/` devolve `503` com `"database": "erro"` | Postgres fora do ar ou senha errada | `dc logs db`; conferir a senha em `DATABASE_URL` |
| `password authentication failed for user` | `POSTGRES_PASSWORD` foi alterada **depois** da criação do volume | Reponha a senha antiga no `.env`, **ou** troque no banco: `dc exec db psql -U rebanho360 -c "ALTER USER rebanho360 PASSWORD 'nova';"` e atualize `.env` (as duas linhas). **Não** apague o volume se já houver dados |
| `/ready/` devolve `503` com `"redis": "erro"` | Redis fora do ar | `dc ps`, `dc logs redis` |
| Tela de login **sem estilo** | Nginx não serve `/static/` ou a pasta está vazia | `ls /var/www/rebanho360/static`; conferir o `alias` no vhost e `STATIC_HOST_DIR`; rodar `./deploy/deploy.sh` de novo |
| Estilo antigo depois de atualizar | Cache do navegador (o `output.css` não tem hash) | Recarregar forçado (Ctrl+F5); o vhost já usa cache de 1 h |
| `ERR_TOO_MANY_REDIRECTS` | Nginx sem `X-Forwarded-Proto` | Conferir `proxy_set_header X-Forwarded-Proto $scheme;` no vhost |
| `Bad Request (400)` ao abrir o domínio | Domínio fora de `DJANGO_ALLOWED_HOSTS`, ou Nginx sem `proxy_set_header Host $host;` | Ajustar o `.env` (e recriar) ou o vhost |
| `403 CSRF verification failed` no login/POST | `Host`/`X-Forwarded-Proto` não repassados, ou acesso por `http://` | Conferir o vhost; acessar sempre por `https://` |
| `502 Bad Gateway` | `web` fora do ar ou porta diferente da do `proxy_pass` | `dc ps`; `curl 127.0.0.1:8013/health/`; conferir `proxy_pass` |
| `nginx -t` mostra `[warn] protocol options redefined for 0.0.0.0:443` | Vários vhosts declaram `listen 443 ssl http2` e as opções do `listen` se repetem entre eles | **Só aviso**, não erro (`syntax is ok`). Já vinha dos outros sistemas do VPS; não altere os vhosts alheios |
| `413 Request Entity Too Large` | Upload maior que o limite do Nginx | `client_max_body_size` (o exemplo usa 20m); no `http {}` global pode haver valor menor |
| `nginx -t` falha por certificado inexistente | Aplicou o vhost final antes do Certbot | Volte ao vhost provisório (7.1), emita o certificado, e aí aplique o final |
| Certbot não valida o domínio | DNS não propagou, ou 80/443 fechadas | `dig +short domínio`; conferir `ufw` e o firewall do provedor |
| E-mail não chega | SMTP incorreto, porta 465, ou `.env` não recarregado | Rodar o teste de [8.5](#85-testar-o-e-mail); usar porta 587; `dc up -d --force-recreate`; olhar `dc logs worker` |
| Código do 2FA "inválido" para todos | Relógio do servidor desajustado | `timedatectl`; `sudo timedatectl set-ntp true`; `conferir_segundo_fator` |
| Usuário perdeu celular e códigos do 2FA | — | `dc exec web python manage.py resetar_segundo_fator USUARIO --motivo "..."` (fica na auditoria) |
| Sistema subiu com **banco vazio** após mexer no servidor | Pasta do projeto renomeada/movida: o Compose criou volumes novos | Volte a pasta ao nome/local originais (`/var/www/docker-instances/rebanho360`); os volumes antigos estão intactos (`docker volume ls | grep rebanho360`) |
| `web` morto por falta de memória (`Killed`, exit 137) | Limite de 768M estourado (ex.: PDF grande) | `docker stats`; `dmesg -T | grep -i oom`; ver [seção 14](#14-lacunas-conhecidas) |
| `address already in use` na 8013 | Outro serviço usa a porta | Escolher outra porta (ver [2.4](#24-conhecer-o-que-já-roda-no-servidor-sem-mexer)) |
| `git pull` recusa (`Not possible to fast-forward`) | Alteração local ou histórico reescrito no GitHub | `git status`; descartar alteração local; se foi *force push*, falar com quem fez |
| `Nenhuma imagem 'rebanho360_web:previous'` no rollback | Primeiro deploy | Esperado: não existe versão anterior para voltar |

---

## 14. Lacunas conhecidas

Coisas que o repositório ainda **não** resolve — o guia não as esconde:

1. **Healthcheck do container `web` mostra `unhealthy`.** O `docker-compose.prod.yml` chama `http://localhost:8000/health/` sem `Host` do domínio nem `X-Forwarded-Proto`; com `ALLOWED_HOSTS` só com o domínio e `SECURE_SSL_REDIRECT` ligado, a resposta é `400`. É só estético — nada depende dele e o `restart: unless-stopped` não reage a `unhealthy` —, mas **não confie no status do `docker ps`**; use `./deploy/healthcheck.sh` e `/ready/`. Já listado em [docs/arquitetura/02-infra-e-deploy.md](../docs/arquitetura/02-infra-e-deploy.md#pendências-conhecidas).
2. **Sem rotação de logs no compose.** A arquitetura prevê `max-size: 10m / max-file: 5`, mas o `docker-compose.prod.yml` não define `logging:`. Sem rotação, o log do container cresce sem limite. Verifique se o Docker do servidor já tem um padrão: `cat /etc/docker/daemon.json`. Se não tiver, a forma mais simples é:

   ```json
   { "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "5" } }
   ```

   ⚠️ O padrão do `daemon.json` vale para **todos** os containers **novos** do VPS, e aplicá-lo exige `sudo systemctl restart docker` — que **reinicia os containers de todos os sistemas** (a menos que `live-restore` esteja ativo). Faça em janela combinada. A alternativa sem tocar no host é acrescentar um bloco `logging:` aos cinco serviços do compose (mudança de código, via GitHub).
3. **Backup não é agendado pelo sistema.** A documentação de arquitetura cita o `beat`, mas hoje o `beat` só agenda a manutenção das exportações. O agendamento é o cron da [seção 10.3](#103-agendar-cron).
4. **Retenção do backup é simplificada** (90 dias por idade, não 7 diários + 4 semanais + 12 mensais). A política completa fica para quando houver cópia externa estável; use a regra de ciclo de vida do bucket.
5. **Limite de memória do `web` (768M)** com 3 workers do Gunicorn e geração de PDF (WeasyPrint) pode ser apertado. Observe `docker stats` nas primeiras semanas; se estourar, o ajuste é no `docker-compose.prod.yml`.
6. **`BACKUP_ROOT` não é lido do `.env`** (só do ambiente do shell) — ver [seção 5](#5-pastas-do-host).
7. **E-mail só por STARTTLS (587).** SMTP com SSL direto (465) não é suportado sem alterar `prod.py`.
8. **Tributos digitados, não calculados** e demais pendências de negócio: ver [docs/regras-negocio/99-pendencias.md](../docs/regras-negocio/99-pendencias.md). Nada disso bloqueia o deploy.

---

## 15. Checklist final

Espelha o checklist de produção de [docs/arquitetura/02-infra-e-deploy.md](../docs/arquitetura/02-infra-e-deploy.md#checklist-de-produção).

**Servidor**
- [ ] Relógio sincronizado (`timedatectl`)
- [ ] Firewall: só 22/80/443 (mudanças registradas em `firewall.md`)
- [ ] Porta 8013 só em `127.0.0.1`; 5432 e 6379 não publicadas
- [ ] Pasta do projeto em `/var/www/docker-instances/rebanho360` (sem renomear)
- [ ] Deploy key somente leitura no GitHub

**Aplicação**
- [ ] `DJANGO_DEBUG=False`, `ALLOWED_HOSTS` com o domínio real, sem `*`
- [ ] `SECRET_KEY` só no `.env`; `.env` com `chmod 600`, fora do Git, **copiado para o gerenciador de senhas**
- [ ] `./deploy/deploy.sh` terminou com `Deploy OK.`
- [ ] `./deploy/healthcheck.sh` ok
- [ ] `restart: unless-stopped` em todos os containers (vem no compose)

**Acesso e HTTPS**
- [ ] HTTPS com certificado válido e renovação automática testada (`certbot renew --dry-run`)
- [ ] Login com estilo, fontes e ícones, no desktop e no celular
- [ ] HSTS ligado (depois de confirmar o HTTPS), aos poucos
- [ ] Cookies `Secure`/`HttpOnly`/`SameSite=Lax` (vêm configurados em `prod.py`)
- [ ] `seed_demo` **não** foi executado; nenhum usuário `@teste` existe

**Dados e pessoas**
- [ ] Superusuário de suporte criado, com 2FA
- [ ] Administradores reais criados (convite ou senha temporária)
- [ ] Empresa, safra atual, fazendas, categorias e raça cadastradas
- [ ] E-mail de teste recebido

**Backup**
- [ ] Backup diário no cron **e** cópia fora do VPS (`RCLONE_REMOTE`)
- [ ] Primeira restauração de teste feita e **anotada** em `restore-log.md`
- [ ] Logs com rotação (ou decisão registrada — seção 14)
- [ ] Monitor externo no `/ready/` e alerta de disco

**Convivência**
- [ ] Os outros sistemas do VPS continuam funcionando

Fechou tudo? Atualize o roadmap: tarefas **F0-17** (primeiro deploy) e **F0-18** (backup e restauração) em [docs/roadmap/fase-0-fundacao.md](../docs/roadmap/fase-0-fundacao.md).
