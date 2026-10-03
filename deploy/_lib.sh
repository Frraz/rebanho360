#!/usr/bin/env bash
# Funções comuns dos scripts de deploy/. Não é executável: é `source`d.
#
# Os scripts moram em deploy/, mas o docker-compose, o .env e o Dockerfile
# estão na raiz do projeto — por isso todos entram na raiz antes de qualquer
# coisa, e funcionam de qualquer diretório em que forem chamados.

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

# Lê UMA variável do .env sem dar `source` nele: o .env tem chave secreta,
# senhas e URLs com caracteres que o shell interpretaria. Variável já
# exportada no ambiente tem precedência (ex.: `HEALTHCHECK_RETRIES=3 ./deploy/...`).
#   env_var NOME [padrão]
env_var() {
  local nome="$1" padrao="${2:-}" valor
  if [ -n "${!nome:-}" ]; then
    printf '%s' "${!nome}"
    return
  fi
  if [ -f "$RAIZ/.env" ]; then
    valor="$(grep -E "^${nome}=" "$RAIZ/.env" | tail -n 1 | cut -d= -f2- || true)"
    valor="${valor%\"}"; valor="${valor#\"}"
  fi
  printf '%s' "${valor:-$padrao}"
}

# Nome REAL de um volume usado por um container. O Compose prefixa o
# volume com o nome do projeto (`rebanho360_rebanho360_media`), então
# escrever `rebanho360_media` à mão aponta para um volume vazio e novo.
#   volume_de CONTAINER DESTINO_NO_CONTAINER
volume_de() {
  docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$2\"}}{{.Name}}{{end}}{{end}}" "$1" 2>/dev/null
}
