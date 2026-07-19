"""
Pydantic-схемы ответов для фронтенда (данные абитуриентов).

Отдаём только то, что нужно для построения гистограммы и оценки шансов:
баллы, приоритет, признак согласия и БВИ по каждому заявлению, плюс сводка
по направлению (число мест и т.п.) и метаданные снимка.
"""

from datetime import datetime

from pydantic import BaseModel


class ApplicantOut(BaseModel):
    """Одно заявление абитуриента (минимум полей для анализа)."""

    total_score: int | None
    exam_score: int | None
    priority: int | None
    has_agreement: bool
    is_bvi: bool


class MajorStatsOut(BaseModel):
    """Сводка по направлению из снимка."""

    places: int | None
    applications: int | None
    agreements: int | None
    list_formed_at: str | None


class SnapshotOut(BaseModel):
    """Метаданные снимка, из которого взяты данные."""

    id: str
    created_at: datetime
    status: str


class MajorOut(BaseModel):
    """Направление, к которому относятся данные."""

    code: str
    name: str


class ApplicantsResponse(BaseModel):
    """Полный ответ для одного направления: снимок + сводка + заявления."""

    snapshot: SnapshotOut
    major: MajorOut
    stats: MajorStatsOut | None
    applicants: list[ApplicantOut]


class MajorStatsRow(BaseModel):
    """
    Агрегат по одному направлению для сводной выдачи.

    Без списка заявлений: только числа, пригодные для карточек и сортировок.
    """

    university_code: str
    university_name: str
    major_code: str
    major_name: str
    places: int | None
    applications: int | None
    agreements: int | None
    list_formed_at: str | None
    cutoff_score: int | None
    snapshot_created_at: datetime
    snapshot_status: str


class StatsResponse(BaseModel):
    """Сводка по всем направлениям, по которым есть пригодные данные."""

    items: list[MajorStatsRow]
