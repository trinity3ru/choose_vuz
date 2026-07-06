"""
Подключение к базе данных PostgreSQL (асинхронное).

Здесь создаём:
- Base    — базовый класс для всех моделей (таблиц);
- engine  — асинхронный движок SQLAlchemy;
- async_session_factory — фабрика сессий для работы с БД.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Базовый класс моделей. От него наследуются все таблицы проекта."""

    pass


# Асинхронный движок: одно соединение-пул на всё приложение.
engine = create_async_engine(
    settings.database_url,
    echo=False,  # True — если нужно видеть SQL-запросы в логах при отладке
    pool_pre_ping=True,  # проверять живость соединения перед использованием
)

# Фабрика сессий. expire_on_commit=False — объекты остаются доступны после commit.
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """
    Зависимость FastAPI: выдаёт сессию БД на время обработки запроса
    и корректно закрывает её после.
    """
    async with async_session_factory() as session:
        yield session
