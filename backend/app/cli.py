"""
CLI парсера: python -m app.cli <команда>.

Команды делятся на два класса (см. DEPLOY_PLAN.md, раунд D):

DB-only (работают в api-образе, парсеры НЕ импортируются):
    enqueue <code>        — поставить вуз в очередь parser_runs;
    recover-stuck-runs    — пометить зависшие running-задачи как failed;
    check-parser-health   — проверка свежести данных (stale) по каждому вузу;
    cleanup-snapshots     — удалить снимки старше SNAPSHOT_RETENTION_DAYS.

Парсящие (только worker-образ; parser_runner импортируется лениво):
    consume-queue [--once] — вечный цикл воркера: забирать задания и выполнять;
    parse-university <code> — прямой запуск одного вуза (с advisory-lock);
    parse-all              — прямой запуск всех включённых вузов по очереди.

Коды выхода: 0 — успех, 1 — ошибка, 2 — частичный/подозрительный результат.
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone

from app.core.config import settings
from app.services import queue

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PARTIAL = 2


# --------------------------------------------------------------- helpers --


def _summary_to_exit_code(status: str) -> int:
    """Статус запуска -> код выхода процесса."""
    if status == "success":
        return EXIT_OK
    if status == "partial":
        return EXIT_PARTIAL
    return EXIT_ERROR


async def _run_one_with_tracking(code: str) -> str:
    """
    Выполнить парсинг вуза с записью жизненного цикла в parser_runs.

    Возвращает итоговый статус (success/partial/failed).
    Используется прямыми командами (parse-university/parse-all).
    """
    # Ленивый импорт: parser_runner тянет все парсеры (включая Playwright).
    from app.services import parser_runner

    run = await queue.start_direct_run(code)
    try:
        summary = await parser_runner.run_university(run.university_code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Запуск %s упал", code)
        await queue.finalize(run.id, "failed", error_message=str(exc)[:2000])
        return "failed"

    await queue.finalize(
        run.id,
        status=summary["status"],
        records_found=summary["records_found"],
        records_saved=summary["records_saved"],
        error_message="\n".join(summary["errors"])[:2000] or None,
    )
    logger.info(
        "%s: %s, направлений=%d, записей=%d",
        code,
        summary["status"],
        summary["majors_parsed"],
        summary["records_saved"],
    )
    return summary["status"]


async def _execute_claimed(run) -> str:
    """Выполнить уже забранное из очереди задание (consume-queue)."""
    from app.services import parser_runner

    try:
        summary = await parser_runner.run_university(run.university_code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Задание %s (%s) упало", run.id, run.university_code)
        await queue.finalize(run.id, "failed", error_message=str(exc)[:2000])
        return "failed"

    await queue.finalize(
        run.id,
        status=summary["status"],
        records_found=summary["records_found"],
        records_saved=summary["records_saved"],
        error_message="\n".join(summary["errors"])[:2000] or None,
    )
    return summary["status"]


# -------------------------------------------------------------- commands --


async def cmd_enqueue(args: argparse.Namespace) -> int:
    """Поставить вуз в очередь (DB-only, работает в api-образе)."""
    run = await queue.enqueue(args.code)
    if run is None:
        print(f"skipped: у вуза уже есть активное задание")
        return EXIT_OK
    print(f"queued: {run.university_code} (run_id={run.id})")
    return EXIT_OK


async def cmd_consume_queue(args: argparse.Namespace) -> int:
    """
    Вечный цикл воркера: восстановить зависшие, затем забирать задания.

    --once: обработать не более одного задания и выйти (для тестов/отладки).
    """
    stopping = False

    def _stop(signum, frame):  # noqa: ANN001
        nonlocal stopping
        stopping = True
        logger.info("Получен сигнал %s — завершаю после текущего задания", signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except ValueError:  # не главный поток (тесты)
            pass

    # Зависшие с прошлого падения воркера.
    recovered = await queue.recover_stuck(settings.parser_stuck_minutes)
    for run in recovered:
        logger.warning("Восстановлено зависшее задание %s (%s)", run.id, run.university_code)

    logger.info("consume-queue: старт (poll=%d сек)", settings.queue_poll_seconds)
    while not stopping:
        run = await queue.claim_next()
        if run is None:
            if args.once:
                print("queue empty")
                return EXIT_OK
            await asyncio.sleep(settings.queue_poll_seconds)
            continue

        logger.info("Задание %s: парсинг %s", run.id, run.university_code)
        status = await _execute_claimed(run)
        print(f"{run.university_code}: {status}")
        if args.once:
            return _summary_to_exit_code(status)

    return EXIT_OK


async def cmd_parse_university(args: argparse.Namespace) -> int:
    """Прямой запуск одного вуза (advisory-lock защищает от параллельности)."""
    from app.core.database import async_session_factory

    code = queue.normalize_code(args.code)

    async with async_session_factory() as lock_session:
        if not await queue.try_advisory_lock(lock_session):
            print("другой парсинг уже выполняется (advisory lock занят)", file=sys.stderr)
            return EXIT_ERROR
        try:
            status = await _run_one_with_tracking(code)
        finally:
            await queue.release_advisory_lock(lock_session)

    print(f"{code}: {status}")
    return _summary_to_exit_code(status)


async def cmd_parse_all(args: argparse.Namespace) -> int:
    """Прямой запуск всех включённых вузов последовательно."""
    from app.core.database import async_session_factory

    async with async_session_factory() as lock_session:
        if not await queue.try_advisory_lock(lock_session):
            print("другой парсинг уже выполняется (advisory lock занят)", file=sys.stderr)
            return EXIT_ERROR
        try:
            statuses: list[str] = []
            for code in queue.enabled_codes():
                status = await _run_one_with_tracking(code)
                statuses.append(status)
                print(f"{code}: {status}")
        finally:
            await queue.release_advisory_lock(lock_session)

    if all(s == "success" for s in statuses):
        return EXIT_OK
    if all(s == "failed" for s in statuses):
        return EXIT_ERROR
    return EXIT_PARTIAL


async def cmd_recover_stuck(args: argparse.Namespace) -> int:
    """Пометить зависшие running-задачи как failed (DB-only)."""
    recovered = await queue.recover_stuck(settings.parser_stuck_minutes)
    for run in recovered:
        print(f"recovered: {run.university_code} (run_id={run.id})")
    print(f"total: {len(recovered)}")
    return EXIT_OK


async def cmd_check_parser_health(args: argparse.Namespace) -> int:
    """
    Проверка свежести данных по каждому включённому вузу (DB-only).

    Выводит JSON; exit 2 — есть stale-вузы, 0 — все данные свежие.
    (Telegram-уведомления подключаются на этапе 8 плана.)
    """
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.models import ParserRun

    now = datetime.now(timezone.utc)
    report: list[dict] = []
    any_stale = False

    async with async_session_factory() as s:
        for code in queue.enabled_codes():
            # Последний запуск, обновивший данные: success или partial с записями.
            last_success = (
                await s.execute(
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
                await s.execute(
                    select(ParserRun)
                    .where(
                        ParserRun.university_code == code,
                        ParserRun.status.not_in(("queued",)),
                    )
                    .order_by(ParserRun.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            age_hours: float | None = None
            if last_success is not None and last_success.finished_at is not None:
                age_hours = (now - last_success.finished_at).total_seconds() / 3600

            is_stale = age_hours is None or age_hours > settings.parser_stale_hours
            any_stale = any_stale or is_stale

            report.append(
                {
                    "code": code,
                    "last_success_at": (
                        last_success.finished_at.isoformat()
                        if last_success and last_success.finished_at
                        else None
                    ),
                    "last_run_status": last_run.status if last_run else None,
                    "age_hours": round(age_hours, 1) if age_hours is not None else None,
                    "is_stale": is_stale,
                    "last_error": last_run.error_message if last_run else None,
                }
            )

    print(json.dumps({"generated_at": now.isoformat(), "universities": report},
                     ensure_ascii=False, indent=2))
    return EXIT_PARTIAL if any_stale else EXIT_OK


async def cmd_cleanup_snapshots(args: argparse.Namespace) -> int:
    """Удалить снимки старше SNAPSHOT_RETENTION_DAYS (и их строки) — DB-only."""
    from datetime import timedelta

    from sqlalchemy import delete, select

    from app.core.database import async_session_factory
    from app.models import Applicant, MajorStats, ParseSnapshot

    threshold = datetime.now(timezone.utc) - timedelta(days=settings.snapshot_retention_days)

    async with async_session_factory() as s:
        async with s.begin():
            old_ids = (
                (await s.execute(select(ParseSnapshot.id).where(ParseSnapshot.created_at < threshold)))
                .scalars()
                .all()
            )
            if not old_ids:
                print("nothing to clean")
                return EXIT_OK
            # Сначала дочерние строки, затем сами снимки (FK без ondelete).
            await s.execute(delete(Applicant).where(Applicant.snapshot_id.in_(old_ids)))
            await s.execute(delete(MajorStats).where(MajorStats.snapshot_id.in_(old_ids)))
            await s.execute(delete(ParseSnapshot).where(ParseSnapshot.id.in_(old_ids)))

    print(f"deleted snapshots: {len(old_ids)} (older than {settings.snapshot_retention_days} d)")
    return EXIT_OK


# ------------------------------------------------------------------ main --


def build_parser() -> argparse.ArgumentParser:
    """Собрать argparse-парсер команд."""
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("enqueue", help="поставить вуз в очередь")
    p.add_argument("code", help="код вуза (регистронезависимо), напр. spbstu")
    p.set_defaults(func=cmd_enqueue)

    p = sub.add_parser("consume-queue", help="цикл воркера: выполнять задания очереди")
    p.add_argument("--once", action="store_true", help="обработать одно задание и выйти")
    p.set_defaults(func=cmd_consume_queue)

    p = sub.add_parser("parse-university", help="прямой запуск одного вуза")
    p.add_argument("code", help="код вуза (регистронезависимо)")
    p.set_defaults(func=cmd_parse_university)

    p = sub.add_parser("parse-all", help="прямой запуск всех включённых вузов")
    p.set_defaults(func=cmd_parse_all)

    p = sub.add_parser("recover-stuck-runs", help="пометить зависшие running как failed")
    p.set_defaults(func=cmd_recover_stuck)

    p = sub.add_parser("check-parser-health", help="проверка свежести данных (stale)")
    p.set_defaults(func=cmd_check_parser_health)

    p = sub.add_parser("cleanup-snapshots", help="удалить старые снимки (retention)")
    p.set_defaults(func=cmd_cleanup_snapshots)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    except queue.UnknownUniversityError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
