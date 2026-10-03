#!/usr/bin/env bash
# Backup diário: dump do Postgres + tar do volume de media. Rodado pelo
# `beat` (Celery) ou por cron do host — ver docs/arquitetura/02-infra-e-deploy.md#backup.
#
# Backup no mesmo VPS não é backup: o passo 3 (envio para fora) é o que
# conta. Configurar RCLONE_REMOTE antes de depender disto de verdade.
set -euo pipefail
# shellcheck source=deploy/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DB_DIR="${BACKUP_ROOT}/db"
MEDIA_DIR="${BACKUP_ROOT}/media"

PG_USER="$(env_var POSTGRES_USER rebanho360)"
PG_DB="$(env_var POSTGRES_DB rebanho360)"
RCLONE_REMOTE="$(env_var RCLONE_REMOTE)"

# Primeiro deploy: ainda não há banco para guardar. Não é falha — e o
# deploy.sh chama este script antes de tudo.
if ! docker ps --format '{{.Names}}' | grep -qx rebanho360_db; then
  echo "Container rebanho360_db não está rodando — nada para guardar (primeiro deploy?). Backup ignorado." >&2
  exit 0
fi

mkdir -p "$DB_DIR" "$MEDIA_DIR"

echo "==> 1/3 pg_dump"
docker exec rebanho360_db pg_dump -U "$PG_USER" -Fc "$PG_DB" \
  > "${DB_DIR}/rebanho360_${TIMESTAMP}.dump"

echo "==> 2/3 tar do volume de media (anexos, PDFs gerados, planilhas)"
MEDIA_VOLUME="$(volume_de rebanho360_web /app/media)"
if [ -z "$MEDIA_VOLUME" ]; then
  echo "Volume de media não encontrado em rebanho360_web — media FICOU FORA deste backup." >&2
else
  docker run --rm \
    -v "${MEDIA_VOLUME}:/data:ro" \
    -v "${MEDIA_DIR}:/backup" \
    alpine tar czf "/backup/media_${TIMESTAMP}.tar.gz" -C /data .
fi

echo "==> 3/3 envio para fora do VPS"
if [ -n "$RCLONE_REMOTE" ]; then
  rclone copy "${DB_DIR}/rebanho360_${TIMESTAMP}.dump" "${RCLONE_REMOTE}/db/"
  if [ -f "${MEDIA_DIR}/media_${TIMESTAMP}.tar.gz" ]; then
    rclone copy "${MEDIA_DIR}/media_${TIMESTAMP}.tar.gz" "${RCLONE_REMOTE}/media/"
  fi
else
  echo "RCLONE_REMOTE não configurado — backup ficou só local. Isso NÃO é backup de verdade." >&2
fi

# Simplificado por idade; a política alvo (7 diários, 4 semanais, 12 mensais)
# exige separar por data e fica para quando houver cópia externa.
echo "==> Retenção local: apaga o que tem mais de 90 dias"
find "$DB_DIR" -name "*.dump" -mtime +90 -delete
find "$MEDIA_DIR" -name "*.tar.gz" -mtime +90 -delete

echo "Backup concluído: ${TIMESTAMP}"
