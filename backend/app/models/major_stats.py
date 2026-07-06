"""Модель сводки по направлению (места, заявления, согласия) на момент снимка."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MajorStats(Base):
    """
    Сводные показатели направления в конкретном снимке.

    Данные приходят из эндпоинта get-direction-info: количество мест,
    количество заявлений, количество согласий и время формирования списка
    на сайте вуза. Привязка к снимку позволяет видеть динамику.
    """

    __tablename__ = "major_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parse_snapshots.id", ondelete="CASCADE"),
        index=True,
    )
    major_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("majors.id", ondelete="CASCADE"), index=True
    )
    # Количество бюджетных мест на направлении.
    places: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Количество поданных заявлений.
    applications: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Количество согласий на зачисление.
    agreements: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Время формирования списка на сайте (как строка, например "03.07.2026 18:00").
    list_formed_at: Mapped[str | None] = mapped_column(String(100), nullable=True)

    snapshot: Mapped["ParseSnapshot"] = relationship(back_populates="stats")
    major: Mapped["Major"] = relationship(back_populates="stats")
