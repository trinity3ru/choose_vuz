"""
Парсер конкурсных списков Санкт-Петербургского горного университета (SPMI).

Данные: GET https://priem2026.spmi.ru/list?direction_id=7&specialization_id=N
&applicant_type_id=2&applicant_consent_id=0 — server-rendered HTML с таблицей.
Браузер не нужен — httpx + BeautifulSoup.

external_id в конфиге = specialization_id укрупнённой программы на сайте.
Несколько кодов направлений (09.03.01 и 09.03.02) могут указывать на один
specialization_id — список на сайте общий, парсер кэширует загрузку по id.
"""

import logging

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.spmi_mapping import build_list_url, parse_list_html
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)

_REFERER = "https://priem2026.spmi.ru/specialization?direction_id=7"

# Кэш загрузок: specialization_id -> (places, applicants).
_Cache = dict[str, tuple[int | None, list]]


class SpmiParser(HttpParser):
    """Парсер Горного университета СПб. Реализует интерфейс HttpParser."""

    def extra_headers(self) -> dict[str, str]:
        return {"Referer": _REFERER}

    async def _prepare(self, client: httpx.AsyncClient) -> _Cache:
        """Создать кэш загрузок (несколько кодов делят один specialization_id)."""
        return {}

    async def _load_group(
        self, client: httpx.AsyncClient, specialization_id: str
    ) -> tuple[int | None, list]:
        """Скачать и разобрать HTML-список укрупнённой программы."""
        url = build_list_url(specialization_id)
        resp = await client.get(url)
        raise_for_status(resp, f"list {url}")

        places, applicants = parse_list_html(resp.text)
        if not applicants:
            raise RuntimeError("таблица общего конкурса пуста или не найдена")
        return places, applicants

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: _Cache
    ) -> MajorResult:
        if not major.external_id:
            raise RuntimeError("не задан external_id (specialization_id) в конфиге")

        spec_id = major.external_id.strip()
        if spec_id not in context:
            context[spec_id] = await self._load_group(client, spec_id)

        places, applicants = context[spec_id]
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
