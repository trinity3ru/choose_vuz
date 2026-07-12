"""
Парсер конкурсных списков Самарского политеха (СамГТУ).

Страница samgtu.ru/admission/competetivegroup — Angular-приложение; данные
берутся из двух JSON-эндпоинтов личного кабинета (lk.samgtu.ru):

- GET /publics/competetivegroup/kcps            -> список конкурсных групп
- GET /publics/competetivegroup/rating?id=<CGID> -> строки абитуриентов группы

Оба запроса — обычный GET JSON без cookie/CSRF, поэтому браузер не нужен:
обычные запросы через httpx.

Направление из конфига сопоставляем с группой по коду в рантайме
(как у СПбПУ), а из строк рейтинга берём только категорию
«Основные места в рамках КЦП» (общий бюджетный конкурс).
"""

import logging

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.samgtu_mapping import (
    MAIN_REPRESENTATION,
    PLACE_TYPE_BUDGET,
    STUDY_FORM_NAMES,
    row_to_applicant,
)
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)

# Базовый адрес API личного кабинета СамГТУ.
API_BASE = "https://lk.samgtu.ru/publics/competetivegroup"
# Реферер обязателен не всегда, но добавляем для «похожести» на браузер.
REFERER = "https://samgtu.ru/admission/competetivegroup"


class SamgtuParser(HttpParser):
    """Парсер СамГТУ. Реализует интерфейс HttpParser."""

    # У lk.samgtu.ru просрочен TLS-сертификат (обнаружено 2026-07-12,
    # certificate has expired). Данные публичные — проверку отключаем.
    # TODO: вернуть True, когда вуз обновит сертификат.
    verify_ssl = False

    def extra_headers(self) -> dict[str, str]:
        return {"Referer": REFERER}

    async def _prepare(self, client: httpx.AsyncClient) -> list[dict]:
        """Скачать список конкурсных групп (уровень бакалавриат/специалитет)."""
        resp = await client.get(f"{API_BASE}/kcps")
        raise_for_status(resp, "kcps")
        data = resp.json()
        if not data:
            raise RuntimeError("kcps вернул пустой ответ")
        # d[0] — приёмная кампания на бакалавриат/специалитет.
        return data[0].get("items", [])

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: list[dict]
    ) -> MajorResult:
        """Собрать данные одного направления: найти CGID и скачать рейтинг."""
        group = self._match_group(context, major)
        if group is None:
            raise RuntimeError("не найдена конкурсная группа (очная, КЦП, СамГТУ)")

        cg_id = group["CompetetiveGroupID"]
        resp = await client.get(f"{API_BASE}/rating", params={"id": cg_id})
        raise_for_status(resp, "rating")
        rows = resp.json()

        # Оставляем только общий бюджетный конкурс (Основные места в рамках КЦП).
        budget_rows = [r for r in rows if str(r.get("PlaceTypeID")) == PLACE_TYPE_BUDGET]
        applicants = [row_to_applicant(r) for r in budget_rows]

        summary = MajorSummary(
            places=self._to_int(group.get("KCP")),
            applications=len(applicants),
            agreements=sum(1 for a in applicants if a.has_agreement),
            list_formed_at=None,
        )

        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=self._to_int(cg_id),
            summary=summary,
            applicants=applicants,
        )

    @staticmethod
    def _match_group(kcps_items: list[dict], major: MajorConfig) -> dict | None:
        """
        Найти конкурсную группу по коду направления из конфига.

        Условия: название начинается с кода, очная форма, головной вуз (не филиал)
        и категория «Основные места в рамках КЦП» (PlaceTypeID=1).
        """
        study_form = STUDY_FORM_NAMES.get(major.params.study_form, major.params.study_form)
        for item in kcps_items:
            name = str(item.get("CompetetiveGroupName", ""))
            if (
                name.startswith(major.code)
                and item.get("StudyFormName") == study_form
                and item.get("Representation") == MAIN_REPRESENTATION
                and str(item.get("PlaceTypeID")) == PLACE_TYPE_BUDGET
            ):
                return item
        return None

    @staticmethod
    def _to_int(value: object) -> int | None:
        """Локальный помощник: строку/число привести к int (или None)."""
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return None
