"""
Парсер конкурсных списков КФУ (Казанский федеральный университет).

Данные на странице kpfu.ru встроены через iframe abiturient.kpfu.ru.
Фильтр работает GET-параметрами (перезагрузка страницы), без AJAX — браузер
не нужен, обычные запросы через httpx.

Ответ сайта чаще в cp1251, поэтому декодируем тело сами (kpfu_mapping.decode_html).

external_id в конфиге = id института (p_faculty). id программы (p_speciality)
находим по коду направления в выпадающем списке.
"""

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.kpfu_mapping import (
    decode_html,
    parse_main_competition,
    parse_select_options,
    pick_speciality_id,
)
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)

_LIST_PATH = "/entrant/abit_entrant_originals_list"

# Фиксированные коды формы для бакалавриата, очной, бюджета, основного кампуса.
_LEVEL_BACHELOR = "1"
_INST_MAIN = "0"
_CATEGORY_BUDGET = "1"
_STUDY_FULLTIME = "1"


class KpfuParser(HttpParser):
    """Парсер КФУ. Реализует интерфейс HttpParser."""

    def extra_headers(self) -> dict[str, str]:
        return {"Referer": str(self.university.url)}

    def _list_host(self) -> str:
        """Базовый URL API списков (iframe abiturient.kpfu.ru)."""
        url = str(self.university.url)
        if "abiturient.kpfu.ru" in url:
            return url.split("/entrant/")[0]
        return "https://abiturient.kpfu.ru"

    async def _fetch_html(self, client: httpx.AsyncClient, url: str) -> str:
        resp = await client.get(url)
        raise_for_status(resp, f"запрос {url}")
        return decode_html(resp.content)

    def _build_url(self, base_host: str, params: dict[str, str]) -> str:
        return f"{base_host}{_LIST_PATH}?{urlencode(params)}"

    async def _resolve_speciality_id(
        self, client: httpx.AsyncClient, base_host: str, faculty_id: str, code: str
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
        html = await self._fetch_html(client, url)
        spec_id, title = pick_speciality_id(parse_select_options(html, "p_speciality"), code)
        return spec_id, title

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: Any
    ) -> MajorResult:
        if not major.external_id:
            raise RuntimeError("не задан external_id (id института p_faculty) в конфиге")

        base_host = self._list_host()
        spec_id, _ = await self._resolve_speciality_id(
            client, base_host, major.external_id, major.code
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
        html = await self._fetch_html(client, url)
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
