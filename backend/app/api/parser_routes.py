"""
API-эндпоинты управления парсером.

ВАЖНО (прод-архитектура): API не запускает парсинг сам — он только ставит
задания в очередь parser_runs, которую разбирает отдельный worker-контейнер
(python -m app.cli consume-queue). Поэтому модуль не импортирует парсеры
и Playwright (api-образ собирается без Chromium).

- POST /api/v1/parser/start  — поставить в очередь все включённые вузы (или один).
- GET  /api/v1/parser/status — статус очереди и последнего снимка.
- GET  /api/v1/config        — текущая конфигурация вузов и направлений.

Расширенное health-API (/parser/health, /parser/runs, /parser/run/{code})
добавляется на этапе 4 DEPLOY_PLAN.md.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_loader import ConfigError, load_config
from app.core.database import get_session
from app.models import Applicant, ParseSnapshot
from app.services import queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["parser"])


class StartRequest(BaseModel):
    """Тело запроса на запуск. university_code опционален (один вуз)."""

    university_code: str | None = None


@router.post("/parser/start")
async def start_parser(request: StartRequest | None = None) -> dict:
    """
    Поставить парсинг в очередь. Выполнит его worker (consume-queue).

    Дубликаты не ставятся: вуз с активным заданием попадает в skipped.
    """
    if request and request.university_code:
        try:
            codes = [queue.normalize_code(request.university_code)]
        except queue.UnknownUniversityError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    else:
        codes = queue.enabled_codes()

    queued: list[str] = []
    skipped: list[str] = []
    for code in codes:
        run = await queue.enqueue(code)
        (queued if run is not None else skipped).append(code)

    return {"status": "queued", "queued": queued, "skipped": skipped}


@router.get("/parser/status")
async def parser_status(session: AsyncSession = Depends(get_session)) -> dict:
    """Вернуть статус очереди и последнего снимка."""
    stmt = select(ParseSnapshot).order_by(ParseSnapshot.created_at.desc()).limit(1)
    snapshot = (await session.execute(stmt)).scalar_one_or_none()

    is_running = await queue.is_any_active()

    if snapshot is None:
        return {"is_running": is_running, "last_snapshot": None}

    # Сколько строк абитуриентов в этом снимке.
    count_stmt = select(func.count(Applicant.id)).where(
        Applicant.snapshot_id == snapshot.id
    )
    applicants_count = (await session.execute(count_stmt)).scalar_one()

    return {
        "is_running": is_running,
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
