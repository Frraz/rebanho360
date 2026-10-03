from django.core.exceptions import ImproperlyConfigured

from config.settings.base import *  # noqa: F401,F403

# Falhar alto é melhor que subir inseguro — docs/arquitetura/02-infra-e-deploy.md
if not SECRET_KEY:  # noqa: F405
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY ausente. A aplicação recusa subir em produção sem ela."
    )

if DEBUG:  # noqa: F405
    raise ImproperlyConfigured("DEBUG=True em produção. Corrija DJANGO_DEBUG no .env.")

if "*" in ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS não pode conter '*' em produção. Use o domínio real."
    )

if not ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS vazio em produção.")

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS: ligar só depois de confirmar que o HTTPS funciona (checklist de produção)
SECURE_HSTS_SECONDS = config("DJANGO_HSTS_SECONDS", default=0, cast=int)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="")  # noqa: F405
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)  # noqa: F405
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")  # noqa: F405
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")  # noqa: F405
EMAIL_USE_TLS = True
# Sem prazo, um SMTP que trava segura o processo para sempre.
EMAIL_TIMEOUT = 10

SENTRY_DSN = config("SENTRY_DSN", default="")  # noqa: F405
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        send_default_pii=False,
        traces_sample_rate=0.1,
    )
