import os

from config.settings.base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
SECRET_KEY = SECRET_KEY or "dev-only-not-secret-" + "x" * 30  # noqa: F405

# Facilita rodar sem HTTPS local
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# O painel de SQL formata cada consulta e chegou a ser metade do tempo medido de
# uma tela (docs/operacao/02-desempenho.md): ligado sempre, o desenvolvimento
# parece mais lento do que o sistema é. Para investigar consultas:
# DJANGO_DEBUG_TOOLBAR=1 no .env.
if os.environ.get("DJANGO_DEBUG_TOOLBAR", "").lower() in ("1", "true", "sim"):
    INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
    MIDDLEWARE = [
        "debug_toolbar.middleware.DebugToolbarMiddleware",
        *MIDDLEWARE,  # noqa: F405
    ]
    INTERNAL_IPS = ["127.0.0.1"]
