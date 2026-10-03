#!/usr/bin/env bash
# Atualiza a produção com o que está no GitHub. Rodar NO VPS, na raiz do projeto:
#
#   ./atualizar.sh            mostra o que vai subir, pede confirmação e atualiza
#   ./atualizar.sh -y         sem perguntar (para rodar por SSH/automação)
#   ./atualizar.sh --forcar   refaz o deploy mesmo sem commit novo (ex.: deploy que falhou)
#
# Fluxo: confere o servidor -> git fetch -> mostra os commits novos -> confirma ->
# git pull -> deploy/deploy.sh (backup, build, migrações, subida, healthcheck e
# rollback automático se o healthcheck falhar).
#
# Este script não reimplementa o deploy: só o protege e o torna fácil de chamar.
# Tudo fica dentro de main() para o bash ler a função inteira antes de executar;
# assim o `git pull` pode trocar este arquivo no meio da execução sem quebrá-lo.
set -euo pipefail

main() {
  local RAIZ BRANCH=main AUTO_SIM=0 FORCAR=0 arg
  RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$RAIZ"

  for arg in "$@"; do
    case "$arg" in
      -y|--yes|--sim) AUTO_SIM=1 ;;
      --forcar)       FORCAR=1 ;;
      -h|--help)      sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
      *) echo "Opção desconhecida: $arg (use -h)" >&2; return 2 ;;
    esac
  done

  # Duas atualizações ao mesmo tempo disputariam build, migração e containers.
  exec 9> "$RAIZ/.atualizar.lock"
  if ! flock -n 9; then
    echo "Já existe uma atualização em andamento. Aguarde terminar." >&2
    return 1
  fi

  if [ ! -d .git ]; then
    echo "Esta pasta não é um repositório Git — nada para puxar do GitHub." >&2
    return 1
  fi
  if [ ! -f .env ] || [ ! -f docker-compose.prod.yml ]; then
    echo ".env e docker-compose.prod.yml precisam existir na raiz — este é o servidor de produção?" >&2
    return 1
  fi

  local atual
  atual="$(git rev-parse --abbrev-ref HEAD)"
  if [ "$atual" != "$BRANCH" ]; then
    echo "O servidor está na branch '$atual', não em '$BRANCH'. Volte com: git checkout $BRANCH" >&2
    return 1
  fi

  # Arquivo versionado alterado à mão no servidor faria o pull falhar (ou, pior,
  # seria sobrescrito sem aviso). Arquivos não versionados (.env, etc.) não contam.
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "Há alterações locais em arquivos versionados no servidor:" >&2
    git status --short --untracked-files=no >&2
    echo >&2
    echo "Alterações devem ser feitas no GitHub, não no VPS. Descarte-as (git checkout -- <arquivo>)" >&2
    echo "ou guarde-as (git stash) e rode de novo." >&2
    return 1
  fi

  echo "==> Consultando o GitHub"
  git fetch origin "$BRANCH"

  local local_sha remoto_sha
  local_sha="$(git rev-parse HEAD)"
  remoto_sha="$(git rev-parse "origin/$BRANCH")"

  if [ "$local_sha" = "$remoto_sha" ]; then
    if [ "$FORCAR" -ne 1 ]; then
      echo "Produção já está no último commit (${local_sha:0:7}). Nada a atualizar."
      echo "Para refazer o deploy mesmo assim: ./atualizar.sh --forcar"
      return 0
    fi
    echo "Sem commit novo; refazendo o deploy por --forcar."
  else
    if ! git merge-base --is-ancestor "$local_sha" "$remoto_sha"; then
      echo "O servidor tem commits que não estão no GitHub (histórico divergente). Não vou sobrescrever." >&2
      git log --oneline "origin/$BRANCH..HEAD" >&2
      return 1
    fi

    echo
    echo "Vai subir ${local_sha:0:7} -> ${remoto_sha:0:7}:"
    git log --oneline --no-decorate "$local_sha..$remoto_sha"
    echo
    # Avisos que mudam o risco do deploy.
    if git diff --name-only "$local_sha" "$remoto_sha" | grep -q '/migrations/'; then
      echo "  * Tem MIGRAÇÃO de banco. O rollback reverte o código, não o banco (o backup roda antes)."
    fi
    if git diff --name-only "$local_sha" "$remoto_sha" | grep -qE '^(\.env\.example|docker-compose\.prod\.yml)$'; then
      echo "  * Mudou .env.example ou docker-compose.prod.yml — confira se o .env do servidor precisa de variável nova."
    fi
    echo
  fi

  if [ "$AUTO_SIM" -ne 1 ]; then
    local resp
    read -r -p "Atualizar a produção agora? [s/N] " resp
    case "$resp" in
      s|S|sim|SIM) ;;
      *) echo "Cancelado. Nada foi alterado."; return 0 ;;
    esac
  fi

  echo "==> Atualizando o código"
  git pull --ff-only origin "$BRANCH"

  echo "==> Deploy"
  # Chamado como subprocesso já com o código novo: se o próprio deploy.sh mudou
  # neste pull, roda a versão nova, não a que estava na memória.
  ./deploy/deploy.sh

  echo
  echo "Produção atualizada: $(git log -1 --format='%h %s')"
}

main "$@"
exit $?
