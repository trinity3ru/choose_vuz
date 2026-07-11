"""Разведка структуры списков ГУАП (priem.guap.ru)."""

import re
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

INDEX_URL = "https://priem.guap.ru/bach/lists/list_1_1_1_1"
SPEC_URL = "https://priem.guap.ru/bach/lists/list_1_75_1_1_1_f_1"
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


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def main() -> None:
    scripts_dir = Path(__file__).resolve().parent
    index_html = fetch(INDEX_URL)
    spec_html = fetch(SPEC_URL)
    (scripts_dir / "guap_index.html").write_text(index_html, encoding="utf-8")
    (scripts_dir / "guap_spec.html").write_text(spec_html, encoding="utf-8")
    print("saved index", len(index_html), "spec", len(spec_html))

    soup = BeautifulSoup(index_html, "html.parser")
    links: list[tuple[str, str]] = []
    for a in soup.select("a[href*='/bach/lists/']"):
        href = a.get("href", "")
        text = a.get_text(" ", strip=True)
        if href and text:
            links.append((href, text))

    print("links", len(links))
    for href, text in links[:20]:
        print(href, "|", text[:100])

    print("\n--- codes ---")
    for code in CODES:
        matches = [(h, t) for h, t in links if code in t]
        print(code, "->", len(matches))
        for h, t in matches[:3]:
            print(" ", h, "|", t[:120])

    soup2 = BeautifulSoup(spec_html, "html.parser")
    title = soup2.title.get_text(strip=True) if soup2.title else ""
    print("\ntitle:", title)

    tables = soup2.find_all("table")
    print("tables", len(tables))
    for i, table in enumerate(tables[:5]):
        print("table", i, "id=", table.get("id"), "class=", table.get("class"))
        for tr in table.find_all("tr")[:4]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            print(" ", cells)

    # Ищем блоки с местами и датой формирования.
    for pattern in [r"мест[а-я]*\s*:\s*(\d+)", r"(\d+)\s*мест", r"План\s+при[её]ма"]:
        for m in re.finditer(pattern, spec_html, re.IGNORECASE):
            start = max(0, m.start() - 40)
            print("match:", spec_html[start : m.end() + 40].replace("\n", " ")[:120])


if __name__ == "__main__":
    main()
