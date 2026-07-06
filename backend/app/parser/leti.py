"""
Парсер конкурсных списков СПбГЭТУ «ЛЭТИ» (abit.etu.ru / lists.priem.etu.ru).

Страница abit.etu.ru встраивает виджет, который грузит данные с
lists.priem.etu.ru. Мы обращаемся напрямую к API:

    GET https://lists.priem.etu.ru/public/list.html?id=<UUID>

Ответ — готовый HTML таблицы (обычный GET, без cookie/JS).
UUID списка задаётся в конфиге через external_id.
"""

import asyncio
import logging

from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.leti_mapping import parse_list_html
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

_API_BASE = "https://lists.priem.etu.ru/public/list.html"
_REFERER = "https://abit.etu.ru/ru/postupayushhim/lists/page/list"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class LetiParser(BaseParser):
    """Парсер ЛЭТИ. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Собрать все направления вуза через GET list.html и вернуть результат."""
        result = ParseResult(university_code=self.university.code)

        async with async_playwright() as pw:
            rc = await pw.request.new_context(
                extra_http_headers={"User-Agent": _USER_AGENT, "Referer": _REFERER},
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
        """Скачать и разобрать HTML-список одного направления."""
        if not major.external_id:
            raise RuntimeError("не задан external_id (id списка) в конфиге")

        resp = await rc.get(_API_BASE, params={"id": major.external_id})
        if not resp.ok:
            raise RuntimeError(f"list.html вернул статус {resp.status}")

        html = await resp.text()
        places, applicants = parse_list_html(html)
        if not applicants:
            raise RuntimeError("не найдены строки «Основные места» или список пуст")

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
