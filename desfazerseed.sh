#!/usr/bin/env bash
# Desfaz o que o seedar.sh criou — e só isso. Roda na raiz do projeto, em
# produção (beta) ou em desenvolvimento:
#
#   ./desfazerseed.sh              pede confirmação e desfaz
#   ./desfazerseed.sh -y           sem perguntar (SSH/automação)
#   ./desfazerseed.sh --simular    só mostra o que seria apagado, não apaga nada
#   ./desfazerseed.sh --sem-backup não faz backup antes (só em produção)
#
# Usa sempre --force: o desfazer recusa DEBUG=False, e a produção beta roda assim.
# Apaga de verdade as fazendas S3-…, o que pertence a elas e os parceiros do seed.
# Usuários e a auditoria NÃO são tocados. Se algum dado seu depender do seed, para
# e não apaga nada.
set -euo pipefail

main() {
  local RAIZ AUTO_SIM=0 SEM_BACKUP=0 SIMULAR=0 arg
  RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$RAIZ"

  for arg in "$@"; do
    case "$arg" in
      -y|--yes|--sim) AUTO_SIM=1 ;;
      --simular)      SIMULAR=1 ;;
      --sem-backup)   SEM_BACKUP=1 ;;
      -h|--help)      sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
      *) echo "Opção desconhecida: $arg (use -h)" >&2; return 2 ;;
    esac
  done

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
  if ! $COMPOSE exec -T web python manage.py help desfazer_seed_operacao_grande >/dev/null 2>&1 </dev/null; then
    echo "O comando desfazer_seed_operacao_grande não existe neste container." >&2
    echo "Em produção o código vai dentro da imagem: rode ./atualizar.sh primeiro." >&2
    return 1
  fi

  if [ "$SIMULAR" -eq 1 ]; then
    echo "Ambiente: $AMBIENTE — simulação (nada será apagado)"
    $COMPOSE exec -T web python manage.py desfazer_seed_operacao_grande --force --simular
    return 0
  fi

  echo "Ambiente: $AMBIENTE"
  echo "Vai APAGAR de verdade as fazendas S3-… e tudo que o seed criou."
  echo "Usuários e auditoria não são tocados."
  if [ "$AUTO_SIM" -ne 1 ]; then
    read -r -p "Continuar? [s/N] " resposta
    case "$resposta" in s|S|sim|SIM) ;; *) echo "Cancelado."; return 0 ;; esac
  fi

  if [ "$AMBIENTE" != "desenvolvimento" ] && [ "$SEM_BACKUP" -ne 1 ]; then
    echo "==> Backup antes de desfazer"
    ./deploy/backup.sh
  fi

  echo "==> Desfazendo"
  $COMPOSE exec -T web python manage.py desfazer_seed_operacao_grande --force --sim
}

main "$@"
