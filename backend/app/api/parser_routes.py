"""
API-эндпоинты управления парсером и мониторинга (ТЗ §10).

ВАЖНО (прод-архитектура): API не запускает парсинг сам — он только ставит
задания в очередь parser_runs, которую разбирает отдельный worker-контейнер
(python -m app.cli consume-queue). Поэтому модуль не импортирует парсеры
и Playwright (api-образ собирается без Chromium).

- GET  /api/v1/parser/health     — состояние парсеров по каждому вузу (stale и т.д.).
- GET  /api/v1/parser/runs       — история запусков с фильтрами.
- POST /api/v1/parser/run/{code} — ручной запуск одного вуза (Bearer-токен).
- POST /api/v1/parser/start      — (deprecated) очередь всех включённых вузов.
- GET  /api/v1/parser/status     — (deprecated) статус очереди и последнего снимка.
- GET  /api/v1/config            — текущая конфигурация вузов и направлений.
"""

import logging
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config_loader import ConfigError, load_config
from app.core.database import get_session
from app.models import Applicant, ParseSnapshot, ParserRun
from app.services import queue
from app.services.health import build_health_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["parser"])


# ------------------------------------------------------- health и история --


@router.get("/parser/health")
async def parser_health(session: AsyncSession = Depends(get_session)) -> dict:
    """Состояние парсеров: свежесть данных по каждому включённому вузу."""
    return await build_health_report(session)


def _run_to_dict(run: ParserRun) -> dict:
    """Строка parser_runs для JSON-ответа."""
    return {
        "id": str(run.id),
        "university_code": run.university_code,
        "parser_type": run.parser_type,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": run.duration_seconds,
        "records_found": run.records_found,
        "records_saved": run.records_saved,
        "records_changed": run.records_changed,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/parser/runs")
async def parser_runs(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    university_code: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """История запусков парсера (новые сверху) с фильтрами ТЗ §10.2."""
    filters = []
    if university_code:
        filters.append(ParserRun.university_code == university_code.strip().upper())
    if status:
        filters.append(ParserRun.status == status)
    if date_from:
        filters.append(
            ParserRun.created_at
            >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to:
        filters.append(
            ParserRun.created_at
            <= datetime.combine(date_to, time.max, tzinfo=timezone.utc)
        )

    total = (
        await session.execute(select(func.count(ParserRun.id)).where(*filters))
    ).scalar_one()

    rows = (
        (
            await session.execute(
                select(ParserRun)
                .where(*filters)
                .order_by(ParserRun.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "runs": [_run_to_dict(r) for r in rows],
    }


# ---------------------------------------------------------- ручной запуск --


@router.post("/parser/run/{university_code}", status_code=202)
async def trigger_parser_run(
    university_code: str,
    authorization: str | None = Header(default=None),
) -> dict:
    """
    Ручной запуск парсера одного вуза (ставит задание в очередь).

    Защита Bearer-токеном (ТЗ §10.3): без токена — 401, с неверным — 403.
    Ответ 202: задание принято (или уже есть активное — дубликат не ставится).
    """
    if not settings.parser_trigger_token:
        raise HTTPException(
            status_code=503,
            detail="Ручной запуск не настроен: задайте PARSER_TRIGGER_TOKEN",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Требуется Bearer-токен")
    token = authorization.split(" ", 1)[1].strip()
    if token != settings.parser_trigger_token:
        raise HTTPException(status_code=403, detail="Неверный токен")

    try:
        code = queue.normalize_code(university_code)
    except queue.UnknownUniversityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    run = await queue.enqueue(code)
    if run is None:
        return {"status": "already_queued", "university_code": code}
    return {"status": "queued", "university_code": code, "run_id": str(run.id)}


class StartRequest(BaseModel):
    """Тело запроса на запуск. university_code опционален (один вуз)."""

    university_code: str | None = None


@router.post("/parser/start", deprecated=True)
async def start_parser(request: StartRequest | None = None) -> dict:
    """
    (deprecated: используйте POST /parser/run/{code} с токеном)

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


@router.get("/parser/status", deprecated=True)
async def parser_status(session: AsyncSession = Depends(get_session)) -> dict:
    """
    (deprecated: используйте GET /parser/health и GET /parser/runs)

    Вернуть статус очереди и последнего снимка.
    """
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
