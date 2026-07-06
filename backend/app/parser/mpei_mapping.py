"""
Преобразование HTML-списка МЭИ (pk.mpei.ru) в чистые модели.

Каждое направление — отдельная страница entrants_listN.html с одной таблицей
«По конкурсу» (общий бюджетный конкурс). Строки данных: tr[id^=p], 15 колонок.
Раздельные баллы по предметам (колонки 3–5) не храним.
"""

import re

from bs4 import BeautifulSoup

from app.schemas.parser_schema import ApplicantRow

# Число колонок в строке данных.
_DATA_COLS = 15

# Места в шапке: «Количество вакантных мест: 100».
_PLACES_RE = re.compile(r"вакантных\s+мест:\s*(\d+)", re.IGNORECASE)


def to_int(value: object) -> int | None:
    """Привести значение ячейки к целому (пустое/прочерк -> None)."""
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (ValueError, TypeError):
        return None


def _is_yes(value: str) -> bool:
    return value.strip().lower() == "да"


def row_to_applicant(cells: list[str]) -> ApplicantRow:
    """Собрать ApplicantRow из 15 ячеек строки таблицы МЭИ."""
    note = cells[14].strip()
    pref9, pref10 = cells[7].strip(), cells[8].strip()
    preferential = "Да" if (_is_yes(pref9) or _is_yes(pref10)) else None

    return ApplicantRow(
        applicant_code=cells[0].strip(),
        is_bvi="бви" in note.lower(),
        total_score=to_int(cells[1]),
        # «Сумма без ИД» — сумма баллов за вступительные испытания.
        exam_score=to_int(cells[2]),
        achievement_score=to_int(cells[6]),
        target_achievement_score=None,
        preferential_right=preferential,
        priority=to_int(cells[10]),
        has_agreement=_is_yes(cells[9]),
        review_status=note or None,
    )


def parse_page(html: str) -> tuple[int | None, list[ApplicantRow]]:
    """
    Разобрать HTML страницы entrants_listN.html.

    Возвращает (число вакантных мест, список абитуриентов).
    """
    places_match = _PLACES_RE.search(html)
    places = to_int(places_match.group(1)) if places_match else None

    soup = BeautifulSoup(html, "html.parser")
    applicants: list[ApplicantRow] = []

    for tr in soup.select("table.concurs-list tr[id^=p]"):
        tds = tr.find_all("td")
        if len(tds) != _DATA_COLS:
            continue
        cells = [td.get_text(strip=True) for td in tds]
        if not cells[0].strip():
            continue
        applicants.append(row_to_applicant(cells))

    return places, applicants
