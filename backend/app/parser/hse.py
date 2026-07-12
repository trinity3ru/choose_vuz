"""
Парсер конкурсных списков ВШЭ (pk.hse.ru) — кампусы Москва и Санкт-Петербург.

Кампусы заведены в config.json как ДВА вуза (HSE_MSK, HSE_SPB) с общим классом
парсера: списки живут в одном API, но принадлежность кампусу видна только в
заголовке группы (поле filial). Парсер сверяет filial с ожидаемым городом
вуза — перепутанный URL другого кампуса даст явную ошибку, а не тихо чужие данные.

external_id направления = оба UUID из адресной строки списка через «/»:
    https://pk.hse.ru/admissions/bak/BD/applicants/<setId>/<groupId>
    -> external_id: "<setId>/<groupId>"
где setId — образовательная программа (набор конкурсных групп),
groupId — конкретный список (бюджет/платное/квоты). Берём только бюджетный
(placeType.code == «Б» проверяется по заголовку группы).

Браузер не нужен: обычные GET через httpx (см. hse_mapping — описание API).
"""

import asyncio
import logging
from typing import Any

import httpx

from app.parser.hse_mapping import BUDGET_PLACE_CODE, row_to_applicant
from app.parser.http_base import HttpParser, raise_for_status
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)

_API_BASE = "https://pk.hse.ru/admissions/api"
_REFERER = "https://pk.hse.ru/admissions/bak/BD/applicants"

# Ожидаемый кампус (filial из заголовка группы) для каждого кода вуза.
_EXPECTED_FILIAL = {
    "HSE_MSK": "Москва",
    "HSE_SPB": "Санкт-Петербург",
}

# Размер страницы списка (API отдаёт Spring Page).
_PAGE_SIZE = 500
# Пауза между страницами одного списка, сек (мягче, чем пауза между направлениями).
_PAGE_DELAY_S = 0.4


class HseParser(HttpParser):
    """Парсер ВШЭ (оба кампуса). Реализует интерфейс HttpParser."""

    def extra_headers(self) -> dict[str, str]:
        return {"Referer": _REFERER, "Accept": "application/json"}

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: Any
    ) -> MajorResult:
        set_id, group_id = self._split_external_id(major)

        # Заголовок группы: тип мест, места, кампус, дата формирования.
        resp = await client.get(f"{_API_BASE}/competitve-group/{group_id}")
        raise_for_status(resp, "заголовок конкурсной группы")
        header = resp.json()

        place_type = header.get("placeType") or {}
        if place_type.get("code") != BUDGET_PLACE_CODE:
            raise RuntimeError(
                f"список не бюджетный (placeType={place_type.get('code')}: "
                f"{place_type.get('name')}) — проверьте groupId в external_id"
            )

        expected_filial = _EXPECTED_FILIAL.get(self.university.code)
        filial = str(header.get("filial", "")).strip()
        if expected_filial and filial != expected_filial:
            raise RuntimeError(
                f"кампус списка «{filial}» не совпадает с вузом "
                f"({self.university.code} → {expected_filial}) — URL другого кампуса?"
            )

        applicants = await self._fetch_all_pages(client, set_id, place_type["id"])

        summary = MajorSummary(
            places=header.get("placeCount"),
            applications=len(applicants),
            agreements=sum(1 for a in applicants if a.has_agreement),
            list_formed_at=header.get("updatedAt"),
        )

        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=None,
            summary=summary,
            applicants=applicants,
        )

    async def _fetch_all_pages(
        self, client: httpx.AsyncClient, set_id: str, place_type_id: str
    ) -> list:
        """Собрать все страницы списка (Spring Page: content/totalPages)."""
        applicants: list = []
        page = 0
        total_pages = 1

        while page < total_pages:
            resp = await client.get(
                f"{_API_BASE}/applicant",
                params={
                    "sort": "index_number_in_reg_list",
                    "level": "BAK",
                    "placeType": place_type_id,
                    "setOfCompetitiveGroupId": set_id,
                    "page": page,
                    "size": _PAGE_SIZE,
                },
            )
            raise_for_status(resp, f"страница списка {page}")
            data = resp.json()

            applicants.extend(row_to_applicant(entry) for entry in data.get("content", []))
            total_pages = data.get("totalPages", 0)
            page += 1
            if page < total_pages:
                await asyncio.sleep(_PAGE_DELAY_S)

        return applicants

    @staticmethod
    def _split_external_id(major: MajorConfig) -> tuple[str, str]:
        """Разобрать external_id вида "<setId>/<groupId>" (оба UUID из URL)."""
        if not major.external_id or "/" not in major.external_id:
            raise RuntimeError(
                'не задан external_id вида "<setId>/<groupId>" '
                "(оба UUID из URL списка на pk.hse.ru)"
            )
        set_id, _, group_id = major.external_id.partition("/")
        set_id, group_id = set_id.strip(), group_id.strip()
        if not set_id or not group_id:
            raise RuntimeError("external_id должен содержать оба UUID через «/»")
        return set_id, group_id
