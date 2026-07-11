"""
Парсер конкурсных списков КФУ (Казанский федеральный университет).

Данные на странице kpfu.ru встроены через iframe abiturient.kpfu.ru.
Фильтр работает GET-параметрами (перезагрузка страницы), без AJAX — браузер
не нужен, используем HTTP-клиент Playwright.

external_id в конфиге = id института (p_faculty). id программы (p_speciality)
находим по коду направления в выпадающем списке.
"""

import asyncio
import logging
from urllib.parse import urlencode

from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.kpfu_mapping import (
    decode_html,
    parse_main_competition,
    parse_select_options,
    pick_speciality_id,
)
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

_LIST_PATH = "/entrant/abit_entrant_originals_list"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Фиксированные коды формы для бакалавриата, очной, бюджета, основного кампуса.
_LEVEL_BACHELOR = "1"
_INST_MAIN = "0"
_CATEGORY_BUDGET = "1"
_STUDY_FULLTIME = "1"


class KpfuParser(BaseParser):
    """Парсер КФУ. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Собрать все направления вуза через GET HTML-страниц."""
        result = ParseResult(university_code=self.university.code)
        base_host = self._list_host()

        async with async_playwright() as pw:
            rc = await pw.request.new_context(
                extra_http_headers={
                    "User-Agent": _USER_AGENT,
                    "Referer": str(self.university.url),
                },
                timeout=settings.browser_timeout_ms,
            )
            try:
                for major in self.university.majors:
                    try:
                        major_result = await self._parse_major(rc, base_host, major)
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

    def _list_host(self) -> str:
        """Базовый URL API списков (iframe abiturient.kpfu.ru)."""
        url = str(self.university.url)
        if "abiturient.kpfu.ru" in url:
            return url.split("/entrant/")[0]
        return "https://abiturient.kpfu.ru"

    async def _fetch_html(self, rc, url: str) -> str:
        resp = await rc.get(url)
        if not resp.ok:
            raise RuntimeError(f"запрос вернул статус {resp.status}: {url}")
        return decode_html(await resp.body())

    def _build_url(self, base_host: str, params: dict[str, str]) -> str:
        return f"{base_host}{_LIST_PATH}?{urlencode(params)}"

    async def _resolve_speciality_id(
        self, rc, base_host: str, faculty_id: str, code: str
    ) -> tuple[str, str]:
        """Получить p_speciality по коду направления."""
        url = self._build_url(
            base_host,
            {
                "p_level": _LEVEL_BACHELOR,
                "p_inst": _INST_MAIN,
                "p_faculty": faculty_id,
                "p_category": _CATEGORY_BUDGET,
            },
        )
        html = await self._fetch_html(rc, url)
        spec_id, title = pick_speciality_id(parse_select_options(html, "p_speciality"), code)
        return spec_id, title

    async def _parse_major(self, rc, base_host: str, major: MajorConfig) -> MajorResult:
        if not major.external_id:
            raise RuntimeError("не задан external_id (id института p_faculty) в конфиге")

        spec_id, _ = await self._resolve_speciality_id(
            rc, base_host, major.external_id, major.code
        )
        url = self._build_url(
            base_host,
            {
                "p_level": _LEVEL_BACHELOR,
                "p_inst": _INST_MAIN,
                "p_faculty": major.external_id,
                "p_speciality": spec_id,
                "p_typeofstudy": _STUDY_FULLTIME,
                "p_category": _CATEGORY_BUDGET,
            },
        )
        html = await self._fetch_html(rc, url)
        places, applicants = parse_main_competition(html)
        if not applicants:
            raise RuntimeError("таблица общего конкурса пуста или не найдена")

        summary = MajorSummary(
            places=places,
            applications=len(applicants),
            agreements=sum(1 for row in applicants if row.has_agreement),
            list_formed_at=None,
        )
        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=int(spec_id),
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
