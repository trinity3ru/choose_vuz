"""
Тесты Telegram-алертов (этап 8): детект событий ТЗ §13.

Реальная отправка подменяется: monkeypatch send_telegram собирает тексты.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.core.database import async_session_factory
from app.models import ParserRun
from app.services import notifications, queue


@pytest.fixture(autouse=True)
async def _db(clean_db):
    yield


@pytest.fixture
def sent(monkeypatch):
    """Перехват отправки: тексты алертов складываются в список."""
    messages: list[str] = []

    async def fake_send(text: str) -> bool:
        messages.append(text)
        return True

    monkeypatch.setattr(notifications, "send_telegram", fake_send)
    return messages


async def _finished_run(
    code: str,
    status: str,
    records: int | None,
    error: str | None = None,
    created_shift_s: int = 0,
) -> ParserRun:
    """Создать завершённый запуск (created_at сдвигается для порядка)."""
    now = datetime.now(timezone.utc) + timedelta(seconds=created_shift_s)
    async with async_session_factory() as s:
        async with s.begin():
            run = ParserRun(
                university_code=code,
                parser_type="http",
                status=status,
                started_at=now - timedelta(minutes=10),
                finished_at=now,
                records_found=records,
                records_saved=records,
                error_message=error,
                created_at=now,
            )
            s.add(run)
            await s.flush()
            s.expunge(run)
            return run


async def test_failed_run_alerts(sent):
    run = await _finished_run("ITMO", "failed", 0, error="Timeout while loading page")
    await notifications.notify_run_finished(run.id)
    assert len(sent) == 1
    assert "ошибка парсера" in sent[0]
    assert "ITMO" in sent[0]
    assert "Timeout" in sent[0]


async def test_partial_run_alerts(sent):
    run = await _finished_run("GUAP", "partial", 500, error="Направление 03.03.01: пусто")
    await notifications.notify_run_finished(run.id)
    assert len(sent) == 1
    assert "частичный" in sent[0]


async def test_zero_records_alerts(sent):
    run = await _finished_run("ITMO", "success", 0)
    await notifications.notify_run_finished(run.id)
    assert len(sent) == 1
    assert "ни одной записи" in sent[0]


async def test_records_drop_alerts(sent):
    await _finished_run("ITMO", "success", 1000, created_shift_s=-60)
    run = await _finished_run("ITMO", "success", 400)  # -60% >= порога 50%
    await notifications.notify_run_finished(run.id)
    assert len(sent) == 1
    assert "резкое падение" in sent[0]
    assert "1000" in sent[0] and "400" in sent[0]


async def test_small_drop_is_quiet(sent):
    await _finished_run("ITMO", "success", 1000, created_shift_s=-60)
    run = await _finished_run("ITMO", "success", 800)  # -20% < порога
    await notifications.notify_run_finished(run.id)
    assert sent == []


async def test_first_success_without_baseline_is_quiet(sent):
    run = await _finished_run("ITMO", "success", 4000)
    await notifications.notify_run_finished(run.id)
    assert sent == []


async def test_worker_interrupted_alert(sent):
    run = await _finished_run("SPBSTU", "failed", None, error="worker interrupted")
    await notifications.notify_worker_interrupted([run])
    assert len(sent) == 1
    assert "worker прерван" in sent[0]
    assert "SPBSTU" in sent[0]


async def test_stale_alert_lists_universities(sent):
    await notifications.notify_stale(
        [
            {"code": "ITMO", "age_hours": 30.5},
            {"code": "GUAP", "age_hours": None},
        ]
    )
    assert len(sent) == 1
    assert "данные устарели" in sent[0]
    assert "ITMO" in sent[0] and "GUAP" in sent[0]
    assert "никогда" in sent[0]


async def test_stale_alert_empty_is_quiet(sent):
    await notifications.notify_stale([])
    assert sent == []


async def test_send_telegram_disabled_returns_false(monkeypatch):
    """Реальная send_telegram с выключенными алертами — тихий пропуск."""
    monkeypatch.setattr(settings, "telegram_alerts_enabled", False)
    assert await notifications.send_telegram("test") is False
