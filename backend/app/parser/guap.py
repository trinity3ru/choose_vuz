"""
Парсер конкурсных списков ГУАП (priem.guap.ru).

Сводная страница `bach/lists/list_1_1_1_1` — server-rendered HTML с таблицей
направлений и ссылками на бюджетные списки. Каждая программа — отдельная
страница с таблицей `.pk-ratings-table`.

Браузер не нужен: обычный HTTP GET через httpx.
Под одним кодом направления бывает несколько программ — объединяем, как у СПбГУ.
"""

import asyncio
import logging

import httpx

from app.parser.guap_mapping import parse_index, parse_list_page
from app.parser.http_base import HttpParser, raise_for_status
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)

_BASE_URL = "https://priem.guap.ru"
# Сводная таблица: бакалавриат, очная форма, бюджет.
_INDEX_PATH = "/bach/lists/list_1_1_1_1"


class GuapParser(HttpParser):
    """Парсер ГУАП. Реализует интерфейс HttpParser."""

    async def _prepare(self, client: httpx.AsyncClient) -> dict[str, list[str]]:
        """Скачать сводную таблицу и построить карту код -> ссылки на списки."""
        resp = await client.get(_BASE_URL + _INDEX_PATH)
        raise_for_status(resp, "сводная страница")
        return parse_index(resp.text)

    async def _parse_major(
        self,
        client: httpx.AsyncClient,
        major: MajorConfig,
        context: dict[str, list[str]],
    ) -> MajorResult:
        """Собрать все бюджетные программы направления и объединить абитуриентов."""
        list_paths = context.get(major.code)
        if not list_paths:
            raise RuntimeError("код направления не найден или нет бюджетного списка")

        all_applicants = []
        total_places = 0
        has_places = False
        list_formed_at: str | None = None

        for path in list_paths:
            places, formed_at, applicants = await self._fetch_list(client, path)
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

    async def _fetch_list(
        self, client: httpx.AsyncClient, path: str
    ) -> tuple[int | None, str | None, list]:
        """Скачать и разобрать страницу одной образовательной программы."""
        href = path if path.startswith("/") else f"/{path}"
        resp = await client.get(_BASE_URL + href)
        raise_for_status(resp, f"страница списка {href}")
        return parse_list_page(resp.text)
