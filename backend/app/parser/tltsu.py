"""
Парсер конкурсных списков ТГУ (Тольяттинский госуниверситет, edu.tltsu.ru).

Списки публикуются как BIRT-отчёт. Интерактивный режим `run` отдаёт AJAX-оболочку,
но режим `preview` возвращает готовый HTML целиком — его и берём обычным GET
(без браузера, через HTTP-клиент Playwright). Ответ тяжёлый и медленный,
поэтому таймаут увеличен.

Один запрос (один `dep` = институт) содержит сразу несколько направлений.
Мы парсим отчёт один раз, группируем строки по коду направления и берём только
категорию «Основные места … (бюджет)» (см. tltsu_mapping.parse_report).
"""

import logging

from playwright.async_api import async_playwright

from app.parser.base import BaseParser
from app.parser.tltsu_mapping import parse_report
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
# Отчёт большой и медленный — даём запросу больше времени (мс).
_REQUEST_TIMEOUT_MS = 120000


class TltsuParser(BaseParser):
    """Парсер ТГУ. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Один GET отчёта -> разбор -> результаты по направлениям из конфига."""
        result = ParseResult(university_code=self.university.code)
        url = str(self.university.url)

        async with async_playwright() as pw:
            rc = await pw.request.new_context(
                extra_http_headers={"User-Agent": _USER_AGENT},
                timeout=_REQUEST_TIMEOUT_MS,
            )
            try:
                resp = await rc.get(url)
                if not resp.ok:
                    raise RuntimeError(f"отчёт вернул статус {resp.status}")
                html = await resp.text()

                # Разбираем весь отчёт: {код -> {places, applicants}}.
                by_code = parse_report(html)

                for major in self.university.majors:
                    data = by_code.get(major.code)
                    if not data or not data["applicants"]:
                        msg = f"Направление {major.code}: нет данных в отчёте"
                        logger.warning(msg)
                        result.errors.append(msg)
                        continue

                    applicants = data["applicants"]
                    summary = MajorSummary(
                        places=data["places"],
                        applications=len(applicants),
                        agreements=sum(1 for a in applicants if a.has_agreement),
                        list_formed_at=None,
                    )
                    result.majors.append(
                        MajorResult(
                            code=major.code,
                            name=major.name,
                            internal_id=None,
                            summary=summary,
                            applicants=applicants,
                        )
                    )

            except Exception as exc:  # noqa: BLE001 (падение всего запуска)
                msg = f"Критическая ошибка парсинга {self.university.code}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)
            finally:
                await rc.dispose()

        result.status = self._compute_status(result)
        return result

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        """Определить статус запуска: success / partial / failed."""
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
