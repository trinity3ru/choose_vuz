"""
Преобразование данных API СамГТУ (Самарский политех) в чистые модели.

Данные приходят из JSON-эндпоинта rating (по CompetetiveGroupID). Ключи
стабильны, поэтому мапим по именам полей. Раздельные баллы по предметам
намеренно не храним — нужна только сумма.

Модуль отвечает только за нормализацию значений и сборку ApplicantRow
(единая ответственность); логика HTTP живёт в samgtu.py.
"""

from app.schemas.parser_schema import ApplicantRow

# Форма обучения из конфига -> StudyFormName в API kcps.
STUDY_FORM_NAMES: dict[str, str] = {
    "Заочная": "Заочная",
    "Очная": "Очная",
    "Очно-заочная": "Очно-Заочная",
}

# Условие поступления -> PlaceTypeID в API.
# 1 = «Основные места в рамках КЦП» (общий бюджетный конкурс). Парсим только его.
PLACE_TYPE_BUDGET = "1"

# Головной вуз (не филиалы) в поле Representation.
MAIN_REPRESENTATION = "СамГТУ"


def to_int(value: object) -> int | None:
    """
    Привести значение к целому. Строки вида '282.00' корректно округляются.

    Пустые/нечисловые значения дают None (например, у строк без баллов).
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    try:
        # Через float, т.к. суммы приходят как '282.00'.
        return int(float(text))
    except (ValueError, TypeError):
        return None


def _achievement_score(raw: dict) -> int | None:
    """
    Баллы за индивидуальные достижения (ИД).

    На сайте столбец ИД считается так: если IndividualAchivment == 0,
    то ИД = SummaAll - SummaResults, иначе = IndividualAchivment
    (повторяем логику шаблона Angular, чтобы цифры совпадали с сайтом).
    """
    ia = to_int(raw.get("IndividualAchivment"))
    if ia:  # не None и не 0
        return ia
    total = to_int(raw.get("SummaAll"))
    exam = to_int(raw.get("SummaResults"))
    if total is None or exam is None:
        return None
    return total - exam


def row_to_applicant(raw: dict) -> ApplicantRow:
    """Преобразовать строку rating в модель ApplicantRow."""
    return ApplicantRow(
        applicant_code=str(raw.get("siteName", "")).strip(),
        # IsNoExam == '1' -> зачисление без вступительных испытаний (БВИ).
        is_bvi=str(raw.get("IsNoExam")) == "1",
        total_score=to_int(raw.get("SummaAll")),
        # Столбец «Сумма баллов по ЕГЭ».
        exam_score=to_int(raw.get("EGE_sum")),
        achievement_score=_achievement_score(raw),
        target_achievement_score=None,
        # Преимущественное право (льгота): Benefit == '1'.
        preferential_right="Да" if str(raw.get("Benefit")) == "1" else None,
        priority=to_int(raw.get("PriorityNumber")),
        # На сайте столбец «Наличие согласия» = OriginalReceived == '1'.
        has_agreement=str(raw.get("OriginalReceived")) == "1",
        review_status=None,
    )
