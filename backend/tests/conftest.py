"""
Общие помощники тестов.

Парсеры гоняются без сети: HttpParser._create_client подменяется клиентом
с httpx.MockTransport, который отдаёт заранее заготовленные ответы (фикстуры).
"""

import os

# Настройки приложения требуют DATABASE_URL — в тестах БД не нужна,
# но переменная должна существовать до импорта app.core.config.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)

from typing import Callable  # noqa: E402

import httpx  # noqa: E402

from app.parser.http_base import USER_AGENT, HttpParser  # noqa: E402
from app.schemas.config_schema import (  # noqa: E402
    MajorConfig,
    MajorParams,
    UniversityConfig,
)

Handler = Callable[[httpx.Request], httpx.Response]


def make_major(
    code: str,
    name: str = "Тестовое направление",
    external_id: str | None = None,
) -> MajorConfig:
    """Направление с типовыми параметрами (очная, бюджет)."""
    return MajorConfig(
        code=code,
        name=name,
        params=MajorParams(study_form="Очная", finance_type="Бюджетная основа"),
        external_id=external_id,
    )


def make_university(code: str, url: str, majors: list[MajorConfig]) -> UniversityConfig:
    """Вуз для тестов."""
    return UniversityConfig(code=code, name=f"Тестовый вуз {code}", url=url, majors=majors)


def mock_client(parser: HttpParser, handler: Handler) -> None:
    """
    Подменить создание HTTP-клиента на клиент с MockTransport.

    Заголовки и таймаут собираются как в боевом _create_client, чтобы тест
    проверял и extra_headers() парсера.
    """
    transport = httpx.MockTransport(handler)

    def _create_client() -> httpx.AsyncClient:
        timeout_ms = parser.request_timeout_ms or 30000
        return httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, **parser.extra_headers()},
            timeout=httpx.Timeout(timeout_ms / 1000),
            follow_redirects=True,
            transport=transport,
        )

    parser._create_client = _create_client  # type: ignore[method-assign]
