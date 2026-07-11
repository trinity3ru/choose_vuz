"""
Очередь запусков парсера поверх таблицы parser_runs (только БД, без парсеров).

Модуль намеренно НЕ импортирует ничего из app.parser.* и parser_runner:
его используют и API-контейнер (enqueue, health, recover), и worker (claim).
Так api-образ остаётся без Playwright (см. DEPLOY_PLAN.md, раунд D).

Гарантии:
- enqueue дедуплицирует: для вуза с активным заданием (queued/running)
  новое не ставится;
- claim_next атомарен: SELECT ... FOR UPDATE SKIP LOCKED — два воркера
  не заберут одно задание;
- recover_stuck помечает зависшие running-задачи (worker упал) как failed,
  снимая блокировку дедупликации.

Дополнительная защита от параллельного тяжёлого парсинга — advisory-lock
PostgreSQL (сессионный): его держит и consume-queue, и ручной parse-university.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_loader import load_config
from app.core.database import async_session_factory
from app.models import ParserRun

logger = logging.getLogger(__name__)

# Статусы, при которых задание вуза считается активным (дедупликация).
ACTIVE_STATUSES = ("queued", "running")

# Ключ advisory-lock PostgreSQL: «право выполнять парсинг» (одно на проект).
PARSER_ADVISORY_LOCK_KEY = 0x756E6976  # 'univ'


class UnknownUniversityError(ValueError):
    """Код вуза отсутствует в config.json."""


def normalize_code(code: str) -> str:
    """
    Привести код вуза к каноническому виду (регистронезависимо).

    :raises UnknownUniversityError: если кода нет в конфиге.
    """
    wanted = code.strip().upper()
    config = load_config()
    for uni in config.universities:
        if uni.code.upper() == wanted:
            return uni.code
    known = ", ".join(u.code for u in config.universities)
    raise UnknownUniversityError(f"неизвестный код вуза '{code}' (есть: {known})")


def parser_type_of(code: str) -> str:
    """Тип парсера вуза из конфига (http / playwright)."""
    config = load_config()
    for uni in config.universities:
        if uni.code == code:
            return uni.parser_type
    raise UnknownUniversityError(f"неизвестный код вуза '{code}'")


def enabled_codes() -> list[str]:
    """Коды всех включённых вузов из config.json."""
    return [u.code for u in load_config().universities if u.enabled]


async def enqueue(code: str, session: AsyncSession | None = None) -> ParserRun | None:
    """
    Поставить задание в очередь (дедупликация по активным заданиям вуза).

    :return: созданный ParserRun или None, если задание уже есть.
    """
    canonical = normalize_code(code)

    async def _do(s: AsyncSession) -> ParserRun | None:
        active = await s.execute(
            select(ParserRun.id)
            .where(
                ParserRun.university_code == canonical,
                ParserRun.status.in_(ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if active.scalar_one_or_none() is not None:
            logger.info("enqueue %s: пропуск, задание уже в очереди/работе", canonical)
            return None

        run = ParserRun(
            university_code=canonical,
            parser_type=parser_type_of(canonical),
            status="queued",
        )
        s.add(run)
        await s.flush()
        return run

    if session is not None:
        return await _do(session)

    async with async_session_factory() as s:
        async with s.begin():
            run = await _do(s)
        return run


async def claim_next() -> ParserRun | None:
    """
    Атомарно забрать самое старое задание из очереди (для worker).

    FOR UPDATE SKIP LOCKED: параллельный воркер не получит ту же строку.
    """
    async with async_session_factory() as s:
        async with s.begin():
            stmt = (
                select(ParserRun)
                .where(ParserRun.status == "queued")
                .order_by(ParserRun.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            run = (await s.execute(stmt)).scalar_one_or_none()
            if run is None:
                return None
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            await s.flush()
            # Данные пригодятся после закрытия сессии.
            s.expunge(run)
            return run


async def start_direct_run(code: str) -> ParserRun:
    """
    Создать запись running для прямого запуска (parse-university/parse-all),
    минуя очередь. Дедупликации нет — от параллельности защищает advisory-lock.
    """
    canonical = normalize_code(code)
    async with async_session_factory() as s:
        async with s.begin():
            run = ParserRun(
                university_code=canonical,
                parser_type=parser_type_of(canonical),
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            s.add(run)
            await s.flush()
            s.expunge(run)
            return run


async def finalize(
    run_id: uuid.UUID,
    status: str,
    records_found: int | None = None,
    records_saved: int | None = None,
    records_changed: int | None = None,
    error_message: str | None = None,
    log_path: str | None = None,
    screenshot_path: str | None = None,
) -> None:
    """Записать итоги запуска (finished_at и duration считаются здесь)."""
    now = datetime.now(timezone.utc)
    async with async_session_factory() as s:
        async with s.begin():
            run = (
                await s.execute(select(ParserRun).where(ParserRun.id == run_id))
            ).scalar_one()
            run.status = status
            run.finished_at = now
            if run.started_at is not None:
                run.duration_seconds = (now - run.started_at).total_seconds()
            run.records_found = records_found
            run.records_saved = records_saved
            run.records_changed = records_changed
            run.error_message = error_message
            run.log_path = log_path
            run.screenshot_path = screenshot_path


async def recover_stuck(older_than_minutes: int) -> list[ParserRun]:
    """
    Пометить зависшие running-задачи как failed («worker interrupted»).

    Возвращает список восстановленных задач (для алертов).
    """
    threshold = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    async with async_session_factory() as s:
        async with s.begin():
            stuck = (
                (
                    await s.execute(
                        select(ParserRun).where(
                            ParserRun.status == "running",
                            ParserRun.started_at.is_not(None),
                            ParserRun.started_at < threshold,
                        )
                    )
                )
                .scalars()
                .all()
            )
            now = datetime.now(timezone.utc)
            for run in stuck:
                run.status = "failed"
                run.finished_at = now
                run.error_message = "worker interrupted"
                if run.started_at is not None:
                    run.duration_seconds = (now - run.started_at).total_seconds()
            # Сначала flush (иначе expunge отменит несохранённые изменения).
            await s.flush()
            for run in stuck:
                s.expunge(run)
            return list(stuck)


async def is_any_active() -> bool:
    """Есть ли сейчас активные задания (queued/running)."""
    async with async_session_factory() as s:
        row = await s.execute(
            select(ParserRun.id).where(ParserRun.status.in_(ACTIVE_STATUSES)).limit(1)
        )
        return row.scalar_one_or_none() is not None


async def try_advisory_lock(session: AsyncSession) -> bool:
    """
    Взять сессионный advisory-lock PostgreSQL (вторая защита после flock).

    Лок держится, пока жива сессия/соединение — держите сессию открытой
    на всё время парсинга и вызовите release_advisory_lock в конце.
    """
    # pg_try_advisory_lock возвращает bool сразу, без ожидания.
    row = await session.execute(select(func.pg_try_advisory_lock(PARSER_ADVISORY_LOCK_KEY)))
    return bool(row.scalar())


async def release_advisory_lock(session: AsyncSession) -> None:
    """Отпустить advisory-lock (парная к try_advisory_lock)."""
    await session.execute(select(func.pg_advisory_unlock(PARSER_ADVISORY_LOCK_KEY)))
