"""
Парсер конкурсных списков МЭИ (pk.mpei.ru).

Каждое направление публикуется на отдельной странице
`pk.mpei.ru/info/entrants_listN.html` — server-rendered HTML с таблицей
«По конкурсу». Обычный GET через httpx, без cookie/JS.

Имя файла страницы задаётся в конфиге через external_id.
"""

import logging
from typing import Any

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.mpei_mapping import parse_page
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)

_BASE_URL = "https://pk.mpei.ru/info/"


class MpeiParser(HttpParser):
    """Парсер МЭИ. Реализует интерфейс HttpParser._parse_major()."""

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: Any
    ) -> MajorResult:
        """Скачать и разобрать HTML-страницу одного направления."""
        if not major.external_id:
            raise RuntimeError("не задан external_id (имя файла страницы) в конфиге")

        url = _BASE_URL + major.external_id.lstrip("/")
        resp = await client.get(url)
        raise_for_status(resp, "страница списка")

        places, applicants = parse_page(resp.text)
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
