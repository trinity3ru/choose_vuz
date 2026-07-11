"""
Парсер конкурсных списков ГУАП (priem.guap.ru).

Сводная страница `bach/lists/list_1_1_1_1` — server-rendered HTML с таблицей
направлений и ссылками на бюджетные списки. Каждая программа — отдельная
страница с таблицей `.pk-ratings-table`.

Браузер не нужен: обычный HTTP GET через playwright.request.
Под одним кодом направления бывает несколько программ — объединяем, как у СПбГУ.
"""

import asyncio
import logging

from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.guap_mapping import parse_index, parse_list_page
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://priem.guap.ru"
# Сводная таблица: бакалавриат, очная форма, бюджет.
_INDEX_PATH = "/bach/lists/list_1_1_1_1"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class GuapParser(BaseParser):
    """Парсер ГУАП. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Собрать все направления вуза через GET HTML-страниц."""
        result = ParseResult(university_code=self.university.code)

        async with async_playwright() as pw:
            rc = await pw.request.new_context(
                extra_http_headers={"User-Agent": _USER_AGENT},
                timeout=settings.browser_timeout_ms,
            )
            try:
                code_map = await self._fetch_index(rc)

                for major in self.university.majors:
                    try:
                        major_result = await self._parse_major(rc, major, code_map)
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

    async def _fetch_index(self, rc) -> dict[str, list[str]]:
        """Скачать сводную таблицу и построить карту код -> ссылки на списки."""
        url = _BASE_URL + _INDEX_PATH
        resp = await rc.get(url)
        if not resp.ok:
            raise RuntimeError(f"сводная страница вернула статус {resp.status}")
        html = await resp.text()
        return parse_index(html)

    async def _parse_major(
        self,
        rc,
        major: MajorConfig,
        code_map: dict[str, list[str]],
    ) -> MajorResult:
        """Собрать все бюджетные программы направления и объединить абитуриентов."""
        list_paths = code_map.get(major.code)
        if not list_paths:
            raise RuntimeError("код направления не найден или нет бюджетного списка")

        all_applicants = []
        total_places = 0
        has_places = False
        list_formed_at: str | None = None

        for path in list_paths:
            places, formed_at, applicants = await self._fetch_list(rc, path)
            all_applicants.extend(applicants)
            if places is not None:
                total_places += places
                has_places = True
            if formed_at and not list_formed_at:
                list_formed_at = formed_at
            await asyncio.sleep(self.request_delay_seconds)

        if not all_applicants:
            raise RuntimeError("таблица рейтинга пуста или не найдена")

        summary = MajorSummary(
            places=total_places if has_places else None,
            applications=len(all_applicants),
            agreements=sum(1 for a in all_applicants if a.has_agreement),
            list_formed_at=list_formed_at,
        )

        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=None,
            summary=summary,
            applicants=all_applicants,
        )

    async def _fetch_list(self, rc, path: str) -> tuple[int | None, str | None, list]:
        """Скачать и разобрать страницу одной образовательной программы."""
        href = path if path.startswith("/") else f"/{path}"
        url = _BASE_URL + href
        resp = await rc.get(url)
        if not resp.ok:
            raise RuntimeError(f"страница списка {href} вернула статус {resp.status}")
        html = await resp.text()
        return parse_list_page(html)

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
