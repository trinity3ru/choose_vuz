"""
Гибридный парсер конкурсных списков СПбПУ.

Идея: браузер (Playwright) открывает страницу один раз, чтобы получить
сессию и cookies. Дальше все данные забираем прямыми запросами к API сайта
через контекст браузера (page.request) — без эмуляции кликов и разбора HTML.
Данные приходят готовым JSON.

Эндпоинты сайта:
- POST /home/get-code-list      -> список направлений [{id, title}]
- GET  /home/get-abit-list      -> строки таблицы абитуриентов
- POST /home/get-direction-info -> сводка по направлению
"""

import asyncio
import json
import logging
from datetime import datetime

from playwright.async_api import Page, async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.spbstu_mapping import (
    FINANCE_TYPE_CODES,
    STUDY_FORM_CODES,
    parse_summary,
    row_to_applicant,
)
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, ParseResult

logger = logging.getLogger(__name__)

# Базовый адрес сайта для построения полных URL эндпоинтов.
BASE = "https://my.spbstu.ru"


class SpbstuParser(BaseParser):
    """Парсер СПбПУ. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Открыть браузер, собрать все направления вуза, вернуть результат."""
        result = ParseResult(university_code=self.university.code)
        url = str(self.university.url)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=settings.headless,
                # В Docker-контейнере (root) Chromium работает без sandbox.
                chromium_sandbox=not settings.browser_no_sandbox,
            )
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded",
                                timeout=settings.browser_timeout_ms)
                csrf = await self._get_csrf(page)

                # Список направлений сайта: title вида "09.03.04 Название".
                # Все направления в конфиге имеют одинаковую форму/условия,
                # берём коды фильтров из первого направления.
                first_params = self.university.majors[0].params
                form_code = STUDY_FORM_CODES[first_params.study_form]
                finance_code = FINANCE_TYPE_CODES[first_params.finance_type]
                code_list = await self._fetch_code_list(page, csrf, form_code, finance_code)

                # Обходим направления из конфига по очереди.
                for major in self.university.majors:
                    try:
                        major_result = await self._parse_major(
                            page, major, code_list, form_code, finance_code, csrf
                        )
                        result.majors.append(major_result)
                    except Exception as exc:  # noqa: BLE001 (логируем и продолжаем)
                        msg = f"Направление {major.code}: {exc}"
                        logger.exception(msg)
                        result.errors.append(msg)
                        await self._save_screenshot(page, major.code)
                    # Пауза между направлениями (защита от блокировок).
                    await asyncio.sleep(self.request_delay_seconds)

            except Exception as exc:  # noqa: BLE001 (падение всего запуска)
                msg = f"Критическая ошибка парсинга {self.university.code}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)
                await self._save_screenshot(page, self.university.code)
            finally:
                await browser.close()

        result.status = self._compute_status(result)
        return result

    async def _get_csrf(self, page: Page) -> str:
        """Достать csrftoken из cookies (нужен для POST-запросов сайта)."""
        cookies = await page.context.cookies()
        for cookie in cookies:
            if cookie["name"] == "csrftoken":
                return cookie["value"]
        return ""

    async def _fetch_code_list(
        self, page: Page, csrf: str, form_code: str, finance_code: str
    ) -> list[dict]:
        """Получить список направлений вуза (id + title)."""
        resp = await page.request.post(
            f"{BASE}/home/get-code-list",
            data=json.dumps(
                {"id_1": form_code, "id_2": finance_code, "education_level": "bachelor"}
            ),
            headers=self._post_headers(csrf),
        )
        if not resp.ok:
            raise RuntimeError(f"get-code-list вернул статус {resp.status}")
        data = await resp.json()
        return data.get("code_list", [])

    async def _parse_major(
        self,
        page: Page,
        major: MajorConfig,
        code_list: list[dict],
        form_code: str,
        finance_code: str,
        csrf: str,
    ) -> MajorResult:
        """Собрать данные одного направления: сводку и строки абитуриентов."""
        internal_id = self._match_internal_id(code_list, major.code)
        if internal_id is None:
            raise RuntimeError("не найдено в списке направлений сайта")

        # Сводка по направлению (места, заявления, согласия).
        info_resp = await page.request.post(
            f"{BASE}/home/get-direction-info",
            data=json.dumps(
                {
                    "id_3": str(internal_id),
                    "education_level": "bachelor",
                    "condition": finance_code,
                }
            ),
            headers=self._post_headers(csrf),
        )
        summary = parse_summary(await info_resp.json()) if info_resp.ok else None

        # Строки таблицы абитуриентов.
        list_resp = await page.request.get(
            f"{BASE}/home/get-abit-list",
            params={
                "filter_1": form_code,
                "filter_2": finance_code,
                "filter_3": str(internal_id),
                "education_level": "bachelor",
            },
            headers={"Referer": str(self.university.url)},
        )
        if not list_resp.ok:
            raise RuntimeError(f"get-abit-list вернул статус {list_resp.status}")
        raw = await list_resp.json()
        applicants = [row_to_applicant(item) for item in raw.get("results", [])]

        # Поле count_agreement в сводке сайта не заполняется (всегда 0),
        # поэтому согласия считаем по строкам списка — как в остальных вузах.
        if summary is not None:
            summary.agreements = sum(1 for a in applicants if a.has_agreement)

        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=internal_id,
            summary=summary,
            applicants=applicants,
        )

    @staticmethod
    def _match_internal_id(code_list: list[dict], major_code: str) -> int | None:
        """Найти внутренний id направления по его коду (начало title)."""
        for entry in code_list:
            title = str(entry.get("title", "")).strip()
            # title вида "09.03.04 Программная инженерия" — сверяем префикс.
            if title.split(" ", 1)[0] == major_code:
                return entry.get("id")
        return None

    def _post_headers(self, csrf: str) -> dict[str, str]:
        """Заголовки для POST-запросов: тип, CSRF и обязательный Referer."""
        return {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
            "Referer": str(self.university.url),
        }

    async def _save_screenshot(self, page: Page, tag: str) -> None:
        """Сохранить скриншот страницы при ошибке (для диагностики)."""
        try:
            settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = settings.screenshots_dir / f"{self.university.code}_{tag}_{stamp}.png"
            await page.screenshot(path=str(path), full_page=True)
        except Exception:  # noqa: BLE001 (скриншот не критичен)
            logger.warning("Не удалось сохранить скриншот для %s", tag)

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        """Определить статус запуска: success / partial / failed."""
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
