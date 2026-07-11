"""
Парсер конкурсных списков Академического университета им. Ж.И. Алферова (spbau.ru).

Данные публикуются только как xlsx на странице /campaign/bachelor/documents.
Один файл содержит все конкурсные группы; для направления 03.03.01 объединяем
подходящие блоки («Общий конкурс», очная форма, бюджет).

Браузер не нужен: страница и файл скачиваются обычным GET через httpx,
xlsx разбирается openpyxl (spbau_mapping).
"""

import logging
from typing import Any

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.spbau_mapping import find_latest_xlsx_url, parse_xlsx
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)


class SpbauParser(HttpParser):
    """Парсер Алферовского университета (СПбАУ). Реализует HttpParser."""

    async def _parse_all(self, client: httpx.AsyncClient, result: ParseResult) -> None:
        """Скачать актуальный xlsx один раз и разобрать направления из конфига."""
        xlsx_bytes, list_url = await self._download_latest_xlsx(client)
        logger.info("СПбАУ: скачан список %s (%d байт)", list_url, len(xlsx_bytes))

        for major in self.university.majors:
            try:
                result.majors.append(self._parse_major_xlsx(major, xlsx_bytes, list_url))
            except Exception as exc:  # noqa: BLE001 (логируем и продолжаем)
                msg = f"Направление {major.code}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)

    async def _download_latest_xlsx(self, client: httpx.AsyncClient) -> tuple[bytes, str]:
        """Открыть страницу документов и скачать последний xlsx основного конкурса."""
        page_url = str(self.university.url)
        resp = await client.get(page_url)
        raise_for_status(resp, "страница документов")

        xlsx_url = find_latest_xlsx_url(resp.text, page_url)

        file_resp = await client.get(xlsx_url)
        raise_for_status(file_resp, "xlsx-файл")

        content = file_resp.content
        if not content:
            raise RuntimeError("xlsx-файл пуст")

        return content, xlsx_url

    def _parse_major_xlsx(
        self, major: MajorConfig, xlsx_bytes: bytes, list_url: str
    ) -> MajorResult:
        """Разобрать xlsx для одного направления из конфига."""
        places, applicants, formed_at = parse_xlsx(
            xlsx_bytes,
            study_form=major.params.study_form,
            finance_type=major.params.finance_type,
        )

        if not applicants:
            raise RuntimeError(
                f"в xlsx не найдено абитуриентов для {major.code} "
                f"({major.params.study_form}, {major.params.finance_type})"
            )

        summary = MajorSummary(
            places=places,
            applications=len(applicants),
            agreements=sum(1 for a in applicants if a.has_agreement),
            list_formed_at=formed_at,
        )

        logger.info(
            "СПбАУ %s: %d абитуриентов, мест=%s, файл=%s",
            major.code,
            len(applicants),
            places,
            list_url,
        )

        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=None,
            summary=summary,
            applicants=applicants,
        )

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: Any
    ) -> MajorResult:
        """Не используется: весь разбор идёт в _parse_all()."""
        raise NotImplementedError
