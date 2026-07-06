"""
Сервисный слой: сохранение результата парсинга в PostgreSQL.

Логика:
1. Находим или создаём вуз (по коду) и направления (по коду внутри вуза).
2. Создаём снимок (parse_snapshot) с итоговым статусом запуска.
3. Массово записываем строки абитуриентов и сводки по направлениям.
Всё выполняется в одной транзакции: при ошибке изменения откатываются.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models import Applicant, Major, MajorStats, ParseSnapshot, University
from app.schemas.config_schema import UniversityConfig
from app.schemas.parser_schema import MajorResult, ParseResult

logger = logging.getLogger(__name__)


async def save_parse_result(
    university: UniversityConfig, result: ParseResult
) -> ParseSnapshot:
    """
    Сохранить результат парсинга одного вуза в БД (в транзакции).

    :param university: конфиг вуза (нужен для имени вуза).
    :param result: результат работы парсера.
    :return: созданный снимок (ParseSnapshot).
    """
    async with async_session_factory() as session:
        async with session.begin():  # автоматический commit/rollback
            university_obj = await _get_or_create_university(session, university)

            # Снимок фиксирует момент запуска и итоговый статус.
            snapshot = ParseSnapshot(
                status=result.status,
                error_log="\n".join(result.errors) if result.errors else None,
            )
            session.add(snapshot)
            await session.flush()  # получаем snapshot.id

            for major_result in result.majors:
                await _save_major(session, university_obj, snapshot, major_result)

        # После выхода из session.begin() транзакция зафиксирована.
        logger.info(
            "Снимок %s сохранён: статус=%s, направлений=%d",
            snapshot.id,
            snapshot.status,
            len(result.majors),
        )
        return snapshot


async def _get_or_create_university(
    session: AsyncSession, university: UniversityConfig
) -> University:
    """Найти вуз по коду или создать новый."""
    stmt = select(University).where(University.code == university.code)
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        obj = University(code=university.code, name=university.name)
        session.add(obj)
        await session.flush()  # получаем university.id
    return obj


async def _get_or_create_major(
    session: AsyncSession, university: University, major_result: MajorResult
) -> Major:
    """Найти направление по коду внутри вуза или создать; обновить данные."""
    stmt = select(Major).where(
        Major.university_id == university.id, Major.code == major_result.code
    )
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        obj = Major(university_id=university.id, code=major_result.code)
        session.add(obj)
    # Обновляем имя и внутренний id сайта (могли измениться).
    obj.name = major_result.name
    obj.spbstu_internal_id = major_result.internal_id
    await session.flush()  # получаем major.id
    return obj


async def _save_major(
    session: AsyncSession,
    university: University,
    snapshot: ParseSnapshot,
    major_result: MajorResult,
) -> None:
    """Сохранить одно направление: сводку и всех абитуриентов."""
    major_obj = await _get_or_create_major(session, university, major_result)

    # Сводка по направлению (если получена).
    if major_result.summary is not None:
        s = major_result.summary
        session.add(
            MajorStats(
                snapshot_id=snapshot.id,
                major_id=major_obj.id,
                places=s.places,
                applications=s.applications,
                agreements=s.agreements,
                list_formed_at=s.list_formed_at,
            )
        )

    # Строки абитуриентов — массовая вставка через ORM-объекты.
    applicants = [
        Applicant(
            snapshot_id=snapshot.id,
            major_id=major_obj.id,
            applicant_code=row.applicant_code,
            is_bvi=row.is_bvi,
            total_score=row.total_score,
            exam_score=row.exam_score,
            achievement_score=row.achievement_score,
            target_achievement_score=row.target_achievement_score,
            preferential_right=row.preferential_right,
            priority=row.priority,
            has_agreement=row.has_agreement,
            review_status=row.review_status,
        )
        for row in major_result.applicants
    ]
    session.add_all(applicants)
