"""
Тесты сводного эндпоинта GET /api/v1/data/stats.

Ключевое, что здесь проверяется, — расчёт отсечки: он должен совпадать с
клиентской реализацией (`cutoffScore` в frontend/src/utils/analysis.ts),
иначе две реализации разъедутся.

Работают против тестовой PostgreSQL (см. conftest.clean_db): нужны оконные
функции, на SQLite такой запрос не проверить.
"""

import httpx
import pytest

from app.main import app
from app.schemas.parser_schema import ApplicantRow, MajorResult, MajorSummary, ParseResult
from app.services.storage import save_parse_result

from .conftest import make_major, make_university


@pytest.fixture(autouse=True)
async def _db(clean_db):
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


UNI = make_university(
    "ITMO", "https://abit.itmo.ru/x", [make_major("01.03.02"), make_major("09.03.04")]
)


def _applicant(code: str, total: int) -> ApplicantRow:
    return ApplicantRow(applicant_code=code, total_score=total, priority=1)


def _result(
    majors: dict[str, tuple[MajorSummary | None, list[ApplicantRow]]],
    status: str = "success",
) -> ParseResult:
    return ParseResult(
        university_code="ITMO",
        status=status,
        majors=[
            MajorResult(code=code, name=f"Направление {code}", summary=summary, applicants=rows)
            for code, (summary, rows) in majors.items()
        ],
    )


async def _stats_for(client: httpx.AsyncClient, major_code: str) -> dict:
    """Достать строку сводки по коду направления."""
    response = await client.get("/api/v1/data/stats")
    assert response.status_code == 200
    items = response.json()["items"]
    match = [i for i in items if i["major_code"] == major_code]
    assert len(match) == 1, f"ожидалась одна строка по {major_code}, получено {len(match)}"
    return match[0]


async def test_cutoff_is_score_at_last_place(client):
    """Отсечка — балл абитуриента на последнем месте в пределах КЦП."""
    await save_parse_result(
        UNI,
        _result(
            {
                "01.03.02": (
                    MajorSummary(places=3, applications=5, agreements=2),
                    # 290, 280, 270 проходят; 3-е место = 270.
                    [
                        _applicant("a", 250),
                        _applicant("b", 290),
                        _applicant("c", 270),
                        _applicant("d", 280),
                        _applicant("e", 240),
                    ],
                )
            }
        ),
    )

    row = await _stats_for(client, "01.03.02")
    assert row["cutoff_score"] == 270
    assert row["places"] == 3
    assert row["applications"] == 5
    assert row["agreements"] == 2
    assert row["university_code"] == "ITMO"


async def test_cutoff_is_min_score_when_fewer_applicants_than_places(client):
    """Заявлений меньше, чем мест, — отсечка равна минимальному баллу."""
    await save_parse_result(
        UNI,
        _result(
            {
                "01.03.02": (
                    MajorSummary(places=10),
                    [_applicant("a", 200), _applicant("b", 260)],
                )
            }
        ),
    )

    row = await _stats_for(client, "01.03.02")
    assert row["cutoff_score"] == 200


async def test_cutoff_is_null_without_places(client):
    """Без КЦП отсечка не определена — выдаём null, а не выдуманное число."""
    await save_parse_result(
        UNI,
        _result({"01.03.02": (MajorSummary(places=None), [_applicant("a", 200)])}),
    )

    row = await _stats_for(client, "01.03.02")
    assert row["cutoff_score"] is None
    assert row["places"] is None


async def test_uses_latest_snapshot_only(client):
    """Берём последний пригодный снимок, а не смешиваем историю."""
    await save_parse_result(
        UNI,
        _result({"01.03.02": (MajorSummary(places=1), [_applicant("a", 200)])}),
    )
    await save_parse_result(
        UNI,
        _result({"01.03.02": (MajorSummary(places=1), [_applicant("b", 299)])}),
    )

    row = await _stats_for(client, "01.03.02")
    assert row["cutoff_score"] == 299


async def test_filter_by_university_code(client):
    """Фильтр по вузу отсекает чужие направления."""
    await save_parse_result(
        UNI,
        _result({"01.03.02": (MajorSummary(places=1), [_applicant("a", 200)])}),
    )

    response = await client.get("/api/v1/data/stats", params={"university_code": "SPBSTU"})
    assert response.status_code == 200
    assert response.json()["items"] == []

    response = await client.get("/api/v1/data/stats", params={"university_code": "ITMO"})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_separate_majors_do_not_leak_scores(client):
    """Отсечка считается внутри направления, а не по всему снимку."""
    await save_parse_result(
        UNI,
        _result(
            {
                "01.03.02": (MajorSummary(places=1), [_applicant("a", 210)]),
                "09.03.04": (MajorSummary(places=1), [_applicant("b", 290)]),
            }
        ),
    )

    assert (await _stats_for(client, "01.03.02"))["cutoff_score"] == 210
    assert (await _stats_for(client, "09.03.04"))["cutoff_score"] == 290
