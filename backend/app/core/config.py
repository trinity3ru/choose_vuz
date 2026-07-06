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

    # Разрешённые источники для CORS (фронтенд). Через запятую в .env, напр.:
    # CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

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
