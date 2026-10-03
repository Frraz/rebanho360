#!/usr/bin/env bash
# Sobe o sistema completo localmente via Docker Compose — roda sempre que
# algo mudar (código, migração, dependência, CSS). Idempotente: chamar de
# novo depois de qualquer alteração é seguro.
#
# Uso (de qualquer pasta):  ./deploy/local.sh
set -euo pipefail
# shellcheck source=deploy/_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"   # entra na raiz do projeto

if [ ! -f .env ]; then
  echo "==> .env não existe — criando a partir de .env.example"
  cp .env.example .env
  SECRET="$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")"
  sed -i "s#^DJANGO_SECRET_KEY=.*#DJANGO_SECRET_KEY=${SECRET}#" .env
  echo "    Gerado DJANGO_SECRET_KEY para desenvolvimento local."
fi

echo "==> 1/5 Build e subida dos containers"
docker compose up --build -d

echo "==> 2/5 Migrações"
docker compose exec -T web python manage.py migrate --noinput

echo "==> 3/5 Dados de demonstração (idempotente)"
docker compose exec -T web python manage.py seed_demo

# O Tailwind standalone é baixado na primeira vez (precisa de rede). Se não
# der, o sistema segue com o static/css/output.css que já existe — só as
# classes novas deixam de aparecer. output.css é gerado e não é versionado.
echo "==> 4/5 CSS (Tailwind)"
if ! docker compose exec -T web sh bin/build_css.sh; then
  if [ -f backend/static/css/output.css ]; then
    echo "    AVISO: não foi possível recompilar o CSS; mantendo o output.css existente." >&2
  else
    echo "    ERRO: sem CSS compilado, a tela abre sem estilo. Rode de novo com rede: ./deploy/local.sh" >&2
    exit 1
  fi
fi

echo "==> 5/5 Aguardando /ready/"
PRONTO=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/ready/ > /dev/null 2>&1; then
    PRONTO=1
    break
  fi
  sleep 1
done

if [ "$PRONTO" -ne 1 ]; then
  echo "O sistema subiu, mas /ready/ não respondeu em 30s — ver 'docker compose logs web'." >&2
  exit 1
fi

cat <<'EOF2'

Rebanho360 no ar em http://127.0.0.1:8000/contas/entrar/

Usuários de demonstração (senha demo12345 para todos):
  admin@teste · gestor@teste · escritorio@teste
  campo@teste · financeiro@teste · consulta@teste

Logs:   docker compose logs -f web
Testes: docker compose run --rm --no-deps -T -v "$PWD/docs:/docs:ro" web python -m pytest -p no:cacheprovider -q
        (o -v docs é obrigatório: sem ele ~47 testes de importação pulam em silêncio)
CSS:    docker compose exec web sh bin/build_css.sh   (depois de mudar classes ou input.css)
Parar:  docker compose down
EOF2
