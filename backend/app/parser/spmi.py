"""
Парсер конкурсных списков Санкт-Петербургского горного университета (SPMI).

Данные: GET https://priem2026.spmi.ru/list?direction_id=7&specialization_id=N
&applicant_type_id=2&applicant_consent_id=0 — server-rendered HTML с таблицей.
Браузер не нужен — HTTP-клиент Playwright + BeautifulSoup.

external_id в конфиге = specialization_id укрупнённой программы на сайте.
Несколько кодов направлений (09.03.01 и 09.03.02) могут указывать на один
specialization_id — список на сайте общий, парсер кэширует загрузку по id.
"""

import asyncio
import logging

from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.spmi_mapping import build_list_url, parse_list_html
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_REFERER = "https://priem2026.spmi.ru/specialization?direction_id=7"


class SpmiParser(BaseParser):
    """Парсер Горного университета СПб. Реализует BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Собрать направления вуза; один запрос на уникальный specialization_id."""
        result = ParseResult(university_code=self.university.code)
        # Кэш: specialization_id -> (places, applicants).
        cache: dict[str, tuple[int | None, list]] = {}

        async with async_playwright() as pw:
            rc = await pw.request.new_context(
                extra_http_headers={"User-Agent": _USER_AGENT, "Referer": _REFERER},
                timeout=settings.browser_timeout_ms,
            )
            try:
                for major in self.university.majors:
                    try:
                        major_result = await self._parse_major(rc, major, cache)
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

    async def _load_group(self, rc, specialization_id: str) -> tuple[int | None, list]:
        """Скачать и разобрать HTML-список укрупнённой программы."""
        url = build_list_url(specialization_id)
        resp = await rc.get(url)
        if not resp.ok:
            raise RuntimeError(f"list вернул статус {resp.status}: {url}")

        places, applicants = parse_list_html(await resp.text())
        if not applicants:
            raise RuntimeError("таблица общего конкурса пуста или не найдена")
        return places, applicants

    async def _parse_major(
        self,
        rc,
        major: MajorConfig,
        cache: dict[str, tuple[int | None, list]],
    ) -> MajorResult:
        if not major.external_id:
            raise RuntimeError("не задан external_id (specialization_id) в конфиге")

        spec_id = major.external_id.strip()
        if spec_id not in cache:
            cache[spec_id] = await self._load_group(rc, spec_id)

        places, applicants = cache[spec_id]
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
            applicants=list(applicants),
        )

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
