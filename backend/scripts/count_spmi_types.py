import asyncio

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


async def count(spec_id: str, app_type: str) -> None:
    url = (
        "https://priem2026.spmi.ru/list?direction_id=7"
        f"&specialization_id={spec_id}&applicant_type_id={app_type}"
        "&applicant_consent_id=0"
    )
    async with async_playwright() as pw:
        rc = await pw.request.new_context(timeout=120000)
        html = await (await rc.get(url)).text()
        rows = BeautifulSoup(html, "html.parser").select("table.table-list tbody tr")
        print(spec_id, "type", app_type, "rows", len(rows))
        await rc.dispose()


async def main() -> None:
    for spec in ["13580", "13579"]:
        for t in ["1", "2"]:
            await count(spec, t)


asyncio.run(main())
