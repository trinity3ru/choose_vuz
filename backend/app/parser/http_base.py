"""
Базовый класс HTTP-парсеров (без браузера).

По требованиям деплоя (ТЗ §8.2) вузы, чьи сайты читаются обычными HTTP-запросами,
парсятся через httpx — Playwright для них не используется. Playwright остаётся
только у вузов, где нужна реальная браузерная сессия (СПбПУ, СПбГУТ).

Класс инкапсулирует общий скелет запуска, который раньше дублировался в каждом
парсере: создание HTTP-клиента, цикл по направлениям с паузой и сбором ошибок,
итоговый статус success/partial/failed. Наследник реализует _parse_major()
и при необходимости _prepare() (одноразовая подготовка: сводная страница,
список групп, скачивание общего файла и т.п.).
"""

import asyncio
import logging
from abc import abstractmethod
from typing import Any

import httpx

from app.core.config import settings
from app.parser.base import BaseParser
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, ParseResult

logger = logging.getLogger(__name__)

# Браузерный User-Agent: без него некоторые сайты отдают заглушку.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def compute_status(result: ParseResult) -> str:
    """Определить статус запуска: success / partial / failed."""
    if not result.errors:
        return "success"
    if result.majors:
        return "partial"
    return "failed"


def raise_for_status(resp: httpx.Response, what: str) -> None:
    """Единая проверка HTTP-статуса с понятным текстом ошибки."""
    if not resp.is_success:
        raise RuntimeError(f"{what} вернул статус {resp.status_code}")


class HttpParser(BaseParser):
    """
    Парсер вуза, работающий обычными HTTP-запросами (httpx, без браузера).

    Наследник задаёт при необходимости:
    - extra_headers() — дополнительные заголовки (Referer и т.п.);
    - request_timeout_ms — увеличенный таймаут (например, тяжёлый BIRT-отчёт);
    - _prepare() — одноразовая подготовка перед циклом направлений;
    - _parse_major() — разбор одного направления (обязательно).
    """

    # Таймаут запроса, мс. None -> settings.browser_timeout_ms.
    request_timeout_ms: int | None = None

    def extra_headers(self) -> dict[str, str]:
        """Дополнительные HTTP-заголовки конкретного вуза (Referer и т.п.)."""
        return {}

    def _create_client(self) -> httpx.AsyncClient:
        """
        Создать HTTP-клиент.

        Вынесено в отдельный метод, чтобы тесты могли подменить транспорт
        (httpx.MockTransport) и гонять парсер без сети.
        """
        timeout_ms = self.request_timeout_ms or settings.browser_timeout_ms
        return httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, **self.extra_headers()},
            timeout=httpx.Timeout(timeout_ms / 1000),
            follow_redirects=True,
        )

    async def parse(self) -> ParseResult:
        """Собрать все направления вуза и вернуть результат."""
        result = ParseResult(university_code=self.university.code)

        async with self._create_client() as client:
            try:
                await self._parse_all(client, result)
            except Exception as exc:  # noqa: BLE001 (падение всего запуска)
                msg = f"Критическая ошибка парсинга {self.university.code}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)

        result.status = compute_status(result)
        return result

    async def _parse_all(self, client: httpx.AsyncClient, result: ParseResult) -> None:
        """
        Стандартный цикл: подготовка, затем направления по одному с паузой.

        Наследники с нестандартным потоком (один отчёт на все направления,
        общий xlsx-файл) переопределяют этот метод целиком.
        """
        context = await self._prepare(client)

        for major in self.university.majors:
            try:
                result.majors.append(await self._parse_major(client, major, context))
            except Exception as exc:  # noqa: BLE001 (логируем и продолжаем)
                msg = f"Направление {major.code}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)
            # Пауза между направлениями (защита от блокировок).
            await asyncio.sleep(self.request_delay_seconds)

    async def _prepare(self, client: httpx.AsyncClient) -> Any:
        """Одноразовая подготовка перед циклом (по умолчанию не нужна)."""
        return None

    @abstractmethod
    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: Any
    ) -> MajorResult:
        """Разобрать одно направление. context — результат _prepare()."""
        raise NotImplementedError
