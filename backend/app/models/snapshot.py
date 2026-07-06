"""Модель снимка (snapshot) — один запуск парсера в конкретный момент времени."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
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
