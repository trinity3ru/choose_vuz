"""
Тесты health-API (этап 4): /parser/health, /parser/runs, /parser/run/{code}.

Приложение гоняется in-process через httpx.ASGITransport (без сети и uvicorn),
БД — тестовая PostgreSQL (conftest.clean_db).
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.main import app
from app.models import ParserRun
from app.services import queue

TOKEN = "test-trigger-token"


@pytest.fixture(autouse=True)
async def _db(clean_db):
    yield


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    """Настроенный PARSER_TRIGGER_TOKEN для ручного запуска."""
    monkeypatch.setattr(settings, "parser_trigger_token", TOKEN)


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _finished_run(
    code: str,
    status: str = "success",
    records: int = 100,
    finished_ago_hours: float = 1.0,
    error: str | None = None,
) -> ParserRun:
    """Создать завершённый запуск в parser_runs (минуя парсер)."""
    now = datetime.now(timezone.utc)
    async with async_session_factory() as s:
        async with s.begin():
            run = ParserRun(
                university_code=code,
                parser_type=queue.parser_type_of(code),
                status=status,
                started_at=now - timedelta(hours=finished_ago_hours, minutes=10),
                finished_at=now - timedelta(hours=finished_ago_hours),
                records_found=records,
                records_saved=records,
                error_message=error,
            )
            s.add(run)
            await s.flush()
            s.expunge(run)
            return run


# ------------------------------------------------------------- /health --


async def test_health_all_stale_without_runs(client):
    resp = await client.get("/api/v1/parser/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "stale"
    # Все включённые вузы из config.json, каждый stale (запусков ещё не было).
    assert len(data["universities"]) >= 13
    assert all(u["is_stale"] for u in data["universities"])


async def test_health_fresh_after_success(client):
    await _finished_run("ITMO", records=4151, finished_ago_hours=1)
    resp = await client.get("/api/v1/parser/health")
    data = resp.json()

    itmo = next(u for u in data["universities"] if u["code"] == "ITMO")
    assert itmo["is_stale"] is False
    assert itmo["records_saved"] == 4151
    assert itmo["last_run_status"] == "success"
    assert 0.5 < itmo["age_hours"] < 2
    # Остальные вузы всё ещё stale -> общий статус stale.
    assert data["status"] == "stale"


async def test_health_old_success_is_stale(client):
    await _finished_run("ITMO", finished_ago_hours=30)  # старше PARSER_STALE_HOURS=24
    resp = await client.get("/api/v1/parser/health")
    itmo = next(u for u in resp.json()["universities"] if u["code"] == "ITMO")
    assert itmo["is_stale"] is True


async def test_health_failed_run_keeps_stale_and_shows_error(client):
    await _finished_run("GUAP", status="failed", records=0, error="Timeout while loading")
    resp = await client.get("/api/v1/parser/health")
    guap = next(u for u in resp.json()["universities"] if u["code"] == "GUAP")
    assert guap["is_stale"] is True
    assert guap["last_run_status"] == "failed"
    assert "Timeout" in guap["last_error"]


# --------------------------------------------------------------- /runs --


async def test_runs_filters_and_pagination(client):
    await _finished_run("ITMO", status="success", finished_ago_hours=3)
    await _finished_run("ITMO", status="failed", finished_ago_hours=2, records=0)
    await _finished_run("GUAP", status="success", finished_ago_hours=1)

    resp = await client.get("/api/v1/parser/runs")
    data = resp.json()
    assert data["total"] == 3
    assert len(data["runs"]) == 3

    # Фильтр по вузу (регистронезависимый).
    resp = await client.get("/api/v1/parser/runs", params={"university_code": "itmo"})
    data = resp.json()
    assert data["total"] == 2
    assert all(r["university_code"] == "ITMO" for r in data["runs"])

    # Фильтр по статусу.
    resp = await client.get("/api/v1/parser/runs", params={"status": "failed"})
    assert resp.json()["total"] == 1

    # Пагинация.
    resp = await client.get("/api/v1/parser/runs", params={"limit": 1, "offset": 1})
    data = resp.json()
    assert data["total"] == 3
    assert len(data["runs"]) == 1

    # Диапазон дат: завтра -> пусто.
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    resp = await client.get("/api/v1/parser/runs", params={"date_from": tomorrow})
    assert resp.json()["total"] == 0


# --------------------------------------------------------- /run/{code} --


async def test_trigger_requires_token(client):
    resp = await client.post("/api/v1/parser/run/itmo")
    assert resp.status_code == 401


async def test_trigger_rejects_wrong_token(client):
    resp = await client.post(
        "/api/v1/parser/run/itmo", headers={"Authorization": "Bearer wrong"}
    )
    assert resp.status_code == 403


async def test_trigger_unknown_university(client):
    resp = await client.post(
        "/api/v1/parser/run/nope", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert resp.status_code == 404


async def test_trigger_queues_and_deduplicates(client):
    resp = await client.post(
        "/api/v1/parser/run/itmo", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["university_code"] == "ITMO"

    # Задание реально в очереди.
    async with async_session_factory() as s:
        run = (
            await s.execute(select(ParserRun).where(ParserRun.status == "queued"))
        ).scalar_one()
        assert run.university_code == "ITMO"

    # Повтор — дубликат не ставится, но это не ошибка (202).
    resp = await client.post(
        "/api/v1/parser/run/ITMO", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "already_queued"


async def test_trigger_disabled_without_configured_token(client, monkeypatch):
    monkeypatch.setattr(settings, "parser_trigger_token", "")
    resp = await client.post(
        "/api/v1/parser/run/itmo", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert resp.status_code == 503
