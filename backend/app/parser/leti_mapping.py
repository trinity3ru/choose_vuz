"""
Преобразование HTML-списка ЛЭТИ (lists.priem.etu.ru) в чистые модели.

Эндпоинт list.html возвращает готовую таблицу. Берём только строки с условием
зачисления «Основные места» (общий бюджетный конкурс). Раздельные баллы
по предметам (колонки 6–8) не храним.
"""

import re

from bs4 import BeautifulSoup

from app.schemas.parser_schema import ApplicantRow

# Условие зачисления для общего бюджетного конкурса.
MAIN_CONDITION = "Основные места"

# Число колонок в строке данных.
_DATA_COLS = 14

# Число бюджетных мест в шапке: «Бюджетных мест: 72».
_PLACES_RE = re.compile(r"Бюджетных\s+мест:\s*(\d+)", re.IGNORECASE)


def to_int(value: object) -> int | None:
    """Привести значение ячейки к целому (пустое/прочерк -> None)."""
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    cleaned = re.sub(r"[^\d-]", "", text)
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


def parse_places(html: str) -> int | None:
    """Достать число бюджетных мест из шапки HTML."""
    match = _PLACES_RE.search(html)
    return to_int(match.group(1)) if match else None


def row_to_applicant(cells: list[str]) -> ApplicantRow:
    """Собрать ApplicantRow из 14 ячеек строки таблицы."""
    condition = cells[3].strip()
    return ApplicantRow(
        applicant_code=cells[1].strip(),
        is_bvi="бви" in condition.lower(),
        total_score=to_int(cells[4]),
        # «∑ балл» — сумма баллов за вступительные испытания.
        exam_score=to_int(cells[5]),
        achievement_score=to_int(cells[9]),
        target_achievement_score=to_int(cells[10]) or None,
        preferential_right="Да" if cells[11].strip().lower() == "да" else None,
        priority=to_int(cells[2]),
        # На сайте ЛЭТИ согласие подаётся электронно.
        has_agreement=cells[12].strip().lower() == "электронное",
        review_status=cells[13].strip() or None,
    )


def parse_list_html(html: str) -> tuple[int | None, list[ApplicantRow]]:
    """
    Разобрать HTML ответ list.html.

    Возвращает (места, список абитуриентов категории «Основные места»).
    """
    places = parse_places(html)
    soup = BeautifulSoup(html, "html.parser")
    applicants: list[ApplicantRow] = []

    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if len(tds) != _DATA_COLS:
            continue
        cells = [td.get_text(" ", strip=True) for td in tds]
        if not cells[0].strip().isdigit():
            continue
        if cells[3].strip() != MAIN_CONDITION:
            continue
        applicants.append(row_to_applicant(cells))

    return places, applicants
