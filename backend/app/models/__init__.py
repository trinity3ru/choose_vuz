"""
Пакет моделей БД.

Импортируем все модели здесь, чтобы Alembic и SQLAlchemy видели их
при автогенерации миграций (достаточно импортировать app.models).
"""

from app.models.university import University
from app.models.major import Major
from app.models.snapshot import ParseSnapshot
from app.models.applicant import Applicant
from app.models.major_stats import MajorStats
from app.models.parser_run import ParserRun

__all__ = [
    "University",
    "Major",
    "ParseSnapshot",
    "Applicant",
    "MajorStats",
    "ParserRun",
]
