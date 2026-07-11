"""Разведка кодов направлений SPMI через API карточки абитуриента."""

import asyncio
import json
import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

TARGET_CODES = {
    "09.03.01": "Информатика и вычислительная техника",
    "09.03.02": "Информационные системы и технологии",
    "13.03.01": "Теплоэнергетика и теплотехника",
    "13.03.02": "Электроэнергетика и электротехника",
}

GROUPS = {
    "it": ("13580", "2"),
    "energy": ("13579", "1"),
}


async def fetch_list(rc, spec_id: str, applicant_type: str) -> str:
    url = (
        "https://priem2026.spmi.ru/list?direction_id=7"
        f"&specialization_id={spec_id}&applicant_type_id={applicant_type}"
        "&applicant_consent_id=0"
    )
    resp = await rc.get(url)
    return await resp.text()


async def main() -> None:
    async with async_playwright() as pw:
        rc = await pw.request.new_context(timeout=60000)
        spec_names: set[str] = set()

        for group, (spec_id, app_type) in GROUPS.items():
            html = await fetch_list(rc, spec_id, app_type)
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("table.table-list tbody tr")[:5]
            print(f"\n=== {group} rows sample: {len(rows)} ===")
            for tr in rows:
                abit_id = tr.get("data-abit-id")
                applicant_id = tr.get("data-applicant-id")
                api = f"https://priem2026.spmi.ru/applicant/{abit_id}/7/{spec_id}"
                data = await (await rc.get(api)).json()
                for item in data.values():
                    if isinstance(item, dict):
                        spec_names.add(item.get("spec_name", ""))
                        spec_names.add(item.get("spec_title_modified_name", ""))
                print(applicant_id, "entries:", len(data))

        print("\nAll spec names from sample:")
        for name in sorted(spec_names):
            if name:
                print("-", name)
                for code, title in TARGET_CODES.items():
                    if title.lower() in name.lower() or code in name:
                        print("  MATCH", code)

        # Ищем коды в HTML всех specialization ссылок
        html = await (await rc.get("https://priem2026.spmi.ru/specialization?direction_id=7")).text()
        for code in TARGET_CODES:
            if code in html:
                print("code in specs page:", code)
            if TARGET_CODES[code] in html:
                print("name in specs page:", code, TARGET_CODES[code])

        await rc.dispose()


if __name__ == "__main__":
    asyncio.run(main())
