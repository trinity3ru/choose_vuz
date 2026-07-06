"""
Парсер конкурсных списков Самарского университета им. Королёва.

Особенность сайта priemsamara.ru: страница рейтинга — обычный
server-rendered HTML (данные сразу в разметке), список открывается по
прямому идентификатору программы `pk` (задаётся в конфиге через external_id).

Поэтому НЕ нужен ни браузер, ни JS: достаточно обычного HTTP GET и разбора
HTML. Чтобы не тащить лишнюю зависимость, используем лёгкий HTTP-клиент
Playwright (`playwright.request`) — он уже есть в проекте и не запускает браузер.

Бюджетный список разбит на таблицы-категории (Отдельная/Особая/Целевая квота
и Общий конкурс). По требованиям парсим ТОЛЬКО «Общий конкурс».
"""

import asyncio
import logging

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.samara_mapping import PAY_CODES, parse_places, row_to_applicant
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

# Браузерный User-Agent: без него некоторые сайты отдают заглушку.
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class SamaraParser(BaseParser):
    """Парсер Самарского университета. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Собрать все направления вуза через HTTP GET и вернуть результат."""
        result = ParseResult(university_code=self.university.code)

        async with async_playwright() as pw:
            # request.new_context() — HTTP-клиент без запуска браузера.
            request_context = await pw.request.new_context(
                extra_http_headers={"User-Agent": _USER_AGENT},
                timeout=settings.browser_timeout_ms,
            )
            try:
                for major in self.university.majors:
                    try:
                        major_result = await self._parse_major(request_context, major)
                        result.majors.append(major_result)
                    except Exception as exc:  # noqa: BLE001 (логируем и продолжаем)
                        msg = f"Направление {major.code}: {exc}"
                        logger.exception(msg)
                        result.errors.append(msg)
                    # Пауза между направлениями (защита от блокировок).
                    await asyncio.sleep(self.request_delay_seconds)
            finally:
                await request_context.dispose()

        result.status = self._compute_status(result)
        return result

    async def _parse_major(self, request_context, major: MajorConfig) -> MajorResult:
        """Скачать и разобрать страницу рейтинга одного направления."""
        if not major.external_id:
            raise RuntimeError("не задан external_id (pk) в конфиге")

        url = self._build_url(major)
        resp = await request_context.get(url)
        if not resp.ok:
            raise RuntimeError(f"страница рейтинга вернула статус {resp.status}")
        html = await resp.text()

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

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        """Определить статус запуска: success / partial / failed."""
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
