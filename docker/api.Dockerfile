# API-контейнер VuzFinder: лёгкий FastAPI без Playwright/Chromium (ТЗ §7).
#
# Сборка из корня репозитория:
#   docker build -f docker/api.Dockerfile -t university-api .

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Зависимости отдельно от кода — кэш слоя переживает правки кода.
COPY backend/requirements-base.txt backend/requirements-api.txt ./
RUN pip install -r requirements-api.txt

# Код приложения, миграции и конфигурация вузов.
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini backend/config.json ./

# Непривилегированный пользователь (ТЗ §20).
RUN useradd --create-home --uid 10001 apiuser
USER apiuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
