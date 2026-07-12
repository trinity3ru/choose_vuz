"""
Отчёт о состоянии парсеров (health) по данным parser_runs.

Единая логика для GET /api/v1/parser/health и CLI check-parser-health
(почасовой systemd-таймер): по каждому включённому вузу — когда данные
обновлялись в последний раз и не устарели ли они (stale).

Правила:
- «данные обновлены» = последний запуск со status in (success, partial)
  и records_saved > 0 (partial тоже сохраняет строки);
- is_stale = такого запуска не было дольше PARSER_STALE_HOURS
  (или не было вообще);
- last_run_status/last_error — по последнему НЕ-queued запуску (running
  учитывается: видно, что парсер работает прямо сейчас).

Модуль DB-only: парсеры не импортируются (работает в api-образе).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config_loader import load_config
from app.models import ParserRun

logger = logging.getLogger(__name__)


async def _university_health(
    session: AsyncSession, code: str, name: str, now: datetime
) -> dict:
    """Собрать состояние одного вуза."""
    last_success = (
        await session.execute(
            select(ParserRun)
            .where(
                ParserRun.university_code == code,
                ParserRun.status.in_(("success", "partial")),
                ParserRun.records_saved > 0,
            )
            .order_by(ParserRun.finished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    last_run = (
        await session.execute(
            select(ParserRun)
            .where(
                ParserRun.university_code == code,
                ParserRun.status != "queued",
            )
            .order_by(ParserRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    age_hours: float | None = None
    if last_success is not None and last_success.finished_at is not None:
        age_hours = (now - last_success.finished_at).total_seconds() / 3600

    is_stale = age_hours is None or age_hours > settings.parser_stale_hours

    return {
        "code": code,
        "name": name,
        "last_success_at": (
            last_success.finished_at.isoformat()
            if last_success and last_success.finished_at
            else None
        ),
        "last_run_status": last_run.status if last_run else None,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "is_stale": is_stale,
        "records_found": last_success.records_found if last_success else None,
        "records_saved": last_success.records_saved if last_success else None,
        "last_error": last_run.error_message if last_run else None,
    }


async def build_health_report(session: AsyncSession) -> dict:
    """
    Отчёт по всем включённым вузам (формат ТЗ §10.1).

    status: "ok" — все данные свежие, "stale" — есть устаревшие вузы.
    """
    now = datetime.now(timezone.utc)
    config = load_config()

    universities = [
        await _university_health(session, uni.code, uni.name, now)
        for uni in config.universities
        if uni.enabled
    ]

    any_stale = any(u["is_stale"] for u in universities)
    return {
        "status": "stale" if any_stale else "ok",
        "generated_at": now.isoformat(),
        "universities": universities,
    }
