"""Модель снимка (snapshot) — один запуск парсера в конкретный момент времени."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ParseSnapshot(Base):
    """
    Снимок парсинга.

    Списки абитуриентов меняются каждый день (доносят оригиналы, меняют
    приоритеты). Каждый запуск парсера создаёт снимок, и все записи
    абитуриентов привязываются к нему. Это позволяет строить динамику по дням.

    status:
        success — все направления спарсены успешно;
        partial — часть направлений упала, часть собрана;
        failed  — парсинг полностью не удался.
    """

    __tablename__ = "parse_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Прямая ссылка на вуз: нужна для retention и истории даже у пустых
    # или неудачных снимков (у них нет заявлений, косвенная связь не работает).
    university_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("universities.id", ondelete="CASCADE"),
        index=True,
    )
    # Запуск парсера, создавший снимок. ON DELETE SET NULL: retention снимков
    # и истории запусков независимы (удаление запуска не каскадит на снимок).
    parser_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parser_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(20), default="success")
    # Текст ошибок (если были), для быстрой диагностики.
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    applicants: Mapped[list["Applicant"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )
    stats: Mapped[list["MajorStats"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )
