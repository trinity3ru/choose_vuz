"""
Конфигурация окружения Alembic для асинхронного движка (asyncpg).

Здесь мы:
- подставляем DATABASE_URL из настроек проекта (app.core.config);
- подключаем метаданные всех моделей (app.models) для автогенерации миграций;
- запускаем миграции через асинхронное соединение.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Импортируем настройки, базовый класс и модели проекта.
# Импорт app.models регистрирует все таблицы в Base.metadata.
from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401  (нужен для регистрации моделей)

# Объект конфигурации Alembic (доступ к значениям alembic.ini).
config = context.config

# Подставляем строку подключения из наших настроек (.env), а не из alembic.ini.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Настройка логирования из alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Метаданные моделей — по ним Alembic сравнивает состояние БД и генерирует миграции.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Миграции в offline-режиме: генерация SQL без подключения к БД."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Выполнить миграции на переданном соединении."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Миграции в online-режиме через асинхронное соединение."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
