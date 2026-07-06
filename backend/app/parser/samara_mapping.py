"""
Преобразование данных сайта Самарского университета (priemsamara.ru).

Страница рейтинга — обычный server-rendered HTML с таблицей. Колонки:
№ | Код поступающего | Сумма баллов | [предметы...] | Баллы за ИД |
Согласие | Приоритет | Состояние | Рассматривается к зачислению |
Преимущ. право / Основание БВИ

Число колонок-предметов различается от направления к направлению,
поэтому мы НЕ привязываемся к абсолютным индексам предметов, а берём
устойчивые крайние колонки: первые 3 слева и последние 6 справа.

Этот модуль отвечает только за нормализацию значений и сборку ApplicantRow
(единая ответственность), а логика HTTP/HTML живёт в samara.py.
"""

import re

from app.schemas.parser_schema import ApplicantRow

# Условие оплаты -> код параметра pay в URL priemsamara.ru.
# Парсим только бюджет, но карта оставлена расширяемой.
PAY_CODES: dict[str, str] = {
    "Бюджетная основа": "budget",
    "Контракт": "paid",
}


def to_int(value: object) -> int | None:
    """
    Аккуратно привести значение ячейки к целому числу.

    Пустые строки, прочерки и нечисловые значения дают None,
    чтобы не падать на строках без баллов (например, у БВИ).
    """
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    # Оставляем только цифры и минус (на случай мусора вокруг числа).
    cleaned = re.sub(r"[^\d-]", "", text)
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


def _has_agreement(value: str) -> bool:
    """Есть ли согласие на зачисление. В колонке 'Согласие' стоит Да/Нет."""
    return value.strip().lower() == "да"


def _is_bvi(pref_value: str, status_value: str) -> bool:
    """
    Определить БВИ по колонкам 'Преимущ. право / Основание БВИ' и 'Состояние'.

    Если где-то встречается упоминание БВИ — считаем поступающего БВИ.
    """
    haystack = f"{pref_value} {status_value}".lower()
    return "бви" in haystack


def row_to_applicant(cells: list[str]) -> ApplicantRow:
    """
    Собрать ApplicantRow из списка текстов ячеек одной строки таблицы.

    Индексация:
    - слева:  cells[1] — код поступающего, cells[2] — сумма баллов;
    - справа: cells[-6] — баллы за ИД, cells[-5] — согласие,
              cells[-4] — приоритет, cells[-3] — состояние,
              cells[-2] — рассматривается к зачислению (не используем),
              cells[-1] — преимущ. право / основание БВИ.
    Такой подход не зависит от числа колонок-предметов посередине.
    """
    pref_text = cells[-1].strip()
    status_text = cells[-3].strip()

    return ApplicantRow(
        applicant_code=cells[1].strip(),
        is_bvi=_is_bvi(pref_text, status_text),
        total_score=to_int(cells[2]),
        # Отдельной суммы ВИ (без ИД) на странице нет — оставляем None.
        exam_score=None,
        achievement_score=to_int(cells[-6]),
        target_achievement_score=None,
        preferential_right=pref_text if pref_text not in {"", "-", "—"} else None,
        priority=to_int(cells[-4]),
        has_agreement=_has_agreement(cells[-5]),
        review_status=status_text or None,
    )


# Регулярка для сводки: после текста 'Общий конкурс' идёт блок 'заявлений / мест'.
# Пример разметки: <div class="text"> Общий конкурс </div>
#                  <div class="numb"> 208 / 29 </div>
_PLACES_RE = re.compile(
    r"Общий конкурс.*?<div class=\"numb\">\s*(\d+)\s*/\s*(\d+)",
    re.DOTALL,
)


def parse_places(html: str) -> int | None:
    """
    Достать число бюджетных мест общего конкурса из шапки страницы.

    Возвращает None, если разметка изменилась (сводка не критична).
    """
    match = _PLACES_RE.search(html)
    if not match:
        return None
    return to_int(match.group(2))
