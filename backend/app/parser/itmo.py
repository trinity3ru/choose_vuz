"""
Парсер конкурсных списков ИТМО (abit.itmo.ru).

Сайт — приложение на Next.js. Данные списка встроены прямо в HTML страницы
(server-side rendering) внутри тега <script id="__NEXT_DATA__">. Поэтому
браузер и выполнение JS не нужны: обычный GET через httpx.

Каждое направление открывается по прямому competitive_group_id, который
задаётся в конфиге через external_id. URL строится как:
    {university.url}/{external_id}
например: https://abit.itmo.ru/rating/bachelor/budget/2342
"""

import logging
from typing import Any

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.itmo_mapping import (
    compute_general_places,
    extract_program_list,
    row_to_applicant,
)
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)


class ItmoParser(HttpParser):
    """Парсер ИТМО. Реализует интерфейс HttpParser._parse_major()."""

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: Any
    ) -> MajorResult:
        """Скачать и разобрать страницу конкурсного списка одного направления."""
        if not major.external_id:
            raise RuntimeError("не задан external_id (competitive_group_id) в конфиге")

        url = str(self.university.url).rstrip("/") + "/" + major.external_id.lstrip("/")
        resp = await client.get(url)
        raise_for_status(resp, "страница списка")

        program_list = extract_program_list(resp.text)

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
