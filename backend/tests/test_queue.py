"""
Тесты очереди parser_runs (app/services/queue.py) против реальной PostgreSQL.

Нужна тестовая база (TEST_DATABASE_URL, по умолчанию univer_parser_test на
localhost:5544 из dev-контейнера). Если базы нет — тесты пропускаются.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.core.database import Base, async_session_factory, engine
from app.models import ParserRun
from app.services import queue


@pytest.fixture(autouse=True)
async def clean_db():
    """Схема + чистая таблица parser_runs (skip, если PostgreSQL недоступна)."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_session_factory() as s:
            async with s.begin():
                await s.execute(delete(ParserRun))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"тестовая PostgreSQL недоступна: {exc}")
    yield
    # У каждого теста свой event loop: сбрасываем пул соединений engine,
    # иначе следующий тест получит соединение из «мёртвого» цикла.
    await engine.dispose()


async def _get_run(run_id) -> ParserRun:
    async with async_session_factory() as s:
        return (
            await s.execute(select(ParserRun).where(ParserRun.id == run_id))
        ).scalar_one()


# ----------------------------------------------------------- normalize --


def test_normalize_code_case_insensitive():
    assert queue.normalize_code("spbstu") == "SPBSTU"
    assert queue.normalize_code("  Itmo ") == "ITMO"


def test_normalize_code_unknown_raises():
    with pytest.raises(queue.UnknownUniversityError):
        queue.normalize_code("NOPE")


def test_parser_type_of():
    assert queue.parser_type_of("SPBSTU") == "playwright"
    assert queue.parser_type_of("ITMO") == "http"


# -------------------------------------------------------------- queue --


async def test_enqueue_and_dedup():
    run = await queue.enqueue("itmo")  # регистронезависимо
    assert run is not None
    assert run.university_code == "ITMO"
    assert run.parser_type == "http"

    # Дубликат при активном задании не ставится.
    assert await queue.enqueue("ITMO") is None
    # Другой вуз ставится независимо.
    assert (await queue.enqueue("GUAP")) is not None


async def test_claim_is_fifo_and_marks_running():
    first = await queue.enqueue("ITMO")
    second = await queue.enqueue("GUAP")
    assert first and second

    claimed = await queue.claim_next()
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == "running"
    assert claimed.started_at is not None

    claimed2 = await queue.claim_next()
    assert claimed2 is not None and claimed2.id == second.id

    # Очередь пуста.
    assert await queue.claim_next() is None


async def test_finalize_writes_results():
    run = await queue.enqueue("ITMO")
    claimed = await queue.claim_next()
    assert claimed is not None

    await queue.finalize(
        claimed.id,
        status="success",
        records_found=100,
        records_saved=100,
        records_changed=None,
    )

    stored = await _get_run(claimed.id)
    assert stored.status == "success"
    assert stored.records_saved == 100
    assert stored.finished_at is not None
    assert stored.duration_seconds is not None and stored.duration_seconds >= 0


async def test_recover_stuck_marks_failed_and_unblocks_dedup():
    run = await queue.enqueue("ITMO")
    claimed = await queue.claim_next()
    assert claimed is not None

    # Состарим задачу вручную: started_at 4 часа назад.
    async with async_session_factory() as s:
        async with s.begin():
            obj = (
                await s.execute(select(ParserRun).where(ParserRun.id == claimed.id))
            ).scalar_one()
            obj.started_at = datetime.now(timezone.utc) - timedelta(hours=4)

    recovered = await queue.recover_stuck(older_than_minutes=180)
    assert [r.id for r in recovered] == [claimed.id]

    stored = await _get_run(claimed.id)
    assert stored.status == "failed"
    assert stored.error_message == "worker interrupted"

    # Свежая running-задача не трогается.
    fresh = await queue.enqueue("GUAP")
    fresh_claimed = await queue.claim_next()
    assert not await queue.recover_stuck(older_than_minutes=180)

    # Дедуп разблокирован: ITMO снова можно поставить.
    assert (await queue.enqueue("ITMO")) is not None


async def test_is_any_active():
    assert await queue.is_any_active() is False
    await queue.enqueue("ITMO")
    assert await queue.is_any_active() is True


async def test_advisory_lock_exclusive():
    async with async_session_factory() as s1, async_session_factory() as s2:
        assert await queue.try_advisory_lock(s1) is True
        # Вторая сессия лок не получает.
        assert await queue.try_advisory_lock(s2) is False
        await queue.release_advisory_lock(s1)
        assert await queue.try_advisory_lock(s2) is True
        await queue.release_advisory_lock(s2)


# ---------------------------------------------------------------- CLI --


async def test_cli_consume_queue_once_empty(capsys):
    """consume-queue --once на пустой очереди: exit 0, парсеры не нужны."""
    from app.cli import EXIT_OK, cmd_consume_queue

    class Args:
        once = True

    assert await cmd_consume_queue(Args()) == EXIT_OK
    assert "queue empty" in capsys.readouterr().out


async def test_cli_enqueue_and_recover(capsys):
    from app.cli import EXIT_OK, cmd_enqueue, cmd_recover_stuck

    class Args:
        code = "itmo"

    assert await cmd_enqueue(Args()) == EXIT_OK
    out = capsys.readouterr().out
    assert "queued: ITMO" in out

    # Повторная постановка — skipped, но код выхода 0.
    assert await cmd_enqueue(Args()) == EXIT_OK
    assert "skipped" in capsys.readouterr().out

    class NoArgs:
        pass

    assert await cmd_recover_stuck(NoArgs()) == EXIT_OK


async def test_cli_check_parser_health_reports_stale(capsys):
    """Без единого успешного запуска все вузы stale -> exit 2."""
    from app.cli import EXIT_PARTIAL, cmd_check_parser_health

    class Args:
        pass

    code = await cmd_check_parser_health(Args())
    assert code == EXIT_PARTIAL
    out = capsys.readouterr().out
    assert '"is_stale": true' in out


def test_cli_exit_code_mapping():
    from app.cli import EXIT_ERROR, EXIT_OK, EXIT_PARTIAL, _summary_to_exit_code

    assert _summary_to_exit_code("success") == EXIT_OK
    assert _summary_to_exit_code("partial") == EXIT_PARTIAL
    assert _summary_to_exit_code("failed") == EXIT_ERROR


def test_cli_has_all_commands():
    from app.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    commands = set(sub.choices.keys())
    assert commands == {
        "enqueue",
        "consume-queue",
        "parse-university",
        "parse-all",
        "recover-stuck-runs",
        "check-parser-health",
        "cleanup-snapshots",
    }