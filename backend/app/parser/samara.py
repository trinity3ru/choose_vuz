"""
Парсер конкурсных списков Самарского университета им. Королёва.

Особенность сайта priemsamara.ru: страница рейтинга — обычный
server-rendered HTML (данные сразу в разметке), список открывается по
прямому идентификатору программы `pk` (задаётся в конфиге через external_id).

Поэтому НЕ нужен ни браузер, ни JS: обычный HTTP GET (httpx) и разбор HTML.

Бюджетный список разбит на таблицы-категории (Отдельная/Особая/Целевая квота
и Общий конкурс). По требованиям парсим ТОЛЬКО «Общий конкурс».
"""

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.samara_mapping import PAY_CODES, parse_places, row_to_applicant
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)


class SamaraParser(HttpParser):
    """Парсер Самарского университета. Реализует HttpParser._parse_major()."""

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: Any
    ) -> MajorResult:
        """Скачать и разобрать страницу рейтинга одного направления."""
        if not major.external_id:
            raise RuntimeError("не задан external_id (pk) в конфиге")

        url = self._build_url(major)
        resp = await client.get(url)
        raise_for_status(resp, "страница рейтинга")
        html = resp.text

        cells_rows = self._extract_general_rows(html)
        if not cells_rows:
            raise RuntimeError("не найдена таблица 'Общий конкурс' или она пуста")

        applicants = [row_to_applicant(cells) for cells in cells_rows]

        summary = MajorSummary(
            places=parse_places(html),
            applications=len(applicants),
            agreements=sum(1 for a in applicants if a.has_agreement),
            list_formed_at=None,
        )

        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=int(major.external_id) if major.external_id.isdigit() else None,
            summary=summary,
            applicants=applicants,
        )

    def _build_url(self, major: MajorConfig) -> str:
        """Собрать URL рейтинга: базовый url вуза + pk и условие оплаты."""
        pay = PAY_CODES.get(major.params.finance_type, "budget")
        base = str(self.university.url).rstrip("/") + "/"
        return f"{base}?pk={major.external_id}&pay={pay}&filter=all"

    @staticmethod
    def _extract_general_rows(html: str) -> list[list[str]]:
        """
        Найти таблицу «Общий конкурс» и вернуть строки как списки текстов ячеек.

        Каждая категория конкурса — отдельная таблица с id вида bak_table_idN,
        первая строка которой — заголовок-категория (th colspan=12). Берём ту,
        где в заголовке есть «Общий конкурс», и собираем строки с ячейками td.
        """
        soup = BeautifulSoup(html, "html.parser")

        target = None
        for table in soup.select("table[id^=bak_table_id]"):
            header = table.find("th")
            if header and "общий конкурс" in header.get_text(strip=True).lower():
                target = table
                break
        if target is None:
            return []

        rows: list[list[str]] = []
        for tr in target.find_all("tr"):
            tds = tr.find_all("td")
            # Строки данных содержат все колонки; строку-категорию (th) пропускаем.
            if len(tds) < 9:
                continue
            cells = [td.get_text(" ", strip=True) for td in tds]
            # В первой колонке — порядковый номер; так отсеиваем служебные строки.
            if not cells[0].strip().isdigit():
                continue
            rows.append(cells)
        return rows
