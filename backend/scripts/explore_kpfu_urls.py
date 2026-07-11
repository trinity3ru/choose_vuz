"""Подбор URL и разбор таблицы КФУ."""
import asyncio
import re
import sys
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://abiturient.kpfu.ru/entrant/abit_entrant_originals_list"
# p_faculty=9 — ИВМиИТ, p_level=1 — бакалавриат, p_inst=0 — КФУ, p_category=1 — бюджет
COMMON = "?p_level=1&p_inst=0&p_faculty=9&p_category=1"

TARGET_CODES = [
    "03.03.02", "03.03.03", "12.03.04", "01.03.02",
    "02.03.01", "02.03.02", "09.03.02", "09.03.03",
]


async def fetch_page(rc, url: str) -> str:
    resp = await rc.get(url)
    if not resp.ok:
        raise RuntimeError(f"{url} -> {resp.status}")
    body = await resp.body()
    for enc in ("utf-8", "cp1251", "windows-1251"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def parse_options(html: str, name: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    sel = soup.find("select", {"name": name})
    if not sel:
        return []
    return [(o.get("value", ""), o.get_text(strip=True)) for o in sel.find_all("option") if o.get("value")]


def parse_table(html: str) -> tuple[list[str], list[list[str]]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return [], []
    rows = table.find_all("tr")
    headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])] if rows else []
    data = []
    for tr in rows[1:]:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if cells:
            data.append(cells)
    return headers, data


async def main():
    async with async_playwright() as pw:
        rc = await pw.request.new_context(
            extra_http_headers={"User-Agent": "Mozilla/5.0"},
            timeout=60000,
        )
        try:
            # Шаг 1: специальности после выбора уровня+факультета
            url1 = BASE + COMMON
            html1 = await fetch_page(rc, url1)
            specs = parse_options(html1, "p_speciality")
            print("SPECIALITIES:", len(specs))
            for val, text in specs:
                print(f"  {val}: {text[:120]}")

            # Шаг 2: для каждой целевой специальности найти id
            code_map = {}
            for val, text in specs:
                m = re.match(r"(\d{2}\.\d{2}\.\d{2})", text)
                if m and m.group(1) in TARGET_CODES:
                    code_map[m.group(1)] = (val, text)

            print("\nMAPPED TARGET CODES:", code_map)

            # Шаг 3: форма обучения для первой специальности
            if code_map:
                first_code = next(iter(code_map))
                spec_id, _ = code_map[first_code]
                url2 = BASE + COMMON + f"&p_speciality={spec_id}"
                html2 = await fetch_page(rc, url2)
                forms = parse_options(html2, "p_typeofstudy")
                print("\nSTUDY FORMS:", forms)

                # Шаг 4: полный URL с очной формой
                fulltime = next((v for v, t in forms if "очн" in t.lower()), forms[0][0] if forms else "1")
                url3 = BASE + COMMON + f"&p_speciality={spec_id}&p_typeofstudy={fulltime}"
                html3 = await fetch_page(rc, url3)
                headers, rows = parse_table(html3)
                print(f"\nTABLE for {first_code}: headers={headers}")
                print(f"ROWS: {len(rows)}")
                if rows:
                    print("FIRST ROW:", rows[0])
                    print("LAST ROW:", rows[-1])
                # save sample
                with open("scripts/kpfu_sample.html", "w", encoding="utf-8") as f:
                    f.write(html3)
        finally:
            await rc.dispose()


if __name__ == "__main__":
    asyncio.run(main())
