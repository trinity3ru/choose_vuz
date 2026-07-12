# Worker-контейнер VuzFinder: парсеры, Playwright + Chromium (ТЗ §8).
#
# База — официальный образ Playwright (браузеры и системные библиотеки
# уже внутри, версия совпадает с requirements-worker.txt).
#
# Контейнер живёт в цикле consume-queue под flock: lock-файл лежит на
# bind-mount ./locks:/var/lock/university (общий на хосте), поэтому даже
# случайно поднятый второй worker-контейнер не начнёт парсить параллельно.
#
# Сборка из корня репозитория:
#   docker build -f docker/worker.Dockerfile -t university-worker .

FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# flock — явно (не полагаемся на базовый образ), см. DEPLOY_PLAN раунд C/D.
RUN apt-get update \
    && apt-get install -y --no-install-recommends util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements-base.txt backend/requirements-worker.txt ./
RUN pip install -r requirements-worker.txt

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini backend/config.json ./

# Каталоги логов/скриншотов (в проде поверх них монтируются bind-тома).
RUN mkdir -p /app/logs /app/screenshots /var/lock/university

# Одно задание за раз; lock-файл общий с хостом (bind mount).
CMD ["/bin/bash", "-c", "mkdir -p /var/lock/university && exec flock -n /var/lock/university/parser.lock python -m app.cli consume-queue"]
