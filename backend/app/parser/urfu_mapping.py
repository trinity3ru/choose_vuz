"""
Разбор HTML-файлов рейтингов УрФУ и нормализация строк абитуриентов.

Источник (см. urfu.py): один HTML-файл на институт содержит десятки списков.
Каждый список — пара таблиц: META (2 колонки, ключ→значение) и DATA (10 колонок).
Здесь живёт разбор HTML и сборка ApplicantRow (единая ответственность);
HTTP и кэширование по институтам — в urfu.py.

Парсим только основной бюджетный конкурс очной формы
(META «Вид конкурса» == «Основные места в рамках КЦП», «Форма обучения» == «Очная»).
Каждый такой список адресуется строкой «Направление (образовательная программа)»,
которая в пределах института уникальна.
"""

import re

from app.schemas.parser_schema import ApplicantRow

# Вид конкурса основного бюджетного набора (как у СамГТУ/ТГУ).
COMPETITION_KIND_MAIN = "Основные места в рамках КЦП"

# Форма обучения из конфига -> значение поля «Форма обучения» в META.
STUDY_FORM_NAMES: dict[str, str] = {
    "Заочная": "Заочная",
    "Очная": "Очная",
    "Очно-заочная": "Очно-заочная",
}

# Признак DATA-таблицы: заголовок с колонкой кода поступающего.
_DATA_HEADER_MARK = "Код поступающего (УКП)"
# Признак строки без вступительных испытаний (БВИ).
_NO_EXAM_MARK = "Без проведения"

# Ключи META-таблицы.
_META_KIND = "Вид конкурса"
_META_DIRECTION = "Направление (образовательная программа)"
_META_STUDY_FORM = "Форма обучения"
_META_PLAN = "План приема"

# Индексы колонок DATA-таблицы (порядок стабилен во всех файлах).
_C_CODE = 1          # Код поступающего (УКП)
_C_AGREEMENT = 2     # Согласие на зачисление
_C_PRIORITY = 3      # Приоритет
_C_EXAMS = 4         # Вступительные испытания по предметам
_C_BVI = 5           # Основание приема БВИ
_C_ACHIEVE = 6       # Общие инд. достижения
_C_TARGET_ACHIEVE = 7  # Целевые инд. достижения
_C_TOTAL = 8         # Сумма конкурсных баллов
_C_PREFERENCE = 9    # Преимущественное право

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TABLE_RE = re.compile(r"<table.*?</table>", re.S | re.I)
_INT_RE = re.compile(r"\d+")

# Ленивая замена HTML-сущностей без импорта html на каждый вызов.
import html as _html  # noqa: E402


def _clean(raw: str) -> str:
    """Убрать теги, развернуть сущности, схлопнуть пробелы."""
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub(" ", raw))).strip()


def _cells(row_html: str) -> list[str]:
    return [_clean(c) for c in _CELL_RE.findall(row_html)]


def normalize_direction(text: str) -> str:
    """Нормализовать строку направления для сопоставления (схлопнуть пробелы)."""
    return _WS_RE.sub(" ", text).strip()


def to_int(value: str | None) -> int | None:
    """Первое целое из строки или None (пусто/прочерк/БВИ)."""
    if not value:
        return None
    m = _INT_RE.search(value)
    return int(m.group()) if m else None


def sum_exam_scores(exams_text: str) -> int | None:
    """
    Сумма баллов по предметам из колонки вступительных испытаний.

    Пример: «Математика 99 (ЕГЭ) Физика 100 (ЕГЭ) Русский язык 91 (ЕГЭ)» -> 290.
    У БВИ-строк («Без проведения вступительных испытаний») чисел нет -> None.
    """
    nums = _INT_RE.findall(exams_text or "")
    return sum(int(n) for n in nums) if nums else None


def row_to_applicant(cells: list[str]) -> ApplicantRow | None:
    """Преобразовать строку DATA-таблицы в ApplicantRow (None — если не строка данных)."""
    if len(cells) < 10 or not cells[0].isdigit():
        return None
    exams = cells[_C_EXAMS]
    is_bvi = bool(cells[_C_BVI].strip()) or _NO_EXAM_MARK in exams
    agreement = cells[_C_AGREEMENT].strip().lower().startswith("да")
    preference = cells[_C_PREFERENCE].strip() or None
    return ApplicantRow(
        applicant_code=cells[_C_CODE].strip(),
        is_bvi=is_bvi,
        total_score=to_int(cells[_C_TOTAL]),
        exam_score=sum_exam_scores(exams),
        achievement_score=to_int(cells[_C_ACHIEVE]),
        target_achievement_score=to_int(cells[_C_TARGET_ACHIEVE]),
        preferential_right=preference,
        priority=to_int(cells[_C_PRIORITY]),
        has_agreement=agreement,
        review_status=None,
    )


def _parse_meta(table_html: str) -> dict[str, str]:
    """META-таблица: пары ключ :: значение."""
    meta: dict[str, str] = {}
    for tr in _TR_RE.findall(table_html):
        c = _cells(tr)
        if len(c) == 2 and c[0]:
            meta[c[0]] = c[1]
    return meta


# Разобранный список: план приёма (мест) и строки абитуриентов.
ParsedList = tuple[int | None, list[ApplicantRow]]


def parse_institute_lists(html_text: str, study_form: str = "Очная") -> dict[str, ParsedList]:
    """
    Разобрать HTML института в словарь {нормализованное направление: (места, строки)}.

    Берём только основной бюджетный конкурс (COMPETITION_KIND_MAIN) заданной
    формы обучения. Направление в пределах института уникально, поэтому служит ключом.
    """
    lists: dict[str, ParsedList] = {}
    current_meta: dict[str, str] | None = None

    for table_html in _TABLE_RE.findall(html_text):
        rows = _TR_RE.findall(table_html)
        if not rows:
            continue
        header = _cells(rows[0])
        if header and _DATA_HEADER_MARK in " ".join(header):
            # DATA-таблица: относится к последней встреченной META.
            if not current_meta:
                continue
            if (
                current_meta.get(_META_KIND) != COMPETITION_KIND_MAIN
                or current_meta.get(_META_STUDY_FORM) != study_form
            ):
                continue
            direction = normalize_direction(current_meta.get(_META_DIRECTION, ""))
            if not direction:
                continue
            applicants = [a for a in (row_to_applicant(_cells(tr)) for tr in rows[1:]) if a]
            places = to_int(current_meta.get(_META_PLAN))
            lists[direction] = (places, applicants)
        else:
            meta = _parse_meta(table_html)
            if _META_DIRECTION in meta:
                current_meta = meta

    return lists
