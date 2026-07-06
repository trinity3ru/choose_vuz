"""
Парсер конкурсных списков Самарского политеха (СамГТУ).

Страница samgtu.ru/admission/competetivegroup — Angular-приложение; данные
берутся из двух JSON-эндпоинтов личного кабинета (lk.samgtu.ru):

- GET /publics/competetivegroup/kcps            -> список конкурсных групп
- GET /publics/competetivegroup/rating?id=<CGID> -> строки абитуриентов группы

Оба запроса — обычный GET JSON без cookie/CSRF, поэтому браузер не нужен:
используем HTTP-клиент Playwright (playwright.request, без запуска Chromium).

Направление из конфига сопоставляем с группой по коду в рантайме
(как у СПбПУ), а из строк рейтинга берём только категорию
«Основные места в рамках КЦП» (общий бюджетный конкурс).
"""

import asyncio
import logging

from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.samgtu_mapping import (
    MAIN_REPRESENTATION,
    PLACE_TYPE_BUDGET,
    STUDY_FORM_NAMES,
    row_to_applicant,
)
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

# Базовый адрес API личного кабинета СамГТУ.
API_BASE = "https://lk.samgtu.ru/publics/competetivegroup"
# Реферер обязателен не всегда, но добавляем для «похожести» на браузер.
REFERER = "https://samgtu.ru/admission/competetivegroup"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class SamgtuParser(BaseParser):
    """Парсер СамГТУ. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Собрать все направления вуза через JSON-API и вернуть результат."""
        result = ParseResult(university_code=self.university.code)

        async with async_playwright() as pw:
            # HTTP-клиент без запуска браузера.
            rc = await pw.request.new_context(
                extra_http_headers={"User-Agent": _USER_AGENT, "Referer": REFERER},
                timeout=settings.browser_timeout_ms,
            )
            try:
                # Список конкурсных групп (уровень бакалавриат/специалитет — d[0]).
                kcps_items = await self._fetch_kcps(rc)

                for major in self.university.majors:
                    try:
                        major_result = await self._parse_major(rc, major, kcps_items)
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

    async def _fetch_kcps(self, rc) -> list[dict]:
        """Скачать список конкурсных групп (уровень бакалавриат/специалитет)."""
        resp = await rc.get(f"{API_BASE}/kcps")
        if not resp.ok:
            raise RuntimeError(f"kcps вернул статус {resp.status}")
        data = await resp.json()
        if not data:
            raise RuntimeError("kcps вернул пустой ответ")
        # d[0] — приёмная кампания на бакалавриат/специалитет.
        return data[0].get("items", [])

    async def _parse_major(
        self, rc, major: MajorConfig, kcps_items: list[dict]
    ) -> MajorResult:
        """Собрать данные одного направления: найти CGID и скачать рейтинг."""
        group = self._match_group(kcps_items, major)
        if group is None:
            raise RuntimeError("не найдена конкурсная группа (очная, КЦП, СамГТУ)")

        cg_id = group["CompetetiveGroupID"]
        resp = await rc.get(f"{API_BASE}/rating", params={"id": cg_id})
        if not resp.ok:
            raise RuntimeError(f"rating вернул статус {resp.status}")
        rows = await resp.json()

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

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        """Определить статус запуска: success / partial / failed."""
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
