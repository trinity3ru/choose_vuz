"""
Преобразование HTML-списка Горного университета (priem2026.spmi.ru) в модели.

Сайт публикует укрупнённые конкурсные группы (напр. «Информационные технологии»,
«Электроэнергетика и теплоэнергетика»). Отдельных страниц по кодам 09.03.01 /
09.03.02 на сайте нет — несколько кодов из config.json могут ссылаться на один
specialization_id (external_id).

Берём только строки с участием в «Общий конкурс» (колонка с иконкой «+»).
applicant_type_id=2 на сайте соответствует фильтру «общий конкурс».
"""

import re

from bs4 import BeautifulSoup, Tag

from app.schemas.parser_schema import ApplicantRow

# Фиксированные параметры бакалавриата на priem2026.spmi.ru.
DIRECTION_ID = "7"
APPLICANT_TYPE_GENERAL = "2"

# Число ячеек в строке таблицы (включая скрытые на мобильных).
_DATA_COLS = 13

# Индексы колонок в строке table-list.
_COL_RANK = 0
_COL_CODE = 1
_COL_TOTAL = 2
_COL_EXAM = 3
_COL_ACHIEVEMENT = 4
_COL_PRIORITY = 5
_COL_GENERAL = 6
_COL_AGREEMENT = 10
_COL_STATUS = 11

# Места в шапке страницы.
_TOTAL_PLACES_RE = re.compile(
    r"мест\s*\(квота\)\s*за\s*счет\s*бюджета\s*Университета\s*ВСЕГО\s*[–-]\s*"
    r'<span[^>]*>\s*(\d+)',
    re.IGNORECASE,
)
_SPECIAL_QUOTA_RE = re.compile(r"особая\s+квота\s*-\s*<span[^>]*>\s*(\d+)", re.IGNORECASE)
_SEPARATE_QUOTA_RE = re.compile(r"отдельная\s+квота\s*-\s*<span[^>]*>\s*(\d+)", re.IGNORECASE)
_TARGET_QUOTA_RE = re.compile(r"целевая\s+квота\s*-\s*<span[^>]*>\s*(\d+)", re.IGNORECASE)


def to_int(value: object) -> int | None:
    """Привести текст ячейки к целому (пустое -> None)."""
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    cleaned = re.sub(r"[^\d-]", "", text)
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


def build_list_url(specialization_id: str) -> str:
    """Собрать URL страницы списка для укрупнённой программы."""
    return (
        "https://priem2026.spmi.ru/list"
        f"?direction_id={DIRECTION_ID}"
        f"&specialization_id={specialization_id}"
        f"&applicant_type_id={APPLICANT_TYPE_GENERAL}"
        "&applicant_consent_id=0"
    )


def parse_places(html: str) -> int | None:
    """
    Посчитать места общего конкурса: всего бюджет - особая - отдельная - целевая.
    """
    total_match = _TOTAL_PLACES_RE.search(html)
    if not total_match:
        return None

    total = to_int(total_match.group(1))
    if total is None:
        return None

    special = to_int((_SPECIAL_QUOTA_RE.search(html) or [None, "0"])[1]) or 0
    separate = to_int((_SEPARATE_QUOTA_RE.search(html) or [None, "0"])[1]) or 0
    target = to_int((_TARGET_QUOTA_RE.search(html) or [None, "0"])[1]) or 0
    return max(total - special - separate - target, 0)


def _has_plus_icon(cell: Tag) -> bool:
    """На сайте участие в категории отмечено иконкой fa-plus в ячейке."""
    return cell.find("i", class_=lambda c: c and "fa-plus" in c) is not None


def row_to_applicant(cells: list[Tag]) -> ApplicantRow | None:
    """Собрать ApplicantRow из ячеек строки. None — если не общий конкурс."""
    if len(cells) != _DATA_COLS:
        return None

    if not _has_plus_icon(cells[_COL_GENERAL]):
        return None

    rank_text = cells[_COL_RANK].get_text(strip=True)
    if not rank_text.isdigit():
        return None

    status = cells[_COL_STATUS].get_text(" ", strip=True)
    return ApplicantRow(
        applicant_code=cells[_COL_CODE].get_text(strip=True),
        is_bvi="бви" in status.lower(),
        total_score=to_int(cells[_COL_TOTAL].get_text(strip=True)),
        exam_score=to_int(cells[_COL_EXAM].get_text(strip=True)),
        achievement_score=to_int(cells[_COL_ACHIEVEMENT].get_text(strip=True)),
        target_achievement_score=None,
        preferential_right=None,
        priority=to_int(cells[_COL_PRIORITY].get_text(strip=True)),
        has_agreement=_has_plus_icon(cells[_COL_AGREEMENT]),
        review_status=status or None,
    )


def parse_list_html(html: str) -> tuple[int | None, list[ApplicantRow]]:
    """
    Разобрать HTML страницы /list.

    Возвращает (места общего конкурса, абитуриенты общего конкурса).
    """
    places = parse_places(html)
    soup = BeautifulSoup(html, "html.parser")
    applicants: list[ApplicantRow] = []

    for tr in soup.select("table.table-list tbody tr"):
        tds = tr.find_all("td")
        row = row_to_applicant(tds)
        if row is not None:
            applicants.append(row)

    return places, applicants
