"""Модель заявления абитуриента (одна строка конкурсного списка)."""

import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Applicant(Base):
    """
    Одно заявление абитуриента на конкретное направление в конкретном снимке.

    Абитуриент указан по уникальному коду, присвоенному на ЕПГУ
    (персональных данных сайт не публикует).
    """

    __tablename__ = "applicants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parse_snapshots.id", ondelete="CASCADE"),
        index=True,
    )
    major_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("majors.id", ondelete="CASCADE"), index=True
    )
    # Уникальный код поступающего с ЕПГУ.
    applicant_code: Mapped[str] = mapped_column(String(50), index=True)
    # Поступление без вступительных испытаний (олимпиадники и т.п.).
    is_bvi: Mapped[bool] = mapped_column(Boolean, default=False)
    # Сумма конкурсных баллов (по ней идёт ранжирование).
    total_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Сумма баллов за вступительные испытания (ЕГЭ/ВИ).
    exam_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Баллы за общие индивидуальные достижения (ИД).
    achievement_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Баллы за целевые индивидуальные достижения.
    target_achievement_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Преимущественное право (текст, обычно "Отсутствует").
    preferential_right: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Приоритет заявления (1-5 и т.д.).
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Наличие согласия на зачисление / заключённого договора.
    has_agreement: Mapped[bool] = mapped_column(Boolean, default=False)
    # Статус рассмотрения заявления ("Участвует в конкурсе", "На рассмотрении").
    review_status: Mapped[str | None] = mapped_column(String(200), nullable=True)

    snapshot: Mapped["ParseSnapshot"] = relationship(back_populates="applicants")
    major: Mapped["Major"] = relationship(back_populates="applicants")
