"""Settings comuns. `dev.py` e `prod.py` herdam e sobrescrevem."""

from pathlib import Path

import dj_database_url
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # terceiros
    "django_htmx",
    "widget_tweaks",
    # núcleo
    "apps.core",
    "apps.accounts",
    "apps.audit",
    # domínio
    "apps.organizations",
    "apps.properties",
    "apps.partners",
    "apps.livestock",
    "apps.herd",
    "apps.reproduction",
    "apps.infrastructure",
    "apps.costs",
    "apps.purchases",
    "apps.sales",
    "apps.finance",
    "apps.commercial",
    "apps.procurement",
    "apps.imports",
    "apps.reports",
    "apps.dashboards",
    "apps.documents",
    "apps.exports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.TwoFactorMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Depois das mensagens (usa `messages`) e do segundo fator (que vem primeiro).
    "apps.accounts.middleware.PasswordChangeRequiredMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.RequestContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.contexto_fixo",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default="postgres://rebanho360:rebanho360@localhost:5432/rebanho360",
        conn_max_age=60,
    )
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailOuUsuarioBackend"]

# Política de senha **liberal, de propósito** (decisão de Warley, 2026-10-03): o
# sistema é privado, o login tem limite de tentativas e o segundo fator é
# opcional, então não se exige complexidade — vale qualquer senha com 4 ou mais
# caracteres, inclusive `0000` ou `abcde`. Sem validador de semelhança com o
# usuário, de senha comum nem de senha só numérica. Para endurecer, é só
# acrescentar validadores aqui (e subir `min_length`).
SENHA_TAMANHO_MINIMO = 4
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": SENHA_TAMANHO_MINIMO},
    },
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sessão e cookies (docs/seguranca/01-seguranca.md#sessão) ---
SESSION_COOKIE_AGE = 60 * 60 * 12  # 12 horas
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"

# Link de "definir senha" (convite, aprovação, redefinição): vale 3 dias e uma vez.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 3

# --- E-mail (docs/seguranca/01) ---
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="Rebanho360 <nao-responda@localhost>"
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL
# E-mails que também recebem o aviso de solicitação de acesso, além dos
# administradores cadastrados (ex.: o do dono, que não usa o sistema).
ACCESS_REQUEST_NOTIFY_EMAILS = config(
    "ACCESS_REQUEST_NOTIFY_EMAILS", default="", cast=Csv()
)

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboards:inicio"
LOGOUT_REDIRECT_URL = "accounts:login"

# --- Cache / Celery (Redis) ---
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
# Manutenção das exportações (apps/exports): dá por interrompida a que parou no
# meio e apaga os arquivos vencidos. A cada 15 minutos basta.
CELERY_BEAT_SCHEDULE = {
    "exports-manutencao": {"task": "exports.manutencao", "schedule": 15 * 60},
}

# --- Exportação de dados (docs/regras-negocio/10-exportacao-de-dados.md) ---
# O arquivo gerado fica disponível por este prazo; depois é apagado (o pedido
# e a auditoria ficam). Pendência #45.
EXPORT_RETENTION_DAYS = config("EXPORT_RETENTION_DAYS", default=7, cast=int)
# Quantas exportações um usuário pode ter ao mesmo tempo (na fila ou rodando).
EXPORT_MAX_ACTIVE_PER_USER = config("EXPORT_MAX_ACTIVE_PER_USER", default=2, cast=int)

# --- Upload (docs/seguranca/01-seguranca.md#arquivos) ---
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50 MB (planilha)
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB (anexo)

# --- Segundo fator (F4-09, docs/seguranca/01#autenticação) ---
# TOTP **opcional**, recomendado a todos: quem ativa passa a confirmar a cada
# entrada; quem não ativa entra só com a senha. `TWO_FACTOR_ROLES` são os
# perfis sensíveis: com o segundo fator ativo, a sessão deles morre ao fechar
# o navegador.
TWO_FACTOR_ROLES = ("ADMIN", "FINANCEIRO")
# Pendência #19: o cliente ainda avalia se o segundo fator é sustentável na
# operação. Se adotar, será obrigatório para **todos** os usuários (não só
# `ADMIN` e `FINANCEIRO`): basta ligar esta variável — quem ainda não ativou é
# levado direto à configuração no próximo acesso.
TWO_FACTOR_OBRIGATORIO = config("TWO_FACTOR_OBRIGATORIO", default=False, cast=bool)
TWO_FACTOR_ISSUER = "Rebanho360"
# Passos de 30 s aceitos antes e depois do atual — tolera relógio de celular
# levemente atrasado, sem abrir a janela demais.
TWO_FACTOR_WINDOW = 1

# --- Console de auditoria (docs/regras-negocio/06) ---
AUDIT_CONSOLE_INCLUDE_GESTOR = config(
    "AUDIT_CONSOLE_INCLUDE_GESTOR", default=False, cast=bool
)

# --- Logging estruturado, sem dado sensível (F0-13) ---
from config.logging_filters import SensitiveDataFilter  # noqa: E402

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "sensitive_data": {"()": SensitiveDataFilter},
        "request_id": {"()": "apps.core.logging.RequestIdFilter"},
    },
    "formatters": {
        "json": {"()": "apps.core.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["sensitive_data", "request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        # fora do log de acesso: /health/ e /ready/ (F0-13)
        "django.server": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

# Mortalidade "acima do normal" e quebra de viagem "acima do normal" deixaram de
# existir (cliente, 2026-10-03, pendências #15 e #23): o sistema registra e
# mostra os números, mas não define o que é anormal nem gera alerta percentual.
