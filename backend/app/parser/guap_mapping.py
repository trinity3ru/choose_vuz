"""
Преобразование HTML-списков ГУАП (priem.guap.ru) в чистые модели.

Сводная страница list_1_1_1_1 содержит таблицу #tablestat: код направления и ссылки
на бюджетный общий конкурс в колонке «Основные места (федеральный бюджет)».

Страница программы — таблица .pk-ratings-table (11 колонок):
0 п/п | 1 Уникальный код | 2 Приоритет | 3 Сумма конкурсных | 4 Сумма ВИ |
5 Баллы за достижения | 6 Баллы за ВИ (текст) | 7 Согласие | 8 Без ВИ |
9 ПП ч.9 | 10 ПП ч.10
"""

import re

from bs4 import BeautifulSoup

from app.schemas.parser_schema import ApplicantRow

# Число колонок в строке данных таблицы рейтинга.
_DATA_COLS = 11

# Места общего конкурса: «Количество мест за вычетом квот - 11».
_PLACES_RE = re.compile(
    r"мест\s+за\s+вычетом\s+квот\s*[-–—]?\s*(\d+)",
    re.IGNORECASE,
)

# Дата формирования списка: «Дата актуализации - 10.07.2026 21:37».
_DATE_RE = re.compile(
    r"дата\s+актуализации\s*[-–—]?\s*(?:</b>)?\s*([\d.]+\s+[\d:]+)",
    re.IGNORECASE,
)


def to_int(value: object) -> int | None:
    """Привести значение ячейки к целому (пустое/прочерк -> None)."""
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    try:
        return int(text)
    except (ValueError, TypeError):
        return None


def _is_yes(value: str) -> bool:
    """Значение колонки-флага «Да»/«Нет»."""
    return value.strip().lower() == "да"


def row_to_applicant(cells: list[str]) -> ApplicantRow:
    """Собрать ApplicantRow из 11 ячеек строки таблицы ГУАП."""
    pref9, pref10 = cells[9].strip(), cells[10].strip()
    preferential = "Да" if (_is_yes(pref9) or _is_yes(pref10)) else None

    return ApplicantRow(
        applicant_code=cells[1].strip(),
        is_bvi=_is_yes(cells[8]),
        total_score=to_int(cells[3]),
        exam_score=to_int(cells[4]),
        achievement_score=to_int(cells[5]),
        target_achievement_score=None,
        preferential_right=preferential,
        priority=to_int(cells[2]),
        has_agreement=_is_yes(cells[7]),
        review_status=None,
    )


def parse_index(html: str) -> dict[str, list[str]]:
    """
    Разобрать сводную таблицу направлений.

    Возвращает словарь {код направления -> [относительные пути к спискам бюджета]}.
    Под одним кодом может быть несколько образовательных программ.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="tablestat")
    if table is None:
        raise RuntimeError("не найдена таблица #tablestat на сводной странице")

    thead = table.find("thead")
    if thead is None:
        raise RuntimeError("у таблицы #tablestat нет заголовка")

    headers = [th.get_text(" ", strip=True) for th in thead.find_all("th")]
    budget_col: int | None = None
    for idx, header in enumerate(headers):
        lower = header.lower()
        if "основ" in lower and "бюджет" in lower:
            budget_col = idx
            break
    if budget_col is None:
        raise RuntimeError("не найдена колонка «Основные места (федеральный бюджет)»")

    code_map: dict[str, list[str]] = {}
    tbody = table.find("tbody")
    if tbody is None:
        return code_map

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) <= budget_col:
            continue
        code = tds[0].get_text(strip=True)
        if not code:
            continue
        link = tds[budget_col].find("a")
        if link is None:
            continue
        href = str(link.get("href", "")).replace("\\", "/").strip()
        if not href:
            continue
        code_map.setdefault(code, []).append(href)

    return code_map


def _normalize_html(html: str) -> str:
    """Подготовить HTML для поиска по регуляркам (nbsp и лишние теги)."""
    return html.replace("&nbsp;", " ")


def parse_list_page(html: str) -> tuple[int | None, str | None, list[ApplicantRow]]:
    """
    Разобрать HTML страницы одной образовательной программы.

    Возвращает (места общего конкурса, дата актуализации, список абитуриентов).
    """
    normalized = _normalize_html(html)
    places_match = _PLACES_RE.search(normalized)
    places = to_int(places_match.group(1)) if places_match else None

    date_match = _DATE_RE.search(normalized)
    list_formed_at = date_match.group(1).strip() if date_match else None

    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.pk-ratings-table")
    if table is None:
        table = soup.find("table", id=re.compile(r"^tablestat\d+$"))

    applicants: list[ApplicantRow] = []
    if table is None:
        return places, list_formed_at, applicants

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != _DATA_COLS:
            continue
        cells = [td.get_text(" ", strip=True) for td in tds]
        if not cells[0].strip().isdigit():
            continue
        if not cells[1].strip():
            continue
        applicants.append(row_to_applicant(cells))

    return places, list_formed_at, applicants
