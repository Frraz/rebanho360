#!/usr/bin/env bash
# Usado pelo deploy.sh e por monitoramento externo. Sai 0 se /ready/ está
# saudável (banco e Redis respondendo), 1 caso contrário — nunca derruba o
# processo sozinho.
#
# Em produção o Django redireciona http -> https (SECURE_SSL_REDIRECT) e só
# aceita o domínio de DJANGO_ALLOWED_HOSTS. Chamando 127.0.0.1:8010 "cru",
# a resposta seria 301/400 e o teste não diria nada sobre o sistema. Por isso
# o script se apresenta como o nginx faz: Host do domínio + X-Forwarded-Proto.
set -euo pipefail
# shellcheck source=deploy/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

URL="${HEALTHCHECK_URL:-http://127.0.0.1:$(env_var WEB_HOST_PORT 8010)/ready/}"
TENTATIVAS="${HEALTHCHECK_RETRIES:-10}"
INTERVALO="${HEALTHCHECK_INTERVAL:-3}"

# Domínio: HEALTHCHECK_HOST, senão o 1º de DJANGO_ALLOWED_HOSTS, senão localhost.
HOST="$(env_var HEALTHCHECK_HOST)"
if [ -z "$HOST" ]; then
  HOST="$(env_var DJANGO_ALLOWED_HOSTS | cut -d, -f1 | tr -d ' ')"
fi
HOST="${HOST:-localhost}"

RESPOSTA="$(mktemp)"
trap 'rm -f "$RESPOSTA"' EXIT

for i in $(seq 1 "$TENTATIVAS"); do
  # Sem -L: um redirecionamento é falha, não sucesso.
  if curl -fsS --max-time 5 \
       -H "Host: ${HOST}" -H "X-Forwarded-Proto: https" \
       "$URL" > "$RESPOSTA" 2>/dev/null \
     && grep -q '"status": *"ok"' "$RESPOSTA"; then
    echo "Pronto após ${i} tentativa(s): $(cat "$RESPOSTA")"
    exit 0
  fi
  sleep "$INTERVALO"
done

echo "Healthcheck falhou em ${TENTATIVAS} tentativas em ${URL} (Host: ${HOST})" >&2
[ -s "$RESPOSTA" ] && echo "Última resposta: $(cat "$RESPOSTA")" >&2
exit 1
