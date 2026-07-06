"""
Преобразование данных сайта СПбГУТ (priem.sut.ru) в чистые модели.

Здесь:
- коды полей формы сайта (форма обучения, основа поступления);
- разбор одной строки HTML-таблицы результатов в модель ApplicantRow.

СПбГУТ отдаёт результаты как HTML (в отличие от СПбПУ с его JSON),
поэтому строку мы получаем уже как список текстов ячеек <td>.
"""

import re

from app.schemas.parser_schema import ApplicantRow

# Уровень образования: бакалавриат (education_base_to).
EDUCATION_LEVEL_BACHELOR = "11"

# Форма обучения -> код training_form на сайте СПбГУТ.
STUDY_FORM_CODES: dict[str, str] = {
    "Очно-заочная": "1",
    "Заочная": "2",
    "Очная": "4",
}

# Условия поступления (config) -> код training_type на сайте СПбГУТ.
# На сайте: 1 Бюджетные места, 2 Платные, 3 Особая квота, 4 Отдельная квота,
# 5 Целевая детализированная, 6 Целевая недетализированная.
FINANCE_TYPE_CODES: dict[str, str] = {
    "Бюджетная основа": "1",
    "Контракт": "2",
    "Особое право": "3",
    "Отдельная квота": "4",
    "Целевой прием": "5",
}

# Индексы колонок в строке таблицы результатов (0-based по ячейкам <td>):
# 0 №, 1 Уник.ид (ЕПГУ), 2 ид в вузе, 3 Приоритет, 4 БВИ, 5 Общие ИД,
# 6 Целевые ИД, 7 Сумма баллов, 8 Статус в КГ, 9 договор (платное), 10 Дата согласия.
COL_CODE = 1
COL_PRIORITY = 3
COL_BVI = 4
COL_ACHIEVEMENT = 5
COL_TARGET_ACHIEVEMENT = 6
COL_TOTAL = 7
COL_STATUS = 8
COL_AGREEMENT_DATE = 10
# Минимальное число колонок валидной строки данных.
MIN_COLUMNS = 11


def to_int(value: str) -> int | None:
    """Привести текст ячейки к целому числу; пусто/мусор -> None."""
    text = (value or "").strip()
    if not text or text in {"-", "—"}:
        return None
    cleaned = re.sub(r"[^\d-]", "", text)
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


def _is_bvi(value: str) -> bool:
    """БВИ по колонке 'БВИ': значение 'да' -> True, 'нет'/пусто -> False."""
    return (value or "").strip().lower() in {"да", "yes"}


def row_to_applicant(cells: list[str]) -> ApplicantRow | None:
    """
    Преобразовать список текстов ячеек строки таблицы в ApplicantRow.

    Возвращает None, если ячеек меньше ожидаемого (служебная/битая строка).
    Полей 'сумма за ВИ' и 'преимущественное право' на сайте СПбГУТ нет — оставляем None.
    """
    if len(cells) < MIN_COLUMNS:
        return None

    return ApplicantRow(
        applicant_code=cells[COL_CODE].strip(),
        is_bvi=_is_bvi(cells[COL_BVI]),
        total_score=to_int(cells[COL_TOTAL]),
        exam_score=None,
        achievement_score=to_int(cells[COL_ACHIEVEMENT]),
        target_achievement_score=to_int(cells[COL_TARGET_ACHIEVEMENT]),
        preferential_right=None,
        priority=to_int(cells[COL_PRIORITY]),
        # Согласие на зачисление: заполнена дата подачи согласия.
        has_agreement=bool(cells[COL_AGREEMENT_DATE].strip()),
        review_status=cells[COL_STATUS].strip() or None,
    )
