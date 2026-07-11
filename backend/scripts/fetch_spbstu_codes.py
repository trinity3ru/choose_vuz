"""Временный скрипт: получить список направлений с сайта СПбПУ (очная, бюджет)."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from app.core.config import settings
from app.parser.spbstu_mapping import FINANCE_TYPE_CODES, STUDY_FORM_CODES

BASE = "https://my.spbstu.ru"
URL = "https://my.spbstu.ru/home/abit/list-applicants/bachelor"


async def main() -> None:
    form_code = STUDY_FORM_CODES["Очная"]
    finance_code = FINANCE_TYPE_CODES["Бюджетная основа"]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=settings.headless)
        page = await browser.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
        cookies = await page.context.cookies()
        csrf = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")

        resp = await page.request.post(
            f"{BASE}/home/get-code-list",
            data=json.dumps(
                {"id_1": form_code, "id_2": finance_code, "education_level": "bachelor"}
            ),
            headers={
                "Content-Type": "application/json",
                "X-CSRFToken": csrf,
                "Referer": URL,
            },
        )
        data = await resp.json()
        code_list = data.get("code_list", [])
        print(f"Total directions on site: {len(code_list)}")
        for item in code_list:
            title = str(item.get("title", "")).strip()
            code = title.split(" ", 1)[0]
            name = title.split(" ", 1)[1] if " " in title else ""
            print(f"{code}\t{name}\t(id={item.get('id')})")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
