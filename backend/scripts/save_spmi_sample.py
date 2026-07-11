import asyncio
import json

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as pw:
        rc = await pw.request.new_context(timeout=60000)
        html = await (
            await rc.get(
                "https://priem2026.spmi.ru/list?direction_id=7&specialization_id=13580"
                "&applicant_type_id=2&applicant_consent_id=0"
            )
        ).text()
        tr = BeautifulSoup(html, "html.parser").select_one("table.table-list tbody tr")
        abit_id = tr["data-abit-id"]
        data = await (await rc.get(f"https://priem2026.spmi.ru/applicant/{abit_id}/7/13580")).json()
        with open("spmi_applicant_sample.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("saved", len(data))
        await rc.dispose()


asyncio.run(main())
