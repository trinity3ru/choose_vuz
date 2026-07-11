"""Собрать уникальные названия программ из списка SPMI."""

import asyncio
import json

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


async def collect(group_name: str, spec_id: str, applicant_type: str) -> None:
    async with async_playwright() as pw:
        rc = await pw.request.new_context(timeout=120000)
        url = (
            "https://priem2026.spmi.ru/list?direction_id=7"
            f"&specialization_id={spec_id}&applicant_type_id={applicant_type}"
            "&applicant_consent_id=0"
        )
        html = await (await rc.get(url)).text()
        rows = BeautifulSoup(html, "html.parser").select("table.table-list tbody tr")
        print(group_name, "rows", len(rows))

        titles: set[str] = set()
        names: set[str] = set()
        for tr in rows[:30]:
            abit_id = tr.get("data-abit-id")
            data = await (await rc.get(f"https://priem2026.spmi.ru/applicant/{abit_id}/7/{spec_id}")).json()
            for key, item in data.items():
                if not isinstance(item, dict):
                    continue
                if item.get("konkurs_name") == "Общий конкурс" and item.get("spec_link", "").endswith(
                    f"specialization_id={spec_id}&direction_id=7"
                ):
                    titles.add(str(item.get("spec_title_modified_name", "")))
                    names.add(str(item.get("spec_name", "")))

        print("titles:", sorted(titles))
        print("names:", sorted(names))
        await rc.dispose()


async def main() -> None:
    await collect("it", "13580", "2")
    await collect("energy", "13579", "1")


if __name__ == "__main__":
    asyncio.run(main())
