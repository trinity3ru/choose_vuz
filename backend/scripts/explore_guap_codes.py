"""Извлечение ссылок на списки ГУАП по кодам направлений."""

from pathlib import Path

from bs4 import BeautifulSoup

CODES = [
    "01.03.02",
    "03.03.01",
    "09.03.01",
    "09.03.02",
    "09.03.03",
    "12.03.04",
    "13.03.02",
    "16.03.01",
]

html = Path(__file__).resolve().parent.joinpath("guap_index.html").read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")
table = soup.find("table", id="tablestat")
if not table:
    raise SystemExit("tablestat not found")

headers = [th.get_text(" ", strip=True) for th in table.find("thead").find_all("th")]
print("headers:", headers)
budget_col = None
for i, h in enumerate(headers):
    if "основ" in h.lower() and "бюджет" in h.lower():
        budget_col = i
        break
print("budget_col", budget_col)

for tr in table.find("tbody").find_all("tr"):
    tds = tr.find_all("td")
    if len(tds) < 2:
        continue
    code = tds[0].get_text(strip=True)
    if code not in CODES:
        continue
    name = tds[1].get_text(" ", strip=True)
    cell = tds[budget_col] if budget_col is not None else None
    link = cell.find("a") if cell else None
    href = link.get("href", "").replace("\\", "/") if link else None
    count = link.get_text(strip=True) if link else "-"
    print(f"{code} | apps={count} | {href} | {name[:80]}")
