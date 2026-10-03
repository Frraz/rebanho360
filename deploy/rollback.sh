#!/usr/bin/env bash
# Volta para a imagem anterior do serviço `web` (e worker/beat, que usam a
# mesma imagem). Chamado pelo deploy.sh quando o healthcheck pós-deploy falha.
#
# O deploy.sh etiqueta a imagem em produção como `rebanho360_web:previous`
# ANTES de construir a nova. Procurar "a segunda imagem da lista" não
# funciona: ao reconstruir, a antiga perde a etiqueta e vira <none>.
#
# Atenção: reverte o CÓDIGO, não o banco. Se o deploy aplicou uma migração,
# ela continua aplicada — por isso migração destrutiva exige backup e janela
# combinada (docs/arquitetura/02-infra-e-deploy.md#deploy).
set -euo pipefail
# shellcheck source=deploy/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

COMPOSE="docker compose -f docker-compose.prod.yml"

echo "Revertendo para a imagem anterior de rebanho360_web..."

if ! docker image inspect rebanho360_web:previous > /dev/null 2>&1; then
  echo "Nenhuma imagem 'rebanho360_web:previous' — não há para onde reverter (primeiro deploy?)." >&2
  exit 1
fi

PREVIOUS_IMAGE_ID="$(docker image inspect -f '{{.Id}}' rebanho360_web:previous)"

docker tag rebanho360_web:previous rebanho360_web:latest
# --no-build: subir exatamente a imagem restaurada, sem reconstruir a defeituosa.
$COMPOSE up -d --no-build web worker beat

echo "Revertido para a imagem ${PREVIOUS_IMAGE_ID}. Investigue o deploy antes de tentar de novo."
