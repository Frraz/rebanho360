# Infraestrutura e deploy

## Premissa

O VPS Ubuntu **já hospeda outros sistemas**. Nada aqui pode assumir máquina dedicada.

Regras que valem sempre:

- Não ocupar porta já em uso
- Não alterar o Nginx dos outros sistemas
- Não mexer no firewall sem documentar em `deploy/`
- Não derrubar nem apagar container ou volume de terceiro
- Prefixar tudo que for nosso com `rebanho360_`

## Topologia

```
Internet
   │  443/tcp
   ▼
Nginx do host  ← já existe, compartilhado
   ├── sistema-a.exemplo.com
   ├── sistema-b.exemplo.com
   └── rebanho360.exemplo.com → proxy_pass 127.0.0.1:8010
                                          │
                        ┌─────────────────┴──────────────────┐
                        │  docker network rebanho360_net     │
                        │  (interna, sem publicação)         │
                        │                                    │
                        │   web ──── worker ──── beat        │
                        │    │         │           │         │
                        │    └─────────┴───────────┘         │
                        │           │        │               │
                        │        postgres  redis             │
                        └────────────────────────────────────┘
```

**Só o `web` publica porta, e só em `127.0.0.1`.** PostgreSQL e Redis ficam na rede interna do Docker, sem `ports:` — inalcançáveis de fora da máquina.

Usar o Nginx do host em vez de subir outro: menos conflito de porta, um só lugar de certificado TLS, um só lugar de log de acesso.

## Serviços

| Container | Imagem | Papel |
|---|---|---|
| `rebanho360_web` | build local | Django + Gunicorn |
| `rebanho360_worker` | build local | Celery |
| `rebanho360_beat` | build local | Celery Beat (backup, consolidação noturna) |
| `rebanho360_db` | `postgres:16-alpine` | Banco |
| `rebanho360_redis` | `redis:7-alpine` | Broker e cache |

Todos com `restart: unless-stopped`, `healthcheck` e limite de memória — para que um problema nosso não derrube os vizinhos.

## Volumes

```
rebanho360_pgdata     dados do PostgreSQL
rebanho360_media      anexos, PDFs gerados, planilhas importadas
rebanho360_static     arquivos estáticos coletados
```

Nomeados, nunca anônimos. Nunca apagados em deploy.

## Configuração

```
config/settings/
├── base.py         comum
├── dev.py          DEBUG=True, e-mail no console
└── prod.py         DEBUG=False, segurança ligada
```

`.env` fora do Git, permissão `600`, dono do usuário da aplicação. `.env.example` versionado com as chaves e sem os valores.

Variáveis obrigatórias em produção: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, `REDIS_URL`, `DJANGO_SETTINGS_MODULE=config.settings.prod`.

A aplicação **recusa subir** em produção se `SECRET_KEY` estiver ausente ou `DEBUG=True`. Falhar alto é melhor que subir inseguro.

## Deploy

Repetível, sem passo manual esquecível. Roda no VPS, a partir de qualquer pasta (os scripts entram na raiz do projeto sozinhos):

```bash
./deploy/deploy.sh
```

Em ordem, com `set -euo pipefail` (qualquer passo que falhe interrompe o deploy):

1. **Backup** (`backup.sh`) — antes de tudo. No primeiro deploy, sem banco ainda, é ignorado.
2. **Código** — `git pull --ff-only origin main` (pulado se a pasta não for um clone).
3. **Build** — antes, a imagem em produção é etiquetada `rebanho360_web:previous` (o destino do rollback). O estágio `prod` do Dockerfile compila o Tailwind e roda o `collectstatic`.
4. **Migrações e estáticos** — `migrate` e `collectstatic`; depois, **publica os estáticos** em `STATIC_HOST_DIR`.
5. **Sobe** `web worker beat`.
6. **Health check** (`healthcheck.sh`); se falhar, `rollback.sh` e o deploy sai com erro.

Antes de migração destrutiva: backup, migração reversível quando possível, e janela combinada. O rollback reverte o **código**, não as migrações já aplicadas.

### Estáticos (CSS, fontes, ícones)

O Django em produção **não serve `/static/`**: não há WhiteNoise e o Gunicorn não serve arquivo. Quem entrega é o Nginx do host, a partir de uma pasta do host. O `deploy.sh` copia o `collectstatic` do volume `rebanho360_static` para `STATIC_HOST_DIR` (definida no `.env`, ex.: `/var/www/rebanho360/static`). O vhost de exemplo, com cache curto para `output.css` (nome sem hash) e longo para fontes, está em [`deploy/nginx.conf.example`](../../deploy/nginx.conf.example). Sem isso o sistema abre **sem estilo, fontes e ícones**; o deploy avisa quando `STATIC_HOST_DIR` não está definida.

Anexos e PDFs gerados **não** passam pelo Nginx: saem por view autenticada.

### Volumes

O Compose prefixa o nome do projeto (`rebanho360_rebanho360_media`). Por isso os scripts descobrem o volume pelo container (`docker inspect`) em vez de usar o nome escrito à mão — escrever `rebanho360_media` apontaria para um volume novo e vazio.

### Desenvolvimento local

`./deploy/local.sh` sobe tudo (containers, migração, `seed_demo`, CSS, espera o `/ready/`) e pode ser repetido a qualquer momento.

## Health check

| Rota | Verifica | Uso |
|---|---|---|
| `/health/` | Processo vivo | Docker healthcheck |
| `/ready/` | Banco e Redis respondem | Deploy e monitoramento |

