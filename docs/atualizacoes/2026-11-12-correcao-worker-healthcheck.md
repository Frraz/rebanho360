# Correção do worker, do beat e do healthcheck — 12/11/2026

Levantado pelo monitoramento em produção (VPS do JMA) e confirmado na demo: nenhuma tarefa em segundo plano rodou desde a entrada no ar.

## O que estava errado

| Sintoma | Causa |
|---|---|
| `rebanho360_worker` em loop de reinícios (664 em ~12 h) | `requirements/base.txt` fixava `celery==5.4.0` e `redis==5.1.1`, mas deixava o `kombu` livre. O pip resolveu o `kombu 5.6.x`, que exige `redis-py >= 6.1`: `VersionMismatch` ao abrir o broker. |
| `rebanho360_beat` reiniciando (~1 a cada 15 min) | Mesma causa. O beat sobe, e cai ao enviar a primeira tarefa agendada (`exports.manutencao`, a cada 15 min). |
| `rebanho360_web` *unhealthy* | O healthcheck do compose chamava `curl -f http://localhost:8000/health/` sem `Host` do domínio nem `X-Forwarded-Proto`. O Django respondia 400 (`ALLOWED_HOSTS`). Já constava como pendência em `02-infra-e-deploy.md`. |

O site continuou servindo normalmente: o nginx não depende do healthcheck do Docker.

## O que mudou

- `backend/requirements/base.txt`: família do Celery inteira fixada (`kombu 5.4.2`, `amqp`, `billiard`, `vine`, `click`), na mesma época do `celery 5.4.0` e do `redis 5.1.1`. O `redis-py` não mudou.
- `docker/web/Dockerfile`: `pip check` depois do `pip install` (dev e prod). Combinação incompatível agora quebra o **build**, não o worker em produção.
- `docker-compose.prod.yml`: healthcheck do `web` se apresenta como o nginx (Host + `X-Forwarded-Proto`) e ganhou `start_period`. Nenhuma mudança no Django: segurança igual.
- `deploy/deploy.sh`: além do web, confere o worker (`celery inspect ping`); falhando, `rollback.sh`.
- `apps/documents/services.py`: relatório pesado com a fila fora do ar vira `ERRO` com mensagem clara, em vez de ficar "Gerando" para sempre (mesmo padrão que as exportações já tinham). Teste novo em `apps/documents/tests/test_documents.py`.

Sem migração de banco. Nenhum dado é alterado; os volumes não são tocados.

## Efeito do defeito nos dados

- **E-mail:** já tinha envio direto como alternativa; nada se perdeu.
- **Exportação:** ficou `ERRO` com mensagem clara; basta pedir de novo.
- **PDF de relatório pesado:** ficava em "Gerando" para sempre. Os que estiverem assim em produção devem ser reenfileirados (roteiro abaixo). A geração é idempotente.
- A fila do Redis deve estar vazia: o web nunca conseguiu enfileirar.

## Verificação local

- Build limpo, `pip check` sem conflitos, `redis 5.1.1 | kombu 5.4.2 | celery 5.4.0`.
- Worker: `Connected to redis://…` e `ready`; beat: `Starting...`; `ping.delay().get()` devolveu `pong`; zero reinícios.
- Imagem `prod`: o comando antigo do healthcheck devolve HTTP 400; o novo devolve 200.
- 543 testes de `documents`, `exports`, `core` e `accounts` passam; `ruff` limpo; sem migração pendente.

## Roteiro de aplicação (demo primeiro, depois produção)

Antes (só leitura):

```bash
cd /var/www/docker-instances/rebanho360
docker exec rebanho360_redis redis-cli llen celery
docker logs --tail 25 rebanho360_beat 2>&1 | cut -c1-200
docker compose -f docker-compose.prod.yml exec -T web python manage.py shell -c \
  "from apps.documents.models import GeneratedDocument as D; print(list(D.objects.filter(status='PENDENTE').values_list('pk', flat=True)))"
```

Atualizar: `./atualizar.sh`. Recria só `web`, `worker` e `beat`; banco e Redis seguem de pé.

Depois (esperar ~2 min):

```bash
docker ps --filter name=rebanho360 --format '{{.Names}}  {{.Status}}'
docker inspect -f '{{.Name}} reinícios={{.RestartCount}}' rebanho360_worker rebanho360_beat
docker logs --tail 15 rebanho360_worker 2>&1 | cut -c1-160     # esperado: ready
docker compose -f docker-compose.prod.yml exec -T web python manage.py shell -c \
  "from apps.core.tasks import ping; print(ping.delay().get(timeout=30))"   # esperado: pong
```

PDFs presos em "Gerando" (lista da primeira consulta), se houver:

```bash
docker compose -f docker-compose.prod.yml exec -T web python manage.py shell -c \
  "from apps.documents.models import GeneratedDocument as D; from apps.documents.tasks import gerar_pdf; [gerar_pdf.delay(pk) for pk in D.objects.filter(status='PENDENTE').values_list('pk', flat=True)]"
```

Na primeira execução rodam `exports.manutencao` (apaga exportações com mais de 30 dias; não há) e `accounts.manutencao` (`clearsessions`, só sessões já vencidas). Nenhum dado de negócio é afetado.

Plano de volta: `./deploy/rollback.sh` (volta a `rebanho360_web:previous`: site no ar, worker parado). Fazer no mesmo dia, porque o cron do servidor remove imagens sem contêiner após 24 h.

## Fora do escopo desta correção

Backup do banco em produção continua pendente, por decisão de Warley.
