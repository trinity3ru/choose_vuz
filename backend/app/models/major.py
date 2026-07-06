"""Модель направления подготовки (например, 09.03.04 Программная инженерия)."""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Major(Base):
    """
    Направление подготовки внутри вуза.

    Поле spbstu_internal_id хранит внутренний id направления с сайта СПбПУ
    (значение filter_3, которое приходит из эндпоинта get-code-list).
    Оно не совпадает с кодом вида "09.03.04" и может меняться, поэтому
    обновляется при каждом парсинге.
    """

    __tablename__ = "majors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    university_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("universities.id", ondelete="CASCADE")
    )
    # Код направления, например "09.03.04".
    code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(500))
    # Внутренний id направления на сайте СПбПУ (nullable: пока не спарсен).
    spbstu_internal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    university: Mapped["University"] = relationship(back_populates="majors")
    applicants: Mapped[list["Applicant"]] = relationship(back_populates="major")
    stats: Mapped[list["MajorStats"]] = relationship(back_populates="major")
