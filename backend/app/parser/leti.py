"""
Парсер конкурсных списков СПбГЭТУ «ЛЭТИ» (abit.etu.ru / lists.priem.etu.ru).

Страница abit.etu.ru встраивает виджет, который грузит данные с
lists.priem.etu.ru. Мы обращаемся напрямую к API:

    GET https://lists.priem.etu.ru/public/list.html?id=<UUID>

Ответ — готовый HTML таблицы (обычный GET через httpx, без cookie/JS).
UUID списка задаётся в конфиге через external_id.
"""

import logging
from typing import Any

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.leti_mapping import parse_list_html
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)

_API_BASE = "https://lists.priem.etu.ru/public/list.html"
_REFERER = "https://abit.etu.ru/ru/postupayushhim/lists/page/list"


class LetiParser(HttpParser):
    """Парсер ЛЭТИ. Реализует интерфейс HttpParser._parse_major()."""

    def extra_headers(self) -> dict[str, str]:
        return {"Referer": _REFERER}

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: Any
    ) -> MajorResult:
        """Скачать и разобрать HTML-список одного направления."""
        if not major.external_id:
            raise RuntimeError("не задан external_id (id списка) в конфиге")

        resp = await client.get(_API_BASE, params={"id": major.external_id})
        raise_for_status(resp, "list.html")

        places, applicants = parse_list_html(resp.text)
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
