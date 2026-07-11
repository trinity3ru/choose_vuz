"""
Парсер конкурсных списков ИТМО (abit.itmo.ru).

Сайт — приложение на Next.js. Данные списка встроены прямо в HTML страницы
(server-side rendering) внутри тега <script id="__NEXT_DATA__">. Поэтому
браузер и выполнение JS не нужны: делаем обычный GET и разбираем JSON
(HTTP-клиент Playwright, как у других HTML/JSON-вузов проекта).

Каждое направление открывается по прямому competitive_group_id, который
задаётся в конфиге через external_id. URL строится как:
    {university.url}/{external_id}
например: https://abit.itmo.ru/rating/bachelor/budget/2342
"""

import asyncio
import logging

from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.itmo_mapping import (
    compute_general_places,
    extract_program_list,
    row_to_applicant,
)
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

# Браузерный User-Agent: без него сайт может отдать заглушку.
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class ItmoParser(BaseParser):
    """Парсер ИТМО. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Собрать все направления вуза через GET HTML-страниц и вернуть результат."""
        result = ParseResult(university_code=self.university.code)

        async with async_playwright() as pw:
            # request.new_context() — HTTP-клиент без запуска браузера.
            rc = await pw.request.new_context(
                extra_http_headers={"User-Agent": _USER_AGENT},
                timeout=settings.browser_timeout_ms,
            )
            try:
                for major in self.university.majors:
                    try:
                        major_result = await self._parse_major(rc, major)
                        result.majors.append(major_result)
                    except Exception as exc:  # noqa: BLE001 (логируем и продолжаем)
                        msg = f"Направление {major.code}: {exc}"
                        logger.exception(msg)
                        result.errors.append(msg)
                    # Пауза между направлениями (защита от блокировок).
                    await asyncio.sleep(self.request_delay_seconds)

            except Exception as exc:  # noqa: BLE001 (падение всего запуска)
                msg = f"Критическая ошибка парсинга {self.university.code}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)
            finally:
                await rc.dispose()

        result.status = self._compute_status(result)
        return result

    async def _parse_major(self, rc, major: MajorConfig) -> MajorResult:
        """Скачать и разобрать страницу конкурсного списка одного направления."""
        if not major.external_id:
            raise RuntimeError("не задан external_id (competitive_group_id) в конфиге")

        url = str(self.university.url).rstrip("/") + "/" + major.external_id.lstrip("/")
        resp = await rc.get(url)
        if not resp.ok:
            raise RuntimeError(f"страница списка вернула статус {resp.status}")

        html = await resp.text()
        program_list = extract_program_list(html)

        # Берём только общий конкурс (как у Самары/СПбГУ).
        general = program_list.get("general_competition", [])
        applicants = [row_to_applicant(entry) for entry in general]
        if not applicants:
            raise RuntimeError("список общего конкурса пуст или не найден")

        direction = program_list.get("direction", {})
        summary = MajorSummary(
            places=compute_general_places(direction),
            applications=len(applicants),
            agreements=sum(1 for a in applicants if a.has_agreement),
            list_formed_at=program_list.get("update_time"),
        )

        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=direction.get("competitive_group_id"),
            summary=summary,
            applicants=applicants,
        )

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        """Определить статус запуска: success / partial / failed."""
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
