"""
Тесты этапа 3: ссылки снимка на вуз/запуск, records_changed, retention.

Работают против тестовой PostgreSQL (см. conftest.clean_db).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models import ParseSnapshot, ParserRun
from app.schemas.parser_schema import ApplicantRow, MajorResult, ParseResult
from app.services import queue
from app.services.changes import compute_records_changed
from app.services.storage import save_parse_result

from .conftest import make_major, make_university


@pytest.fixture(autouse=True)
async def _db(clean_db):
    yield


def _applicant(code: str, total: int, priority: int = 1, agreement: bool = False) -> ApplicantRow:
    return ApplicantRow(
        applicant_code=code,
        total_score=total,
        priority=priority,
        has_agreement=agreement,
    )


def _result(
    uni_code: str,
    majors: dict[str, list[ApplicantRow]],
    status: str = "success",
) -> ParseResult:
    return ParseResult(
        university_code=uni_code,
        status=status,
        majors=[
            MajorResult(code=mcode, name=f"Направление {mcode}", applicants=rows)
            for mcode, rows in majors.items()
        ],
    )


UNI = make_university("ITMO", "https://abit.itmo.ru/x", [make_major("01.03.02")])


async def test_snapshot_gets_university_and_run_links():
    run = await queue.start_direct_run("itmo")
    snapshot = await save_parse_result(
        UNI, _result("ITMO", {"01.03.02": [_applicant("111", 200)]}), parser_run_id=run.id
    )

    async with async_session_factory() as s:
        stored = (
            await s.execute(select(ParseSnapshot).where(ParseSnapshot.id == snapshot.id))
        ).scalar_one()
        assert stored.university_id is not None
        assert stored.parser_run_id == run.id


async def test_records_changed_none_without_previous_success():
    snapshot = await save_parse_result(
        UNI, _result("ITMO", {"01.03.02": [_applicant("111", 200)]})
    )
    assert await compute_records_changed(snapshot.id) is None


async def test_records_changed_added_removed_modified():
    # База: три заявления.
    await save_parse_result(
        UNI,
        _result(
            "ITMO",
            {
                "01.03.02": [
                    _applicant("111", 200),
                    _applicant("222", 210),
                    _applicant("333", 190),
                ]
            },
        ),
    )
    # Новый снимок: 111 без изменений, 222 изменил балл, 333 исчез, 444 добавился.
    snap2 = await save_parse_result(
        UNI,
        _result(
            "ITMO",
            {
                "01.03.02": [
                    _applicant("111", 200),
                    _applicant("222", 215),
                    _applicant("444", 180),
                ]
            },
        ),
    )
    # added(444) + removed(333) + modified(222) = 3.
    assert await compute_records_changed(snap2.id) == 3


async def test_records_changed_key_is_major_and_code():
    """Один applicant_code на двух направлениях не даёт ложных изменений."""
    uni = make_university(
        "ITMO",
        "https://abit.itmo.ru/x",
        [make_major("01.03.02"), make_major("02.03.01")],
    )
    majors = {
        "01.03.02": [_applicant("555", 200)],
        "02.03.01": [_applicant("555", 240)],  # тот же код, другой балл
    }
    await save_parse_result(uni, _result("ITMO", majors))
    snap2 = await save_parse_result(uni, _result("ITMO", majors))
    assert await compute_records_changed(snap2.id) == 0


async def test_records_changed_compares_with_last_success_only():
    await save_parse_result(
        UNI, _result("ITMO", {"01.03.02": [_applicant("111", 200)]})
    )
    # Неудачный пустой снимок между успешными не должен быть базой сравнения.
    await save_parse_result(UNI, _result("ITMO", {}, status="failed"))
    snap3 = await save_parse_result(
        UNI,
        _result(
            "ITMO",
            {"01.03.02": [_applicant("111", 200), _applicant("999", 170)]},
        ),
    )
    # Против первого успешного: added(999) = 1.
    assert await compute_records_changed(snap3.id) == 1


async def test_cleanup_snapshots_keeps_parser_runs(capsys):
    from app.cli import EXIT_OK, cmd_cleanup_snapshots

    run = await queue.start_direct_run("itmo")
    old_snap = await save_parse_result(
        UNI,
        _result("ITMO", {"01.03.02": [_applicant("111", 200)]}),
        parser_run_id=run.id,
    )
    fresh_snap = await save_parse_result(
        UNI, _result("ITMO", {"01.03.02": [_applicant("111", 200)]})
    )

    # Состариваем первый снимок за пределы retention (60 дней по умолчанию).
    async with async_session_factory() as s:
        async with s.begin():
            obj = (
                await s.execute(select(ParseSnapshot).where(ParseSnapshot.id == old_snap.id))
            ).scalar_one()
            obj.created_at = datetime.now(timezone.utc) - timedelta(days=100)

    class Args:
        pass

    assert await cmd_cleanup_snapshots(Args()) == EXIT_OK
    assert "deleted snapshots: 1" in capsys.readouterr().out

    async with async_session_factory() as s:
        remaining = (await s.execute(select(ParseSnapshot.id))).scalars().all()
        assert remaining == [fresh_snap.id]
        # История запусков не тронута (retention независимы).
        runs = (await s.execute(select(ParserRun.id))).scalars().all()
        assert run.id in runs
