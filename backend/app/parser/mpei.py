"""
Парсер конкурсных списков МЭИ (pk.mpei.ru).

Каждое направление публикуется на отдельной странице
`pk.mpei.ru/info/entrants_listN.html` — server-rendered HTML с таблицей
«По конкурсу». Обычный GET без cookie/JS (HTTP-клиент Playwright).

Имя файла страницы задаётся в конфиге через external_id.
"""

import asyncio
import logging

from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.mpei_mapping import parse_page
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://pk.mpei.ru/info/"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class MpeiParser(BaseParser):
    """Парсер МЭИ. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Собрать все направления вуза через GET HTML-страниц."""
        result = ParseResult(university_code=self.university.code)

        async with async_playwright() as pw:
            rc = await pw.request.new_context(
                extra_http_headers={"User-Agent": _USER_AGENT},
                timeout=settings.browser_timeout_ms,
            )
            try:
                for major in self.university.majors:
                    try:
                        major_result = await self._parse_major(rc, major)
                        result.majors.append(major_result)
                    except Exception as exc:  # noqa: BLE001
                        msg = f"Направление {major.code}: {exc}"
                        logger.exception(msg)
                        result.errors.append(msg)
                    await asyncio.sleep(self.request_delay_seconds)

            except Exception as exc:  # noqa: BLE001
                msg = f"Критическая ошибка парсинга {self.university.code}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)
            finally:
                await rc.dispose()

        result.status = self._compute_status(result)
        return result

    async def _parse_major(self, rc, major: MajorConfig) -> MajorResult:
        """Скачать и разобрать HTML-страницу одного направления."""
        if not major.external_id:
            raise RuntimeError("не задан external_id (имя файла страницы) в конфиге")

        url = _BASE_URL + major.external_id.lstrip("/")
        resp = await rc.get(url)
        if not resp.ok:
            raise RuntimeError(f"страница списка вернула статус {resp.status}")

        html = await resp.text()
        places, applicants = parse_page(html)
        if not applicants:
            raise RuntimeError("таблица «По конкурсу» пуста или не найдена")

        summary = MajorSummary(
            places=places,
            applications=len(applicants),
            agreements=sum(1 for a in applicants if a.has_agreement),
            list_formed_at=None,
        )

        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=None,
            summary=summary,
            applicants=applicants,
        )

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
