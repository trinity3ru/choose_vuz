"""
Парсер конкурсных списков Академического университета им. Ж.И. Алферова (spbau.ru).

Данные публикуются только как xlsx на странице /campaign/bachelor/documents.
Один файл содержит все конкурсные группы; для направления 03.03.01 объединяем
подходящие блоки («Общий конкурс», очная форма, бюджет).
"""

import logging

from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.spbau_mapping import find_latest_xlsx_url, parse_xlsx
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class SpbauParser(BaseParser):
    """Парсер Алферовского университета (СПбАУ). Реализует BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Скачать актуальный xlsx и разобрать направления из конфига."""
        result = ParseResult(university_code=self.university.code)

        async with async_playwright() as pw:
            rc = await pw.request.new_context(
                extra_http_headers={"User-Agent": _USER_AGENT},
                timeout=settings.browser_timeout_ms,
            )
            try:
                xlsx_bytes, list_url = await self._download_latest_xlsx(rc)
                logger.info("СПбАУ: скачан список %s (%d байт)", list_url, len(xlsx_bytes))

                for major in self.university.majors:
                    try:
                        major_result = self._parse_major(major, xlsx_bytes, list_url)
                        result.majors.append(major_result)
                    except Exception as exc:  # noqa: BLE001
                        msg = f"Направление {major.code}: {exc}"
                        logger.exception(msg)
                        result.errors.append(msg)

            except Exception as exc:  # noqa: BLE001
                msg = f"Критическая ошибка парсинга {self.university.code}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)
            finally:
                await rc.dispose()

        result.status = self._compute_status(result)
        return result

    async def _download_latest_xlsx(self, rc) -> tuple[bytes, str]:
        """Открыть страницу документов и скачать последний xlsx основного конкурса."""
        page_url = str(self.university.url)
        resp = await rc.get(page_url)
        if not resp.ok:
            raise RuntimeError(f"страница документов вернула статус {resp.status}")

        html = await resp.text()
        xlsx_url = find_latest_xlsx_url(html, page_url)

        file_resp = await rc.get(xlsx_url)
        if not file_resp.ok:
            raise RuntimeError(f"xlsx-файл вернул статус {file_resp.status}")

        content = await file_resp.body()
        if not content:
            raise RuntimeError("xlsx-файл пуст")

        return content, xlsx_url

    def _parse_major(self, major: MajorConfig, xlsx_bytes: bytes, list_url: str) -> MajorResult:
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

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
