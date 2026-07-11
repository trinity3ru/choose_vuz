"""
Парсер конкурсных списков СПбГУ (enrollelists.spbu.ru).

Страница reports/PriemList02.php — Vue-приложение; данные грузятся AJAX.
В HTML встроен JSON (#priem-list-02-report-meta) с идентификаторами отчёта и
списком направлений (specialities) с их UUID. Сами строки берём из эндпоинта:

    POST /api/reports/priem-list-02/data
    тело: {report_priem_list_02_id, speciality_ids:[UUID], filters:{...}}
    ответ: {blocks:[{html}]} — готовый HTML таблицы (разбираем в spbgu_mapping).

Всё работает по обычным GET/POST без cookie/CSRF, поэтому браузер не нужен —
обычные запросы через httpx.

Под одним кодом направления бывает несколько образовательных программ; по
решению парсим ВСЕ программы направления и объединяем в один список.
"""

import json
import logging
import re

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.spbgu_mapping import parse_block
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)

# Адреса сайта.
LIST_URL = "https://enrollelists.spbu.ru/reports/PriemList02.php"
DATA_URL = "https://enrollelists.spbu.ru/api/reports/priem-list-02/data"

# Регулярка для вырезания встроенного JSON с метаданными отчёта.
_META_RE = re.compile(
    r'id="priem-list-02-report-meta">(.*?)</script>', re.DOTALL
)

# Фильтры формы для очной бюджетной кампании (бакалавриат/специалитет).
_EDUCATION_FORM = "очная"
_FIN_SOURCE = "Бюджет"

# Контекст подготовки: id отчёта, id выгрузки, карта {код -> [specialities]}.
_Meta = tuple[str, str, dict[str, list[dict]]]


class SpbguParser(HttpParser):
    """Парсер СПбГУ. Реализует интерфейс HttpParser."""

    def extra_headers(self) -> dict[str, str]:
        return {"Referer": LIST_URL}

    async def _prepare(self, client: httpx.AsyncClient) -> _Meta:
        """
        Скачать базовую страницу (очная+Бюджет) и разобрать встроенный JSON.

        Возвращает id отчёта, report_upload_id и карту {код -> [specialities]}.
        """
        resp = await client.get(
            LIST_URL,
            params={
                "mode": "list",
                "education_level_sort_order": "1",
                "education_form_name": _EDUCATION_FORM,
                "fin_source_name": _FIN_SOURCE,
                "is_foreign": "0",
            },
        )
        raise_for_status(resp, "страница списка")
        html = resp.text

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
        self, client: httpx.AsyncClient, major: MajorConfig, context: _Meta
    ) -> MajorResult:
        """Собрать все программы направления и объединить абитуриентов."""
        report_id, report_upload_id, code_map = context
        specialities = code_map.get(major.code)
        if not specialities:
            raise RuntimeError("код направления не найден в отчёте")

        all_applicants = []
        total_places = 0
        has_places = False

        # Каждая программа направления запрашивается отдельным POST.
        for sp in specialities:
            places, applicants = await self._fetch_speciality(
                client, report_id, report_upload_id, sp["id"]
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
        self, client: httpx.AsyncClient, report_id: str, report_upload_id: str, speciality_id: str
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
        resp = await client.post(
            DATA_URL,
            json=payload,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        raise_for_status(resp, "data")
        data = resp.json()

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
