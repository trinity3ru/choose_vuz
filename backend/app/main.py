"""
Точка входа приложения FastAPI.

При старте:
- проверяем конфигурацию (config.json) — если она битая, приложение не поднимется;
- запускаем планировщик периодического парсинга.
При остановке — корректно гасим планировщик.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.data_routes import router as data_router
from app.api.parser_routes import router as parser_router
from app.core.config import settings
from app.core.config_loader import load_config
from app.scheduler.jobs import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом: старт и остановка фоновых сервисов."""
    # Ранняя проверка конфига — падаем сразу с понятной ошибкой, если он битый.
    load_config()
    start_scheduler()
    logger.info("Приложение запущено")
    yield
    stop_scheduler()
    logger.info("Приложение остановлено")


app = FastAPI(
    title="Парсер конкурсных списков вузов",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS для фронтенда (dev-сервер Vite и т.п.).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(parser_router)
app.include_router(data_router)


@app.get("/health")
async def health() -> dict:
    """Простой health-check для проверки, что сервис жив."""
    return {"status": "ok"}
