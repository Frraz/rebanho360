#!/usr/bin/env bash
# Deploy repetível, sem passo manual esquecível. Roda no VPS, com
# docker-compose.prod.yml e .env já na raiz do projeto (o script entra na
# raiz sozinho; pode ser chamado de qualquer diretório).
#
# Variáveis opcionais (no ambiente ou no .env):
#   STATIC_HOST_DIR  pasta do host que o nginx serve em /static/ (ver
#                    deploy/nginx.conf.example). Sem ela o deploy avisa.
#   BACKUP_ROOT, RCLONE_REMOTE, HEALTHCHECK_* — ver os scripts respectivos.
set -euo pipefail
# shellcheck source=deploy/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

COMPOSE="docker compose -f docker-compose.prod.yml"

if [ ! -f .env ]; then
  echo ".env não existe em ${RAIZ} — copie .env.example, preencha e use chmod 600." >&2
  exit 1
fi
if [ ! -f docker-compose.prod.yml ]; then
  echo "docker-compose.prod.yml não encontrado em ${RAIZ}." >&2
  exit 1
fi

echo "==> 1/6 Backup"
./deploy/backup.sh

echo "==> 2/6 Código"
if [ -d .git ]; then
  git pull --ff-only origin main
else
  echo "Pasta sem .git — pulando 'git pull' (código já deve estar atualizado aqui)."
fi

echo "==> 3/6 Build"
# Guarda a imagem que está no ar: é o destino do rollback.sh.
if docker image inspect rebanho360_web:latest > /dev/null 2>&1; then
  docker tag rebanho360_web:latest rebanho360_web:previous
fi
# O estágio `prod` do Dockerfile compila o Tailwind (static/css/output.css
# não é versionado) e roda o collectstatic; sem rede para baixar o CLI do
# Tailwind, este passo falha e o deploy para aqui, antes de tocar no que está no ar.
$COMPOSE build web

echo "==> 4/6 Migrações e estáticos"
$COMPOSE run --rm web python manage.py migrate --noinput
$COMPOSE run --rm web python manage.py collectstatic --noinput

# O Django em produção NÃO serve /static/ (sem WhiteNoise, e o gunicorn não
# serve arquivo). Sem este passo o sistema abre sem CSS, fontes e ícones.
STATIC_HOST_DIR="$(env_var STATIC_HOST_DIR)"
if [ -n "$STATIC_HOST_DIR" ]; then
  echo "    Publicando estáticos em ${STATIC_HOST_DIR}"
  mkdir -p "$STATIC_HOST_DIR"
  $COMPOSE run --rm --no-deps -v "${STATIC_HOST_DIR}:/publicar" web \
    sh -c 'cp -a /app/staticfiles/. /publicar/'
else
  echo "    AVISO: STATIC_HOST_DIR não definido — o nginx precisa servir /static/ a partir do" >&2
  echo "    volume rebanho360_static (ver deploy/nginx.conf.example). Sem isso, a tela abre sem estilo." >&2
fi

echo "==> 5/6 Subindo"
$COMPOSE up -d web worker beat

echo "==> 6/6 Healthcheck"
if ./deploy/healthcheck.sh; then
  echo "Deploy OK."
else
  echo "Healthcheck falhou — rollback."
  ./deploy/rollback.sh
  exit 1
fi
