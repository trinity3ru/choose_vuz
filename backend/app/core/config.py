"""
Настройки приложения.

Значения читаются из переменных окружения (файл .env).
Используем pydantic-settings — он валидирует типы и даёт понятные ошибки,
если какая-то настройка отсутствует или имеет неверный формат.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень бэкенда: .../backend (на два уровня выше этого файла: core -> app -> backend)
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Все настройки проекта в одном месте."""

    # Строка подключения к PostgreSQL для асинхронного драйвера asyncpg.
    # Пример: postgresql+asyncpg://user:password@localhost:5432/univer_parser
    database_url: str

    # Путь к файлу конфигурации вузов и направлений.
    config_path: Path = BACKEND_DIR / "config.json"

    # Папка для скриншотов страницы при ошибках парсинга (диагностика).
    screenshots_dir: Path = BACKEND_DIR / "logs" / "screenshots"

    # Таймаут ожидания загрузки страницы в Playwright (миллисекунды).
    browser_timeout_ms: int = 30000

    # Запускать браузер без графического окна (True на сервере).
    headless: bool = True

    # Отключить sandbox Chromium (нужно при запуске в Docker-контейнере
    # под root: worker-образ). Локально оставлять False.
    browser_no_sandbox: bool = False

    # Разрешённые источники для CORS (фронтенд). Через запятую в .env, напр.:
    # CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Прод-режим: очередь, worker, мониторинг (см. DEPLOY_PLAN.md) ---

    # Запускать APScheduler внутри API (только локальная разработка).
    enable_scheduler: bool = False

    # Пауза между опросами очереди воркером (consume-queue), сек.
    queue_poll_seconds: int = 15

    # Токен ручного запуска парсера через POST /api/v1/parser/run/{code}.
    parser_trigger_token: str = ""

    # Данные вуза считаются устаревшими, если нет успешного запуска дольше N часов.
    parser_stale_hours: int = 24

    # running-задача старше N минут считается зависшей (worker interrupted).
    parser_stuck_minutes: int = 180

    # Алерт при падении records_saved на N% и больше от последнего успешного запуска.
    parser_records_drop_percent: int = 50

    # Хранить снимки парсинга N дней (cleanup-snapshots).
    snapshot_retention_days: int = 60

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS-источники как список (разбор строки из .env)."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Настройки читаем из файла .env в корне бэкенда.
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Единый экземпляр настроек, который импортируется в других модулях.
settings = Settings()
