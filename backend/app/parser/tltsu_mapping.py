"""
Преобразование BIRT-отчёта ТГУ (edu.tltsu.ru) в чистые модели.

Отчёт `preview` отдаёт готовый HTML, где один документ содержит несколько
направлений/программ. Здесь мы обходим отчёт по порядку, отслеживая текущее
направление и категорию, и собираем строки только категории
«Основные места … (бюджет)» (общий бюджетный конкурс).

Раздельные баллы по предметам не храним. Число колонок-предметов в строке
меняется, поэтому берём устойчивые крайние колонки: слева 8, справа 3.
"""

import re

from bs4 import BeautifulSoup

from app.schemas.parser_schema import ApplicantRow

# Заголовок направления: div.style_7, текст начинается с кода XX.XX.XX.
_NAPR_RE = re.compile(r"^\s*(\d{2}\.\d{2}\.\d{2})\s+\D")
# Число мест в заголовке категории: "... - 16 мест."
_PLACES_RE = re.compile(r"-\s*(\d+)\s*мест")


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


def row_to_applicant(cells: list[str], is_bvi: bool) -> ApplicantRow:
    """
    Собрать ApplicantRow из ячеек строки таблицы.

    Устойчивые индексы:
    - слева:  [1] код ЕПГУ, [2] приоритет, [3] инфо о рассмотрении,
              [4] доп.информация, [5] согласие;
    - справа: [-3] сумма ВИ, [-2] баллы за ИД, [-1] сумма конкурсных баллов.
    """
    extra = cells[4].strip()
    return ApplicantRow(
        applicant_code=cells[1].strip(),
        is_bvi=is_bvi,
        total_score=to_int(cells[-1]),
        exam_score=to_int(cells[-3]),
        achievement_score=to_int(cells[-2]),
        target_achievement_score=None,
        # Преимущественное право отмечается в колонке «Дополнительная информация».
        preferential_right="Да" if "преимущ" in extra.lower() else None,
        priority=to_int(cells[2]),
        # Согласие в ТГУ подаётся электронно: значение «Электронное» = согласие есть,
        # «Отозвано»/пусто = согласия нет.
        has_agreement=cells[5].strip().lower() == "электронное",
        review_status=cells[3].strip() or None,
    )


def _is_budget_category(text: str) -> bool:
    """Категория «Основные места в рамках КЦП (бюджет)» — общий конкурс."""
    low = text.lower()
    return "основные места в рамках" in low and "бюджет" in low


def parse_report(html: str) -> dict[str, dict]:
    """
    Разобрать весь отчёт и сгруппировать данные по коду направления.

    Возвращает {код: {"places": int|None, "applicants": [ApplicantRow]}} —
    только строки категории «Основные места … (бюджет)». Если у кода несколько
    программ, места суммируются, а абитуриенты объединяются.
    """
    soup = BeautifulSoup(html, "html.parser")

    result: dict[str, dict] = {}
    current_code: str | None = None
    in_budget = False
    is_bvi = False

    for el in soup.find_all(["div", "tr"]):
        if el.name == "tr":
            # Строка данных: ячейки td.style_17, первая — место в рейтинге (число).
            tds = el.find_all("td", recursive=False)
            if len(tds) < 11:
                continue
            cells = [td.get_text(" ", strip=True) for td in tds]
            if not cells[0].strip().isdigit():
                continue
            if current_code and in_budget and current_code in result:
                result[current_code]["applicants"].append(
                    row_to_applicant(cells, is_bvi)
                )
            continue

        # div: заголовок направления, категория или подсекция.
        classes = el.get("class", [])
        if "style_7" in classes:
            text = el.get_text(" ", strip=True)
            napr = _NAPR_RE.match(text)
            if napr:
                # Новый заголовок направления — сбрасываем категорию.
                current_code = napr.group(1)
                in_budget = False
                result.setdefault(current_code, {"places": None, "applicants": []})
            elif _is_budget_category(text):
                in_budget = True
                places_match = _PLACES_RE.search(text)
                if places_match and current_code:
                    add = int(places_match.group(1))
                    prev = result[current_code]["places"] or 0
                    result[current_code]["places"] = prev + add
            elif "мест" in text.lower() or "квота" in text.lower() or "договор" in text.lower():
                # Другая категория (квоты, договор) — строки не берём.
                in_budget = False
        elif "style_15" in classes:
            # Подсекция: «без вступительных испытаний» => БВИ.
            is_bvi = "без вступительн" in el.get_text(" ", strip=True).lower()

    return result
