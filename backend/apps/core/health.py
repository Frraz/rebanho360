"""`/health/` e `/ready/` — sem autenticação, fora do log de acesso (F0-13).

Ver docs/arquitetura/02-infra-e-deploy.md#health-check.
"""

from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse


def health(request):
    """Só confirma que o processo está vivo. Usado pelo healthcheck do Docker."""
    return JsonResponse({"status": "ok"})


def ready(request):
    """Confirma que banco e Redis respondem. Usado por deploy e monitoramento."""
    checks = {}

    try:
        connections["default"].cursor()
        checks["database"] = "ok"
    except OperationalError:
        checks["database"] = "erro"

    try:
        import redis

        redis.from_url(settings.REDIS_URL, socket_connect_timeout=2).ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "erro"

    healthy = all(v == "ok" for v in checks.values())
    status_code = 200 if healthy else 503
    return JsonResponse(
        {"status": "ok" if healthy else "erro", "checks": checks}, status=status_code
    )
