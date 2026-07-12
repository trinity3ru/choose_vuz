"""
Расчёт records_changed: сколько заявлений изменилось между снимками вуза.

Семантика (DEPLOY_PLAN, раунды B/C):
- сравнение с ПОСЛЕДНИМ УСПЕШНЫМ (status='success') снимком того же вуза;
- ключ строки — пара (major_id, applicant_code): один абитуриент подаёт
  на несколько направлений одного вуза, сравнение только по коду дало бы
  ложные добавления/удаления;
- records_changed = added + removed + modified, где modified — совпал ключ,
  но изменилось любое из {total_score, priority, has_agreement, review_status};
- если предыдущего успешного снимка нет — возвращается None
  («не с чем сравнивать» отличается от «изменений нет»).

Модуль DB-only (без импорта парсеров): считает worker при финализации запуска.
"""

import logging
import uuid

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models import Applicant, ParseSnapshot

logger = logging.getLogger(__name__)

# Поля, изменение которых считается «modified».
_Row = tuple[int | None, int | None, bool, str | None]
_Key = tuple[uuid.UUID, str]


async def _load_rows(session, snapshot_id: uuid.UUID) -> dict[_Key, _Row]:
    """Загрузить строки снимка как {(major_id, applicant_code): поля}."""
    result = await session.execute(
        select(
            Applicant.major_id,
            Applicant.applicant_code,
            Applicant.total_score,
            Applicant.priority,
            Applicant.has_agreement,
            Applicant.review_status,
        ).where(Applicant.snapshot_id == snapshot_id)
    )
    rows: dict[_Key, _Row] = {}
    for major_id, code, total, priority, agreement, status in result:
        rows[(major_id, code)] = (total, priority, agreement, status)
    return rows


async def compute_records_changed(snapshot_id: uuid.UUID) -> int | None:
    """
    Посчитать records_changed снимка относительно последнего успешного
    снимка того же вуза.

    :return: added + removed + modified, либо None (нет базы для сравнения).
    """
    async with async_session_factory() as session:
        snapshot = (
            await session.execute(
                select(ParseSnapshot).where(ParseSnapshot.id == snapshot_id)
            )
        ).scalar_one_or_none()
        if snapshot is None:
            logger.warning("records_changed: снимок %s не найден", snapshot_id)
            return None

        previous = (
            await session.execute(
                select(ParseSnapshot)
                .where(
                    ParseSnapshot.university_id == snapshot.university_id,
                    ParseSnapshot.id != snapshot.id,
                    ParseSnapshot.status == "success",
                    ParseSnapshot.created_at < snapshot.created_at,
                )
                .order_by(ParseSnapshot.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if previous is None:
            return None

        current_rows = await _load_rows(session, snapshot.id)
        previous_rows = await _load_rows(session, previous.id)

    current_keys = set(current_rows)
    previous_keys = set(previous_rows)

    added = len(current_keys - previous_keys)
    removed = len(previous_keys - current_keys)
    modified = sum(
        1
        for key in current_keys & previous_keys
        if current_rows[key] != previous_rows[key]
    )
    return added + removed + modified
