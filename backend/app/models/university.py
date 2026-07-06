"""Модель вуза (например, СПбПУ)."""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class University(Base):
    """Вуз. Один вуз имеет много направлений (majors)."""

    __tablename__ = "universities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Короткий уникальный код вуза, например "SPBSTU".
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500))

    # Связь: список направлений этого вуза.
    majors: Mapped[list["Major"]] = relationship(
        back_populates="university", cascade="all, delete-orphan"
    )
