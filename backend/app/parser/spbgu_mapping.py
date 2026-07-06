"""
Преобразование данных API СПбГУ (enrollelists.spbu.ru) в чистые модели.

Эндпоинт data возвращает готовый HTML таблицы (в поле blocks[].html), поэтому
здесь и разбор HTML (BeautifulSoup), и нормализация значений, и сборка
ApplicantRow. Раздельные баллы по предметам (ВИ №1..№3) не храним.

Колонки таблицы (13 ячеек td в строке):
0 № | 1 Уникальный код | 2 Сумма конкурсных баллов | 3 Сумма баллов за ВИ |
4 ВИ №1 | 5 ВИ №2 | 6 ВИ №3 | 7 Сумма баллов за ИД |
8 Преимущ. право ч.9 | 9 Преимущ. право ч.10 | 10 Согласие на зачисление |
11 Приоритет зачисления | 12 Статус
"""

from bs4 import BeautifulSoup

from app.schemas.parser_schema import ApplicantRow

# Число колонок данных в строке таблицы (для отсева служебных строк).
_DATA_COLS = 13


def to_int(value: object) -> int | None:
    """Привести значение ячейки к целому (пустое/нечисловое -> None)."""
    text = str(value).strip()
    if not text or text in {"-", "—", "***"}:
        return None
    try:
        return int(float(text.replace(" ", "")))
    except (ValueError, TypeError):
        return None


def _is_yes(value: str) -> bool:
    """Значение колонки-флага 'Да'/'Нет'."""
    return value.strip().lower() == "да"


def row_to_applicant(cells: list[str]) -> ApplicantRow:
    """Собрать ApplicantRow из списка текстов 13 ячеек строки таблицы."""
    konkurs = cells[2].strip()
    # У БВИ в колонке «Сумма конкурсных баллов» стоит текст 'БВИ (...)'.
    is_bvi = "бви" in konkurs.lower()

    # Преимущественное право: колонки ч.9 и ч.10 (Да/Нет).
    pref9, pref10 = cells[8].strip(), cells[9].strip()
    preferential = "Да" if (_is_yes(pref9) or _is_yes(pref10)) else None

    return ApplicantRow(
        applicant_code=cells[1].strip(),
        is_bvi=is_bvi,
        total_score=to_int(cells[2]),
        exam_score=to_int(cells[3]),
        achievement_score=to_int(cells[7]),
        target_achievement_score=None,
        preferential_right=preferential,
        priority=to_int(cells[11]),
        has_agreement=_is_yes(cells[10]),
        review_status=cells[12].strip() or None,
    )


def parse_block(html: str) -> tuple[int | None, list[ApplicantRow]]:
    """
    Разобрать один блок (одна образовательная программа).

    Возвращает (кол-во бюджетных мест из шапки, список абитуриентов).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Число бюджетных мест — в шапке блока (th 'Количество бюджетных мест:' + td).
    places = None
    for th in soup.find_all("th"):
        if "количество бюджетных мест" in th.get_text(strip=True).lower():
            tr = th.find_parent("tr")
            td = tr.find("td") if tr else None
            places = to_int(td.get_text(strip=True)) if td else None
            break

    # Строки абитуриентов: ровно 13 ячеек td, первая — порядковый номер.
    applicants: list[ApplicantRow] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != _DATA_COLS:
            continue
        cells = [td.get_text(" ", strip=True) for td in tds]
        if not cells[0].strip().isdigit():
            continue
        applicants.append(row_to_applicant(cells))

    return places, applicants
