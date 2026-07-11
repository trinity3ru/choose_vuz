"""Разведка API сайта priem2026.spmi.ru."""

import asyncio
import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as pw:
        rc = await pw.request.new_context(timeout=60000)
        html = (await (await rc.get(
            "https://priem2026.spmi.ru/list?direction_id=7&specialization_id=13580"
            "&applicant_type_id=2&applicant_consent_id=0"
        )).text())

        soup = BeautifulSoup(html, "html.parser")
        tr = soup.select_one("table.table-list tbody tr")
        if tr:
            aid = tr.get("data-applicant-id")
            abit = tr.get("data-abit-id")
            print("sample applicant:", aid, abit)

            for path in [
                f"/applicant/{aid}",
                f"/applicant/info/{aid}",
                f"/api/applicant/{aid}",
                f"/applicant/info?applicant_id={aid}",
                f"/applicant/info?applicant_id={aid}&abit_id={abit}",
            ]:
                resp = await rc.get(f"https://priem2026.spmi.ru{path}")
                body = await resp.text()
                print(path, resp.status, body[:300].replace("\n", " "))

        # Парсим строки таблицы
        rows = soup.select("table.table-list tbody tr")
        print("rows:", len(rows))
        if rows:
            tds = rows[0].find_all("td")
            print("cols:", len(tds))
            print("cells:", [td.get_text(" ", strip=True)[:40] for td in tds])

        # Ищем коды направлений в JS
        codes = set(re.findall(r"\d{2}\.\d{2}\.\d{2}", html))
        print("codes in page:", sorted(codes))

        for needle in ["buildTableInfoApplicant", "/base/", "spec_name", "fetch("]:
            idx = html.find(needle)
            print(needle, "at", idx)
            if idx >= 0:
                print(html[idx : idx + 400].replace("\n", " ")[:400])

        idx = html.find("urlRebuild")
        print("urlRebuild context:")
        print(html[idx - 500 : idx + 800].replace("\n", " ")[:1200])

        await rc.dispose()


if __name__ == "__main__":
    asyncio.run(main())
