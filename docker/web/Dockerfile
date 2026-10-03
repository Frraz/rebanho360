# Imagem única para web/worker/beat, em dev e produção — só muda o
# comando (docker-compose.yml vs docker-compose.prod.yml).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Libs de runtime: libpq (Postgres), libs do WeasyPrint (Pango/Cairo/GDK-Pixbuf)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
        libffi8 shared-mime-info fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements/ requirements/

# --- estágio dev: inclui ferramentas de desenvolvimento, sem build de CSS/collectstatic ---
FROM base AS dev
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && pip install -r requirements/dev.txt \
    && apt-get purge -y build-essential libpq-dev && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
COPY . .
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# --- estágio prod: build do Tailwind, collectstatic, Gunicorn ---
FROM base AS prod
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && pip install -r requirements/prod.txt \
    && apt-get purge -y build-essential libpq-dev && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
COPY . .

# Variáveis só para o build (collectstatic não toca banco, mas prod.py
# recusa importar sem SECRET_KEY/ALLOWED_HOSTS válidos) — substituídas em
# runtime pelo .env real via docker-compose.prod.yml.
ENV DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=build-time-placeholder \
    DJANGO_DEBUG=False \
    DJANGO_ALLOWED_HOSTS=build.invalid

RUN sh bin/build_css.sh \
    && python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
