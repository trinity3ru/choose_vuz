"""
Парсер конкурсных списков СПбГУТ (priem.sut.ru).

Механика сайта (отличается от СПбПУ):
1. На странице есть форма и скрытый token. Playwright открывает страницу,
   получает сессию (cookies) и token.
2. Конкурсные группы (аналог направлений) грузятся AJAX-запросом get_spec.
3. Таблица результатов приходит POST-запросом на саму страницу и возвращается
   как HTML целой страницы — разбираем таблицу через BeautifulSoup.
"""

import asyncio
import json
import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.async_api import Page, async_playwright

from app.core.config import settings
from app.parser.base import BaseParser
from app.parser.sut_mapping import (
    EDUCATION_LEVEL_BACHELOR,
    FINANCE_TYPE_CODES,
    STUDY_FORM_CODES,
    row_to_applicant,
)
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary, ParseResult

logger = logging.getLogger(__name__)

# Код организации СПбГУТ в форме сайта (поле general).
ORG_CODE = "101"
AJAX_URL = "https://priem.sut.ru/new_site/inc/ajax_abitur_2025.php"
# Регулярка для извлечения option (id + текст) из ответа get_spec.
_OPTION_RE = re.compile(r'<option\s+value="(\d+)">([^<]+)</option>')


class SutParser(BaseParser):
    """Парсер СПбГУТ. Реализует интерфейс BaseParser.parse()."""

    async def parse(self) -> ParseResult:
        """Открыть браузер, собрать направления вуза, вернуть результат."""
        result = ParseResult(university_code=self.university.code)
        url = str(self.university.url)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=settings.headless)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded",
                                timeout=settings.browser_timeout_ms)
                token = await page.get_attribute('input[name="token"]', "value") or ""

                # Коды формы/основы берём из первого направления (у всех одинаковые).
                first = self.university.majors[0].params
                form_code = STUDY_FORM_CODES[first.study_form]
                base_code = FINANCE_TYPE_CODES[first.finance_type]
                groups = await self._fetch_groups(page, url, form_code, base_code)

                for major in self.university.majors:
                    try:
                        major_result = await self._parse_major(
                            page, url, major, groups, form_code, base_code, token
                        )
                        result.majors.append(major_result)
                    except Exception as exc:  # noqa: BLE001
                        msg = f"Направление {major.code}: {exc}"
                        logger.exception(msg)
                        result.errors.append(msg)
                        await self._save_screenshot(page, major.code)
                    await asyncio.sleep(self.request_delay_seconds)

            except Exception as exc:  # noqa: BLE001
                msg = f"Критическая ошибка парсинга {self.university.code}: {exc}"
                logger.exception(msg)
                result.errors.append(msg)
                await self._save_screenshot(page, self.university.code)
            finally:
                await browser.close()

        result.status = self._compute_status(result)
        return result

    async def _fetch_groups(
        self, page: Page, url: str, form_code: str, base_code: str
    ) -> list[tuple[str, str]]:
        """Получить конкурсные группы: список (id, title)."""
        payload = {
            "action": "get_spec",
            "education_base_to": EDUCATION_LEVEL_BACHELOR,
            "training_form": form_code,
            "general": ORG_CODE,
            "training_type": base_code,
        }
        resp = await page.request.post(
            AJAX_URL,
            data="jsonData=" + json.dumps(payload),
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": url,
            },
        )
        if not resp.ok:
            raise RuntimeError(f"get_spec вернул статус {resp.status}")
        data = await resp.json()
        selecter = data.get("selecter", "")
        return _OPTION_RE.findall(selecter)

    async def _parse_major(
        self,
        page: Page,
        url: str,
        major: MajorConfig,
        groups: list[tuple[str, str]],
        form_code: str,
        base_code: str,
        token: str,
    ) -> MajorResult:
        """Собрать данные одного направления: таблицу абитуриентов."""
        group_id = self._match_group_id(groups, major.code)
        if group_id is None:
            raise RuntimeError("не найдено в списке конкурсных групп сайта")

        resp = await page.request.post(
            url,
            form={
                "general": ORG_CODE,
                "education_base_to": EDUCATION_LEVEL_BACHELOR,
                "training_form": form_code,
                "training_type": base_code,
                "1cunv_groupab": group_id,
                "action": "get_result_new",
                "rekzach": "0",
                "token": token,
            },
            headers={"Referer": url},
        )
        if not resp.ok:
            raise RuntimeError(f"get_result_new вернул статус {resp.status}")

        html = await resp.text()
        applicants = self._parse_table(html)

        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=int(group_id),
            # Кол-во мест сайт в этом ответе не отдаёт; фиксируем число заявлений.
            summary=MajorSummary(applications=len(applicants)),
            applicants=applicants,
        )

    @staticmethod
    def _parse_table(html: str) -> list:
        """Разобрать HTML: строки данных имеют id вида tr_11_N."""
        soup = BeautifulSoup(html, "html.parser")
        applicants = []
        for row in soup.select("tr[id^='tr_11_']"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            applicant = row_to_applicant(cells)
            if applicant is not None:
                applicants.append(applicant)
        return applicants

    @staticmethod
    def _match_group_id(groups: list[tuple[str, str]], major_code: str) -> str | None:
        """Найти id конкурсной группы по коду направления (начало title)."""
        for group_id, title in groups:
            # title вида "11.03.02 Очное Бюджет Название" — сверяем код-префикс.
            if title.strip().split(" ", 1)[0] == major_code:
                return group_id
        return None

    async def _save_screenshot(self, page: Page, tag: str) -> None:
        """Сохранить скриншот страницы при ошибке (для диагностики)."""
        try:
            settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = settings.screenshots_dir / f"{self.university.code}_{tag}_{stamp}.png"
            await page.screenshot(path=str(path), full_page=True)
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось сохранить скриншот для %s", tag)

    @staticmethod
    def _compute_status(result: ParseResult) -> str:
        """Определить статус запуска: success / partial / failed."""
        if not result.errors:
            return "success"
        if result.majors:
            return "partial"
        return "failed"
