"""
Парсер конкурсных списков СПбГУ (enrollelists.spbu.ru).

Страница reports/PriemList02.php — Vue-приложение; данные грузятся AJAX.
В HTML встроен JSON (#priem-list-02-report-meta) с идентификаторами отчёта и
списком направлений (specialities) с их UUID. Сами строки берём из эндпоинта:

    POST /api/reports/priem-list-02/data
    тело: {report_priem_list_02_id, speciality_ids:[UUID], filters:{...}}
    ответ: {blocks:[{html}]} — готовый HTML таблицы (разбираем в spbgu_mapping).

Всё работает по обычным GET/POST без cookie/CSRF, поэтому браузер не нужен —
используем HTTP-клиент Playwright (playwright.request).

Под одним кодом направления бывает несколько образовательных программ; по
решению парсим ВСЕ программы направления и объединяем в один список.
"""

import asyncio
import json
import logging
import re

from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.spbgu_mapping import parse_block
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

# Адреса сайта.
LIST_URL = "https://enrollelists.spbu.ru/reports/PriemList02.php"
DATA_URL = "https://enrollelists.spbu.ru/api/reports/priem-list-02/data"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Регулярка для вырезания встроенного JSON с метаданными отчёта.
_META_RE = re.compile(
    r'id="priem-list-02-report-meta">(.*?)</script>', re.DOTALL
)

# Фильтры формы для очной бюджетной кампании (бакалавриат/специалитет).
_EDUCATION_FORM = "очная"
_FIN_SOURCE = "Бюджет"


class SpbguParser(BaseParser):
    """Парсер СПбГУ. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Собрать все направления вуза через JSON-API и вернуть результат."""
        result = ParseResult(university_code=self.university.code)

        async with async_playwright() as pw:
            rc = await pw.request.new_context(
                extra_http_headers={"User-Agent": _USER_AGENT, "Referer": LIST_URL},
                timeout=settings.browser_timeout_ms,
            )
            try:
                report_id, report_upload_id, code_map = await self._fetch_meta(rc)

                for major in self.university.majors:
                    try:
                        major_result = await self._parse_major(
                            rc, major, report_id, report_upload_id, code_map
                        )
                        result.majors.append(major_result)
                    except Exception as exc:  # noqa: BLE001 (логируем и продолжаем)
                        msg = f"Направление {major.code}: {exc}"
                        logger.exception(msg)
                        result.errors.append(msg)
                    await asyncio.sleep(self.request_delay_seconds)

            except Exception as exc:  # noqa: BLE001 (падение всего запуска)
                msg = f"Критическая ошибка парсинга {self.university.code}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)
            finally:
                await rc.dispose()

        result.status = self._compute_status(result)
        return result

    async def _fetch_meta(self, rc) -> tuple[str, str, dict[str, list[dict]]]:
        """
        Скачать базовую страницу (очная+Бюджет) и разобрать встроенный JSON.

        Возвращает id отчёта, report_upload_id и карту {код -> [specialities]}.
        """
        resp = await rc.get(
            LIST_URL,
            params={
                "mode": "list",
                "education_level_sort_order": "1",
                "education_form_name": _EDUCATION_FORM,
                "fin_source_name": _FIN_SOURCE,
                "is_foreign": "0",
            },
        )
        if not resp.ok:
            raise RuntimeError(f"страница списка вернула статус {resp.status}")
        html = await resp.text()

        match = _META_RE.search(html)
        if not match:
            raise RuntimeError("не найден блок meta с идентификаторами отчёта")
        meta = json.loads(match.group(1))

        # Строим карту: код направления -> список его программ (specialities).
        code_map: dict[str, list[dict]] = {}
        for section in meta.get("sections", []):
            for sp in section.get("specialities", []):
                code_map.setdefault(str(sp.get("code")), []).append(sp)

        return meta.get("id", ""), meta.get("report_upload_id", ""), code_map

    async def _parse_major(
        self,
        rc,
        major: MajorConfig,
        report_id: str,
        report_upload_id: str,
        code_map: dict[str, list[dict]],
    ) -> MajorResult:
        """Собрать все программы направления и объединить абитуриентов."""
        specialities = code_map.get(major.code)
        if not specialities:
            raise RuntimeError("код направления не найден в отчёте")

        all_applicants = []
        total_places = 0
        has_places = False

        # Каждая программа направления запрашивается отдельным POST.
        for sp in specialities:
            places, applicants = await self._fetch_speciality(
                rc, report_id, report_upload_id, sp["id"]
            )
            all_applicants.extend(applicants)
            if places is not None:
                total_places += places
                has_places = True

        summary = MajorSummary(
            places=total_places if has_places else None,
            applications=len(all_applicants),
            agreements=sum(1 for a in all_applicants if a.has_agreement),
            list_formed_at=None,
        )

        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=None,
            summary=summary,
            applicants=all_applicants,
        )

    async def _fetch_speciality(
        self, rc, report_id: str, report_upload_id: str, speciality_id: str
    ) -> tuple[int | None, list]:
        """Запросить данные одной программы и разобрать её HTML-блок."""
        payload = {
            "report_priem_list_02_id": report_id,
            "speciality_ids": [str(speciality_id)],
            "filters": {
                "education_level_sort_order": "1",
                "report_upload_id": report_upload_id,
                "faculty_name": "",
                "program_name": "",
                "speciality": "",
                "applicant_code": "",
                "education_form_name": _EDUCATION_FORM,
                "fin_source_name": _FIN_SOURCE,
                "contract_status": "",
                "consent_status": "",
                "priority": "",
                "status": "",
                "is_foreign": "0",
            },
        }
        resp = await rc.post(
            DATA_URL,
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        if not resp.ok:
            raise RuntimeError(f"data вернул статус {resp.status}")
        data = await resp.json()

        places: int | None = None
        applicants: list = []
        # Обычно один блок на программу, но обходим все на всякий случай.
        for block in data.get("blocks", []):
            block_html = block.get("html", "")
            if not block_html:
                continue
            block_places, block_applicants = parse_block(block_html)
            if block_places is not None:
                places = (places or 0) + block_places
            applicants.extend(block_applicants)
        return places, applicants

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        """Определить статус запуска: success / partial / failed."""
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
