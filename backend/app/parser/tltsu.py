"""
Парсер конкурсных списков ТГУ (Тольяттинский госуниверситет, edu.tltsu.ru).

Списки публикуются как BIRT-отчёт. Интерактивный режим `run` отдаёт AJAX-оболочку,
но режим `preview` возвращает готовый HTML целиком — его и берём обычным GET
(httpx, без браузера). Ответ тяжёлый и медленный, поэтому таймаут увеличен.

Один запрос (один `dep` = институт) содержит сразу несколько направлений.
Мы парсим отчёт один раз, группируем строки по коду направления и берём только
категорию «Основные места … (бюджет)» (см. tltsu_mapping.parse_report).
"""

import logging

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.tltsu_mapping import parse_report
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult
from typing import Any

logger = logging.getLogger(__name__)


class TltsuParser(HttpParser):
    """Парсер ТГУ. Реализует интерфейс HttpParser."""

    # Отчёт большой и медленный — даём запросу больше времени (мс).
    request_timeout_ms = 120000

    async def _parse_all(self, client: httpx.AsyncClient, result: ParseResult) -> None:
        """Один GET отчёта -> разбор -> результаты по направлениям из конфига."""
        resp = await client.get(str(self.university.url))
        raise_for_status(resp, "отчёт")

        # Разбираем весь отчёт: {код -> {places, applicants}}.
        by_code = parse_report(resp.text)

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

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: Any
    ) -> MajorResult:
        """Не используется: весь разбор идёт в _parse_all()."""
        raise NotImplementedError
