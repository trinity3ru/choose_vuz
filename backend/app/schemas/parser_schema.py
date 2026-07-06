"""
Pydantic-схемы для данных, которые возвращает парсер.

Эти модели описывают результат парсинга в чистом, нормализованном виде
(независимо от конкретного вуза). Сервисный слой сохранения работает
именно с ними, а не с сырым JSON сайта.
"""

from typing import Literal

from pydantic import BaseModel


class ApplicantRow(BaseModel):
    """Одна строка конкурсного списка (одно заявление абитуриента)."""

    applicant_code: str
    is_bvi: bool = False
    total_score: int | None = None
    exam_score: int | None = None
    achievement_score: int | None = None
    target_achievement_score: int | None = None
    preferential_right: str | None = None
    priority: int | None = None
    has_agreement: bool = False
    review_status: str | None = None


class MajorSummary(BaseModel):
    """Сводка по направлению (из get-direction-info)."""

    places: int | None = None
    applications: int | None = None
    agreements: int | None = None
    list_formed_at: str | None = None


class MajorResult(BaseModel):
    """Результат парсинга одного направления."""

    code: str  # код направления из конфига, напр. "09.03.04"
    name: str  # название направления из конфига
    internal_id: int | None = None  # внутренний id направления на сайте вуза
    summary: MajorSummary | None = None
    applicants: list[ApplicantRow] = []


class ParseResult(BaseModel):
    """Итог всего запуска парсера по одному вузу."""

    university_code: str
    status: Literal["success", "partial", "failed"] = "success"
    majors: list[MajorResult] = []
    # Тексты ошибок по направлениям (для диагностики и записи в снимок).
    errors: list[str] = []
