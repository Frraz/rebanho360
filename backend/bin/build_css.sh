#!/bin/sh
# Compila o Tailwind via CLI standalone (sem Node). Chamado no build da
# imagem (docker/web/Dockerfile) e, em dev, manualmente após mudar classes:
#   docker compose exec web sh bin/build_css.sh
set -eu

TAILWIND_VERSION="3.4.14"
BIN="/tmp/tailwindcss"

if [ ! -x "$BIN" ]; then
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64) PLATFORM="linux-x64" ;;
    aarch64) PLATFORM="linux-arm64" ;;
    *) echo "Arquitetura não suportada: $ARCH" >&2; exit 1 ;;
  esac
  curl -sL -o "$BIN" \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-${PLATFORM}"
  chmod +x "$BIN"
fi

"$BIN" -c tailwind.config.js -i static/css/input.css -o static/css/output.css --minify
