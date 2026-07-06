"""
API-эндпоинты управления парсером.

- POST /api/v1/parser/start  — запустить парсинг (в фоне), опц. одно направление.
- GET  /api/v1/parser/status — статус последнего запуска и признак работы сейчас.
- GET  /api/v1/config        — текущая конфигурация вузов и направлений.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_loader import ConfigError, load_config
from app.core.database import get_session
from app.models import Applicant, ParseSnapshot
from app.services import parser_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["parser"])


class StartRequest(BaseModel):
    """Тело запроса на запуск парсинга. major_code опционален."""

    major_code: str | None = None


@router.post("/parser/start")
async def start_parser(request: StartRequest | None = None) -> dict:
    """Запустить парсинг в фоне. Если парсинг уже идёт — вернуть 409."""
    # Занимаем парсер синхронно (без await), поэтому две быстрые попытки
    # запуска не могут обе пройти — вторая честно получит 409.
    if not parser_runner.try_begin():
        raise HTTPException(status_code=409, detail="Парсинг уже выполняется")

    major_code = request.major_code if request else None

    # Запускаем в фоне: HTTP-ответ не ждёт окончания долгого парсинга.
    asyncio.create_task(_run_safe(major_code))

    return {"status": "started", "major_code": major_code}


async def _run_safe(major_code: str | None) -> None:
    """
    Фоновый запуск: флаг уже занят в эндпоинте, поэтому вызываем execute()
    напрямую и обязательно освобождаем флаг в конце.
    """
    try:
        await parser_runner.execute(major_code)
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка фонового парсинга")
    finally:
        parser_runner.end()


@router.get("/parser/status")
async def parser_status(session: AsyncSession = Depends(get_session)) -> dict:
    """Вернуть статус последнего снимка и признак текущей работы парсера."""
    stmt = select(ParseSnapshot).order_by(ParseSnapshot.created_at.desc()).limit(1)
    snapshot = (await session.execute(stmt)).scalar_one_or_none()

    if snapshot is None:
        return {"is_running": parser_runner.is_running(), "last_snapshot": None}

    # Сколько строк абитуриентов в этом снимке.
    count_stmt = select(func.count(Applicant.id)).where(
        Applicant.snapshot_id == snapshot.id
    )
    applicants_count = (await session.execute(count_stmt)).scalar_one()

    return {
        "is_running": parser_runner.is_running(),
        "last_snapshot": {
            "id": str(snapshot.id),
            "created_at": snapshot.created_at.isoformat(),
            "status": snapshot.status,
            "applicants_count": applicants_count,
            "error_log": snapshot.error_log,
        },
    }


@router.get("/config")
async def get_config() -> dict:
    """Вернуть текущую конфигурацию (config.json)."""
    try:
        config = load_config()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return config.model_dump(mode="json")
