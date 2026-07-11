"""Полная разведка специальностей КФУ по факультетам."""
import asyncio
import re
import sys
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://abiturient.kpfu.ru/entrant/abit_entrant_originals_list"
TARGET_CODES = [
    "03.03.02", "03.03.03", "12.03.04", "01.03.02",
    "02.03.01", "02.03.02", "09.03.02", "09.03.03",
]
FACULTY = 9  # ИВМиИТ


async def fetch_text(rc, url: str) -> str:
    resp = await rc.get(url)
    body = await resp.body()
    for enc in ("utf-8", "cp1251"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def parse_options(html: str, name: str):
    soup = BeautifulSoup(html, "html.parser")
    sel = soup.find("select", {"name": name})
    if not sel:
        return []
    return [(o.get("value", ""), o.get_text(" ", strip=True)) for o in sel.find_all("option") if o.get("value")]


def parse_table(html: str):
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    best = []
    for table in tables:
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if len(rows) > len(best):
            best = rows
    return best


def pick_spec_id(specs, code: str) -> tuple[str, str] | None:
    """Берём российскую очную программу, не для иностранцев."""
    candidates = []
    for val, text in specs:
        if not text.startswith(code):
            continue
        if "иностран" in text.lower():
            continue
        candidates.append((val, text))
    if not candidates:
        for val, text in specs:
            if text.startswith(code):
                candidates.append((val, text))
    return candidates[0] if candidates else None


async def main():
    async with async_playwright() as pw:
        rc = await pw.request.new_context(timeout=60000)
        try:
            common = f"?p_level=1&p_inst=0&p_faculty={FACULTY}&p_category=1"
            html = await fetch_text(rc, BASE + common)
            specs = parse_options(html, "p_speciality")
            print(f"Faculty {FACULTY}: {len(specs)} specialities")
            for code in TARGET_CODES:
                picked = pick_spec_id(specs, code)
                print(f"  {code}: {picked}")

            # Тест полного URL для 01.03.02
            picked = pick_spec_id(specs, "01.03.02")
            if picked:
                spec_id, title = picked
                url = BASE + common + f"&p_speciality={spec_id}&p_typeofstudy=1"
                html2 = await fetch_text(rc, url)
                rows = parse_table(html2)
                print(f"\n01.03.02 rows={len(rows)-1 if rows else 0}, title={title}")
                if rows:
                    print("HEADERS:", rows[0])
                    print("ROW1:", rows[1] if len(rows) > 1 else None)

            # Поиск недостающих кодов по другим факультетам
            print("\n=== SEARCH OTHER FACULTIES ===")
            html0 = await fetch_text(rc, BASE + "?p_level=1&p_inst=0")
            faculties = parse_options(html0, "p_faculty")
            for fac_id, fac_name in faculties:
                if not fac_id:
                    continue
                h = await fetch_text(rc, BASE + f"?p_level=1&p_inst=0&p_faculty={fac_id}&p_category=1")
                s = parse_options(h, "p_speciality")
                for code in TARGET_CODES:
                    p = pick_spec_id(s, code)
                    if p:
                        print(f"  {code} @ faculty {fac_id} ({fac_name[:40]}): {p[0]} {p[1][:80]}")
        finally:
            await rc.dispose()


if __name__ == "__main__":
    asyncio.run(main())
