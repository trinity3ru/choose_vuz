"""
Преобразование HTML-списков КФУ (abiturient.kpfu.ru) в модели парсера.

Страница abit_entrant_originals_list отдаёт server-rendered HTML с несколькими
таблицами по квотам. Берём только секцию «на основные места в рамках контрольных
цифр» — общий бюджетный конкурс (как «Общий конкурс» у Самары).

Число колонок-предметов меняется, поэтому для ApplicantRow используем устойчивые
крайние колонки справа (ИД, сумма, основание, ПП, приоритет, согласие, статус).
"""

import re

from bs4 import BeautifulSoup, Tag

from app.schemas.parser_schema import ApplicantRow

# Заголовок секции общего бюджетного конкурса на странице КФУ.
_MAIN_SECTION_MARK = "на основные места в рамках контрольных цифр"

# План приёма в шапке страницы: «План приема: 71».
_PLACES_RE = re.compile(r"План\s+при[её]ма:\s*(\d+)", re.IGNORECASE)


def to_int(value: object) -> int | None:
    """Привести текст ячейки к int; пустое и прочерк -> None."""
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    cleaned = re.sub(r"[^\d-]", "", text)
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


def decode_html(body: bytes) -> str:
    """Декодировать ответ КФУ (чаще cp1251, иногда utf-8)."""
    for encoding in ("utf-8", "cp1251", "windows-1251"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def pick_speciality_id(options: list[tuple[str, str]], code: str) -> tuple[str, str]:
    """
    Выбрать p_speciality по коду направления из выпадающего списка.

    Предпочитаем программы для граждан РФ (без «иностран» в названии).
    """
    candidates: list[tuple[str, str]] = []
    for value, title in options:
        if not title.startswith(code):
            continue
        if "иностран" in title.lower():
            continue
        candidates.append((value, title))
    if not candidates:
        for value, title in options:
            if title.startswith(code):
                candidates.append((value, title))
    if not candidates:
        raise RuntimeError(f"программа с кодом {code} не найдена в списке института")
    return candidates[0]


def parse_select_options(html: str, name: str) -> list[tuple[str, str]]:
    """Считать option value/text из select по имени поля формы."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", {"name": name})
    if not select:
        return []
    return [
        (opt.get("value", ""), opt.get_text(" ", strip=True))
        for opt in select.find_all("option")
        if opt.get("value")
    ]


def _is_yes(value: str) -> bool:
    return value.strip().lower() == "да"


def _is_bvi(basis: str, status: str, note: str) -> bool:
    haystack = f"{basis} {status} {note}".lower()
    return "бви" in haystack or "олимпиад" in haystack


def row_to_applicant(cells: list[str]) -> ApplicantRow:
    """Собрать ApplicantRow из строки таблицы tablebig (18+ колонок)."""
    basis = cells[-6].strip()
    pref = cells[-5].strip()
    status = cells[-2].strip()
    note = cells[-1].strip()

    return ApplicantRow(
        applicant_code=cells[1].strip(),
        is_bvi=_is_bvi(basis, status, note),
        total_score=to_int(cells[-7]),
        exam_score=None,
        achievement_score=to_int(cells[-8]),
        target_achievement_score=None,
        preferential_right=pref if _is_yes(pref) else (pref if pref not in {"", "нет", "-"} else None),
        priority=to_int(cells[-4]),
        has_agreement=_is_yes(cells[-3]),
        review_status=status or None,
    )


def _find_main_section(soup: BeautifulSoup) -> Tag | None:
    """Найти section с таблицей общего бюджетного конкурса."""
    for section in soup.select("section.listing-abitur__section"):
        header = section.find("h2")
        if not header:
            continue
        if _MAIN_SECTION_MARK in header.get_text(" ", strip=True).lower():
            return section
    return None


def parse_main_competition(html: str) -> tuple[int | None, list[ApplicantRow]]:
    """
    Разобрать HTML страницы списка КФУ.

    :return: (план приёма, абитуриенты общего конкурса)
    """
    soup = BeautifulSoup(html, "html.parser")
    plan_block = soup.select_one(".listing-abitur__plan")
    places = None
    if plan_block:
        plan_match = _PLACES_RE.search(plan_block.get_text(" ", strip=True))
        if plan_match:
            places = to_int(plan_match.group(1))
    if places is None:
        places_match = _PLACES_RE.search(html)
        places = to_int(places_match.group(1)) if places_match else None

    section = _find_main_section(soup)
    if section is None:
        raise RuntimeError("секция «основные места в рамках КЦП» не найдена")

    applicants: list[ApplicantRow] = []
    for tr in section.select("table.tablebig tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < 12 or not cells[1].strip().isdigit():
            continue
        applicants.append(row_to_applicant(cells))

    return places, applicants
