"""
API-эндпоинты выдачи данных для фронтенда.

- GET /api/v1/data/universities — вузы и направления из последнего пригодного
  снимка (то, по чему реально есть данные для анализа).
- GET /api/v1/data/applicants   — заявления абитуриентов одного направления
  из последнего пригодного снимка, плюс сводка по направлению.

«Пригодный снимок» — последний ParseSnapshot со статусом success или partial,
в котором есть строки по нужному направлению. Статус partial допускаем,
если часть направлений вуза не спарсилась (напр. нет бюджетного списка),
но по остальным данные полные.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import Applicant, Major, MajorStats, ParseSnapshot, University
from app.schemas.data_schema import (
    ApplicantOut,
    ApplicantsResponse,
    MajorOut,
    MajorStatsOut,
    SnapshotOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data", tags=["data"])

# Снимки, из которых фронтенд может показывать данные.
# partial — часть направлений вуза упала, но сохранённые строки валидны.
_USABLE_SNAPSHOT_STATUSES = ("success", "partial")


@router.get("/universities")
async def list_universities(
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """
    Вернуть вузы и их направления, по которым есть спарсенные данные.

    Возвращаются только направления, у которых есть заявления хотя бы в одном
    пригодном снимке — чтобы в фильтрах фронтенда не было пустых пунктов.
    """
    # Направления, по которым есть данные в success/partial снимках.
    stmt = (
        select(University.code, University.name, Major.code, Major.name)
        .join(Major, Major.university_id == University.id)
        .join(Applicant, Applicant.major_id == Major.id)
        .join(ParseSnapshot, ParseSnapshot.id == Applicant.snapshot_id)
        .where(ParseSnapshot.status.in_(_USABLE_SNAPSHOT_STATUSES))
        .distinct()
        .order_by(University.name, Major.code)
    )
    rows = (await session.execute(stmt)).all()

    # Группируем направления по вузам, сохраняя порядок.
    universities: dict[str, dict] = {}
    for uni_code, uni_name, major_code, major_name in rows:
        uni = universities.setdefault(
            uni_code, {"code": uni_code, "name": uni_name, "majors": []}
        )
        uni["majors"].append({"code": major_code, "name": major_name})

    return list(universities.values())


@router.get("/applicants", response_model=ApplicantsResponse)
async def get_applicants(
    university_code: str = Query(..., description="Код вуза, напр. SPBSTU"),
    major_code: str = Query(..., description="Код направления, напр. 09.03.04"),
    session: AsyncSession = Depends(get_session),
) -> ApplicantsResponse:
    """
    Вернуть заявления одного направления из последнего пригодного снимка.

    Данные берутся из самого свежего снимка success/partial, в котором
    есть строки по этому направлению.
    """
    major = await _resolve_major(session, university_code, major_code)
    if major is None:
        raise HTTPException(status_code=404, detail="Направление не найдено")

    snapshot = await _latest_usable_snapshot_for_major(session, major.id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="Нет снимка с данными по этому направлению",
        )

    applicants_stmt = (
        select(Applicant)
        .where(
            Applicant.snapshot_id == snapshot.id,
            Applicant.major_id == major.id,
        )
        .order_by(Applicant.total_score.desc().nullslast())
    )
    applicant_rows = (await session.execute(applicants_stmt)).scalars().all()

    stats_stmt = select(MajorStats).where(
        MajorStats.snapshot_id == snapshot.id,
        MajorStats.major_id == major.id,
    )
    stats_row = (await session.execute(stats_stmt)).scalar_one_or_none()

    return ApplicantsResponse(
        snapshot=SnapshotOut(
            id=str(snapshot.id),
            created_at=snapshot.created_at,
            status=snapshot.status,
        ),
        major=MajorOut(code=major.code, name=major.name),
        stats=(
            MajorStatsOut(
                places=stats_row.places,
                applications=stats_row.applications,
                agreements=stats_row.agreements,
                list_formed_at=stats_row.list_formed_at,
            )
            if stats_row is not None
            else None
        ),
        applicants=[
            ApplicantOut(
                total_score=a.total_score,
                exam_score=a.exam_score,
                priority=a.priority,
                has_agreement=a.has_agreement,
                is_bvi=a.is_bvi,
            )
            for a in applicant_rows
        ],
    )


async def _resolve_major(
    session: AsyncSession, university_code: str, major_code: str
) -> Major | None:
    """Найти направление по коду вуза и коду направления."""
    stmt = (
        select(Major)
        .join(University, University.id == Major.university_id)
        .where(University.code == university_code, Major.code == major_code)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _latest_usable_snapshot_for_major(
    session: AsyncSession, major_id
) -> ParseSnapshot | None:
    """
    Найти последний пригодный снимок, где есть заявления по направлению.

    Джойн с applicants гарантирует, что снимок реально содержит данные по
    этому направлению (а не просто существует со статусом success/partial).
    """
    stmt = (
        select(ParseSnapshot)
        .join(Applicant, Applicant.snapshot_id == ParseSnapshot.id)
        .where(
            ParseSnapshot.status.in_(_USABLE_SNAPSHOT_STATUSES),
            Applicant.major_id == major_id,
        )
        .order_by(ParseSnapshot.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()
