"""
Модель запуска парсера (parser_runs) — история и очередь запусков.

Одна строка = один запуск парсера одного вуза. Таблица служит одновременно:
- очередью заданий: API/таймер создают строку status='queued', worker атомарно
  забирает её (status='running') и по завершении финализирует;
- историей запусков для health-API (/api/v1/parser/health, /runs) и алертов.

Статусы:
    queued  — задание поставлено, ждёт worker;
    running — выполняется (started_at заполнен);
    success — все направления собраны;
    partial — часть направлений упала;
    failed  — запуск не удался (или worker прерван — recover-stuck-runs);
    skipped — запуск пропущен (например, дубликат).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ParserRun(Base):
    """Запуск (или задание на запуск) парсера одного вуза."""

    __tablename__ = "parser_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Код вуза из config.json (SPBSTU, ITMO, ...).
    university_code: Mapped[str] = mapped_column(String(50), index=True)
    # Тип парсера на момент запуска: http / playwright.
    parser_type: Mapped[str] = mapped_column(String(20))

    # Жизненный цикл. started_at пуст, пока задание ждёт в очереди.
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Итоги: сколько строк абитуриентов найдено/сохранено/изменено.
    # records_changed = NULL, если сравнивать не с чем (первый успешный запуск).
    records_found: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_saved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_changed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Диагностика.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
