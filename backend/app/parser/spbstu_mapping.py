"""
Преобразование сырых данных сайта СПбПУ в чистые модели.

Здесь собраны:
- коды фильтров сайта (форма обучения, условия поступления);
- функции нормализации значений (очистка HTML, разбор чисел/флагов);
- маппинг строки таблицы (get-abit-list) в модель ApplicantRow.

Держим это отдельно от логики браузера (парсер spbstu.py), чтобы
каждый модуль отвечал за одно (принцип единой ответственности).
"""

import re

from app.schemas.parser_schema import ApplicantRow, MajorSummary

# Форма обучения -> код filter_1 на сайте СПбПУ.
STUDY_FORM_CODES: dict[str, str] = {
    "Заочная": "1",
    "Очная": "2",
    "Очно-заочная": "3",
}

# Условия поступления -> код filter_2 на сайте СПбПУ.
FINANCE_TYPE_CODES: dict[str, str] = {
    "Бюджетная основа": "1",
    "Контракт": "2",
    "Особое право": "3",
    "Отдельная квота": "4",
    "Целевой прием": "6",
}

# Регулярка для вырезания HTML-тегов из значений ячеек (на всякий случай).
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(value: object) -> str:
    """Убрать HTML-теги и лишние пробелы, вернуть чистую строку."""
    text = _HTML_TAG_RE.sub("", str(value))
    return text.strip()


def to_int(value: object) -> int | None:
    """
    Аккуратно привести значение к целому числу.

    Пустые строки, прочерки и нечисловые значения дают None,
    чтобы не падать на строках без баллов (например, у БВИ).
    """
    text = strip_html(value)
    if not text or text in {"-", "—"}:
        return None
    # Оставляем только цифры и знак минус (на случай мусора вокруг числа).
    cleaned = re.sub(r"[^\d-]", "", text)
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


def _is_bvi(base_value: object) -> bool:
    """
    Определить БВИ по колонке "Основание приема БВИ".

    Значение "Нет" (или пусто/прочерк) означает обычный конкурс.
    Любое другое значение считаем признаком БВИ.
    """
    text = strip_html(base_value).lower()
    return text not in {"", "нет", "-", "—", "none"}


# Значения колонки «Согласие на зачисление», означающие, что согласия нет.
_NO_AGREEMENT_VALUES = {"", "-", "—", "нет", "отсутствует", "не получено", "none"}


def _has_agreement(approval_value: object) -> bool:
    """
    Есть ли согласие на зачисление.

    Сейчас сайт отдаёт "+" при поданном согласии и "Отсутствует", когда его
    нет (раньше в этой колонке встречалось "Получено"). Поэтому отталкиваемся
    от списка «пустых» значений: любое другое непустое значение считаем
    согласием — так формулировка на сайте может меняться без правки парсера.
    """
    return strip_html(approval_value).lower() not in _NO_AGREEMENT_VALUES


def row_to_applicant(raw: dict) -> ApplicantRow:
    """
    Преобразовать сырую строку get-abit-list в модель ApplicantRow.

    Мапим по именам ключей (они стабильны у СПбПУ), а колонки баллов
    по отдельным предметам (math/it/physics и т.п.) намеренно игнорируем —
    они различаются от направления к направлению и нам не нужны.
    """
    return ApplicantRow(
        applicant_code=strip_html(raw.get("code")),
        is_bvi=_is_bvi(raw.get("base")),
        total_score=to_int(raw.get("sum")),
        exam_score=to_int(raw.get("sum_vs")),
        achievement_score=to_int(raw.get("counl_ind")),
        target_achievement_score=to_int(raw.get("count_cel")),
        preferential_right=strip_html(raw.get("privilege")) or None,
        priority=to_int(raw.get("priority")),
        has_agreement=_has_agreement(raw.get("approval")),
        review_status=strip_html(raw.get("info")) or None,
    )


def parse_summary(raw_list: list) -> MajorSummary | None:
    """Преобразовать ответ get-direction-info в модель MajorSummary."""
    if not raw_list:
        return None
    item = raw_list[0]
    return MajorSummary(
        places=to_int(item.get("places")),
        applications=to_int(item.get("applications")),
        agreements=to_int(item.get("count_agreement")),
        list_formed_at=strip_html(item.get("date_info")) or None,
    )
