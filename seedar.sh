#!/usr/bin/env bash
# Popula o sistema com a operação de demonstração (12 fazendas, 3 safras).
# Roda na raiz do projeto, em produção (beta) ou em desenvolvimento:
#
#   ./seedar.sh                       pede confirmação e semeia (volume completo, ~10 min)
#   ./seedar.sh -y                    sem perguntar (SSH/automação)
#   ./seedar.sh --escala 0.2          volume reduzido (bem mais rápido)
#   ./seedar.sh --vincular-acessos    dá acesso às fazendas do seed aos papéis restritos
#   ./seedar.sh --manter-safras-abertas
#   ./seedar.sh --semente 7           outra sequência aleatória
#   ./seedar.sh --sem-backup          não faz backup antes (só em produção)
#
# Usa sempre --force: o seed recusa DEBUG=False, e a produção beta roda assim.
# NÃO cria nem altera usuário. Para desfazer: ./desfazerseed.sh
#
# Em produção o código vai dentro da imagem: se o comando ainda não existir lá,
# rode ./atualizar.sh antes.
set -euo pipefail

main() {
  local RAIZ AUTO_SIM=0 SEM_BACKUP=0 arg
  local EXTRA=()
  RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$RAIZ"

  while [ $# -gt 0 ]; do
    arg="$1"; shift
    case "$arg" in
      -y|--yes|--sim)          AUTO_SIM=1 ;;
      --sem-backup)            SEM_BACKUP=1 ;;
      --escala|--semente)
        [ $# -gt 0 ] || { echo "$arg precisa de um valor." >&2; return 2; }
        EXTRA+=("$arg" "$1"); shift ;;
      --vincular-acessos|--manter-safras-abertas) EXTRA+=("$arg") ;;
      -h|--help)               sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
      *) echo "Opção desconhecida: $arg (use -h)" >&2; return 2 ;;
    esac
  done

  # Produção = container rebanho360_web (compose.prod); senão, desenvolvimento.
  local COMPOSE AMBIENTE
  if docker ps --format '{{.Names}}' | grep -qx rebanho360_web; then
    COMPOSE="docker compose -f docker-compose.prod.yml"; AMBIENTE="produção (beta)"
  else
    COMPOSE="docker compose"; AMBIENTE="desenvolvimento"
  fi

  if ! $COMPOSE exec -T web true </dev/null 2>/dev/null; then
    echo "O container 'web' não está rodando ($AMBIENTE). Suba o sistema antes." >&2
    return 1
  fi
  if ! $COMPOSE exec -T web python manage.py help seed_operacao_grande >/dev/null 2>&1 </dev/null; then
    echo "O comando seed_operacao_grande não existe neste container." >&2
    echo "Em produção o código vai dentro da imagem: rode ./atualizar.sh primeiro." >&2
    return 1
  fi

  echo "Ambiente: $AMBIENTE"
  echo "Vai criar fazendas, rebanho, compras, vendas, custos e títulos FICTÍCIOS."
  echo "Usuários não são tocados. Para desfazer: ./desfazerseed.sh"
  if [ "$AUTO_SIM" -ne 1 ]; then
    read -r -p "Continuar? [s/N] " resposta
    case "$resposta" in s|S|sim|SIM) ;; *) echo "Cancelado."; return 0 ;; esac
  fi

  # Backup só em produção: lá há dado real. O backup.sh já ignora o caso
  # "banco ainda não existe".
  if [ "$AMBIENTE" != "desenvolvimento" ] && [ "$SEM_BACKUP" -ne 1 ]; then
    echo "==> Backup antes de semear"
    ./deploy/backup.sh
  fi

  echo "==> Semeando (pode levar vários minutos no volume completo)"
  $COMPOSE exec -T web python manage.py seed_operacao_grande --force ${EXTRA[@]+"${EXTRA[@]}"}
}

main "$@"
