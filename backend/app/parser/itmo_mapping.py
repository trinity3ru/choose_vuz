"""
Преобразование данных сайта ИТМО (abit.itmo.ru) в чистые модели.

Сайт ИТМО — приложение на Next.js. Данные конкурсного списка встроены
в HTML-страницу внутри тега <script id="__NEXT_DATA__"> в виде JSON
(server-side rendering). Поэтому браузер и JS не нужны: достаточно обычного
GET-запроса и разбора этого JSON.

Структура нужных данных:
props.pageProps.programList = {
    "without_entry_tests":  [...],  # БВИ
    "by_unusual_quota":     [...],  # отдельная квота
    "by_special_quota":     [...],  # особая квота
    "by_target_quota":      [...],  # целевая квота
    "general_competition":  [...],  # общий конкурс  <-- берём только это
    "direction":            {...},  # метаданные (мест, квоты, название)
    "update_time":          "..."   # когда список сформирован
}

По решению (как и для других вузов проекта) парсим ТОЛЬКО общий конкурс.
Раздельные баллы по предметам (disciplines_scores) не храним.
"""

import json
import re

from app.schemas.parser_schema import ApplicantRow

# Регулярка вытаскивает JSON из тега <script id="__NEXT_DATA__">.
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.S,
)


def extract_program_list(html: str) -> dict:
    """
    Достать programList (данные конкурсного списка) из HTML-страницы ИТМО.

    :raises RuntimeError: если тег __NEXT_DATA__ не найден или структура иная.
    """
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise RuntimeError("на странице не найден __NEXT_DATA__ (изменилась вёрстка?)")

    try:
        data = json.loads(match.group(1))
        return data["props"]["pageProps"]["programList"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise RuntimeError(f"не удалось разобрать данные страницы: {exc}") from exc


def _positive_int(value: object) -> int | None:
    """
    Вернуть целое, если оно больше нуля, иначе None.

    У ИТМО ноль баллов означает «баллы не введены» (заявление без ЕГЭ),
    а не реальный результат. Поэтому 0 приводим к None, чтобы такие
    заявления не искажали средний балл при анализе.
    """
    if isinstance(value, int) and value > 0:
        return value
    return None


def row_to_applicant(entry: dict) -> ApplicantRow:
    """Преобразовать одну запись общего конкурса ИТМО в ApplicantRow."""
    return ApplicantRow(
        # sspvo_id — уникальный код заявления (номер с портала ГосУслуг).
        applicant_code=str(entry.get("sspvo_id", "")).strip(),
        # Общий конкурс — не БВИ (БВИ лежат в отдельной категории).
        is_bvi=False,
        # total_scores = баллы ВИ + индивидуальные достижения.
        total_score=_positive_int(entry.get("total_scores")),
        # exam_scores = сумма баллов за вступительные испытания (ЕГЭ/ВИ).
        exam_score=_positive_int(entry.get("exam_scores")),
        # ia_scores = индивидуальные достижения (ИД). Ноль — это валидное «нет ИД».
        achievement_score=entry.get("ia_scores"),
        target_achievement_score=None,
        preferential_right=None,
        priority=entry.get("priority"),
        # is_send_agreement — подано ли согласие на зачисление.
        has_agreement=bool(entry.get("is_send_agreement")),
        # status — служебный статус строки (recommended / pass_another / None).
        review_status=entry.get("status"),
    )


def compute_general_places(direction: dict) -> int | None:
    """
    Посчитать число мест для общего конкурса ИТМО.

    В direction.budget_min лежит общее число бюджетных мест (КЦП). Из него
    вычитаем места, зарезервированные под квоты (целевая, особая, отдельная),
    чтобы получить места именно общего конкурса — по ним считается проходной.
    """
    budget_min = direction.get("budget_min")
    if not isinstance(budget_min, int):
        return None

    target = direction.get("target_reception") or 0  # целевая квота (ЦК)
    special = direction.get("special_quota") or 0     # особая квота (ОcК)
    separate = direction.get("invalid") or 0          # отдельная квота (ОтК)

    general = budget_min - target - special - separate
    return general if general > 0 else budget_min
