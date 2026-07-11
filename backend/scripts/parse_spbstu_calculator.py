"""Парсинг направлений с страницы калькулятора СПбПУ (очная, бюджет)."""

import json
import re
from pathlib import Path

SRC = Path(__file__).with_name("spbstu_calculator.txt")

HEADER_RE = re.compile(
    r"^(\d{2}\.\d{2}\.\d{2}(?:_\d+)?)\s+(.+?)"
    r"(?:Институт|Физико-механический институт|Гуманитарный институт|"
    r"Инженерно-строительный институт)"
)

BUDGET_OCHNAYA_RE = re.compile(r"^\d+Очная$")


def parse_programs(text: str) -> list[dict]:
    lines = text.splitlines()
    programs: list[dict] = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = HEADER_RE.match(line)
        if not m:
            i += 1
            continue

        code, name = m.group(1), m.group(2).strip()
        has_budget_och = False
        j = i + 1
        in_budget = False
        while j < len(lines) and j < i + 25:
            chunk = lines[j].strip()
            if HEADER_RE.match(chunk):
                break
            if chunk == "Бюджет":
                in_budget = True
            elif chunk == "Контракт":
                in_budget = False
            elif in_budget and BUDGET_OCHNAYA_RE.match(chunk):
                has_budget_och = True
                break
            j += 1

        if has_budget_och:
            programs.append({"code": code, "name": name})
        i += 1

    return programs


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    programs = parse_programs(text)
    print(f"Programs with budget+och: {len(programs)}")
    for p in programs:
        print(f"{p['code']}\t{p['name']}")

    out = Path(__file__).with_name("spbstu_majors_budget_och.json")
    out.write_text(json.dumps(programs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