Ambas sem autenticação, sem dado sensível, e **fora** do log de acesso — senão poluem o log com uma linha por segundo.

**Chamar de fora do Nginx exige se apresentar como ele.** Em produção o Django redireciona http→https (`SECURE_SSL_REDIRECT`) e só aceita o domínio de `DJANGO_ALLOWED_HOSTS`: um `curl 127.0.0.1:8010/ready/` cru recebe 400 (Host inválido), e com o Host certo mas sem o cabeçalho de proto recebe 301. O `healthcheck.sh` envia `Host: <1º domínio de DJANGO_ALLOWED_HOSTS>` e `X-Forwarded-Proto: https` e só aceita `"status": "ok"` no corpo. (O `healthcheck` do container no `docker-compose.prod.yml` ainda chama `localhost` sem esses cabeçalhos — ver pendência abaixo.)

## Backup

Sem isto, o resto não importa.

```
Diário 03:00   pg_dump comprimido       → /backups/db/
Diário 03:30   tar do volume de media   → /backups/media/
Diário 04:00   envio para fora do VPS   → rclone / S3
```

Retenção: 7 diários, 4 semanais, 12 mensais.

> **Backup no mesmo VPS não é backup.** Disco que morre leva o banco e a cópia juntos. A cópia externa é a que conta.

### Restauração testada

**Mensal, na agenda, com resultado anotado** em `deploy/restore-log.md`:

1. Subir Postgres limpo em container descartável
2. Restaurar o dump da noite anterior
3. Conferir: total de cabeças por fazenda, total de custos da safra, contagem de movimentos
4. Anotar data, duração e resultado
5. Destruir o container

Backup nunca restaurado é hipótese, não garantia. O procedimento também mede **quanto tempo** a restauração leva — que é o número que importa no dia ruim.

## Logs

JSON estruturado em `stdout`, coletado pelo Docker, com rotação (`max-size: 10m`, `max-file: 5`).

Campos: `timestamp`, `level`, `logger`, `request_id`, `user_id`, `action`, `message`.

**Nunca no log:** senha, token, `SECRET_KEY`, dado bancário completo, CPF/CNPJ integral. Filtro no `logging.Formatter`, não na disciplina de quem escreve o log.

## Firewall

```
22/tcp    SSH — só por chave, senha desabilitada
80/tcp    HTTP → redireciona para HTTPS
443/tcp   HTTPS
```

Nada mais. PostgreSQL (5432) e Redis (6379) **nunca** abertos — não estão publicados nem no Docker.

Alteração de firewall vai documentada em `deploy/firewall.md`, com data e motivo, porque a máquina é compartilhada.

## Monitoramento mínimo

- Disco acima de 80% → alerta (dump de banco enche disco calado)
- `/ready/` falhando por mais de 2 minutos → alerta
- Backup externo que não rodou → alerta
- Sentry para erro não tratado, se aprovado

## Checklist de produção

- [ ] `DEBUG=False`
- [ ] `SECRET_KEY` só no `.env`, `.env` fora do Git
- [ ] `ALLOWED_HOSTS` com o domínio real, sem `*`
- [ ] HTTPS com certificado válido e renovação automática
- [ ] HSTS ligado (**depois** de confirmar que o HTTPS funciona)
- [ ] Cookies `Secure`, `HttpOnly`, `SameSite=Lax`
- [ ] Postgres e Redis sem porta publicada
- [ ] Volumes nomeados e persistentes
- [ ] `STATIC_HOST_DIR` definida e o Nginx servindo `/static/` (abrir a tela de login: com estilo, fontes e ícones)
- [ ] `/ready/` respondendo pelo `healthcheck.sh` (não só pelo `curl` cru)
- [ ] Backup diário rodando **e** com cópia fora do VPS
- [ ] Restauração testada ao menos uma vez, anotada
- [ ] Health check respondendo
- [ ] Logs com rotação
- [ ] Firewall conferido
- [ ] `restart: unless-stopped` em todos os containers

## Pendências conhecidas

- `docker-compose.prod.yml`: o `healthcheck` do `web` usa `curl -f http://localhost:8000/health/`. Com `ALLOWED_HOSTS` só com o domínio e `SECURE_SSL_REDIRECT` ligado, isso responde 400 e o container aparece como *unhealthy*. Precisa dos mesmos cabeçalhos do `healthcheck.sh` (ou de uma isenção do redirect para `/health/`).
- Primeiro deploy real continua pendente (F0-17): `nginx.conf.example` e `restore-check.sql` foram escritos e o SQL validado contra o banco de desenvolvimento, mas o vhost nunca foi aplicado num servidor.


## Fase 4 — o que muda no deploy

- **Reconstruir a imagem** (`docker compose -f docker-compose.prod.yml build`): nova dependência `segno` (QR code do 2FA).
- Migrações novas: `accounts` 0002, `audit` 0004, `purchases` 0002, `sales` 0002, `finance` 0001 — o `deploy.sh` já roda `migrate`.
- **Segundo fator — opcional.** Rodar `docker compose exec web python manage.py conferir_segundo_fator` (mostra a hora do servidor e quem já usa); conferir `timedatectl` (NTP ativo — os códigos do celular dependem do relógio). Recuperação de emergência: `manage.py resetar_segundo_fator <usuário>`.
- O histórico importado **não gera título**; depois do deploy, quem conhece o caso gera o que ainda estiver em aberto em *Financeiro → Operações sem título*.
