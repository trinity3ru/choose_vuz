"""
Преобразование данных API ВШЭ (pk.hse.ru) в чистые модели.

Списки отдаёт JSON-API Angular-приложения /admissions/api (Spring, snake_case
в части параметров и camelCase в ответах; в именах эндпоинтов есть авторская
опечатка «competitve»):

- GET /competitve-group/{groupId} — заголовок конкурсной группы:
  educationProgram, filial (город!), placeType (Б=бюджет), placeCount (места),
  updatedAt (когда список сформирован);
- GET /applicant?level=BAK&placeType={placeTypeId}&setOfCompetitiveGroupId=
  {setId}&page=N&size=M — страницы списка (Spring Page: content/totalPages).

Поля строки: idEpgu (код), sumCompetitiveScore (сумма конкурсных),
sumEntranceTestScore (сумма ВИ), achievementsSum (ИД), achivementsSumTarget
(целевые ИД, опечатка их API), isWithoutExamsAdmReasonBool (БВИ),
isConcertToEnrollment (согласие, ещё одна опечатка), isHasPrerogativeRight9/10
(преимущественное право), priority, participantStatus.
"""

from app.schemas.parser_schema import ApplicantRow

# Условие поступления из конфига -> ожидаемый placeType.code списка ВШЭ.
# Б = «Бюджетные места», К = «С оплатой обучения» (платное).
PLACE_CODE_BY_FINANCE: dict[str, str] = {
    "Бюджетная основа": "Б",
    "Контракт": "К",
}


def score_to_int(value: object) -> int | None:
    """Балл из API (float/None) -> целое (296.0 -> 296)."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def row_to_applicant(entry: dict) -> ApplicantRow:
    """Преобразовать строку /applicant в ApplicantRow."""
    pref9 = bool(entry.get("isHasPrerogativeRight9"))
    pref10 = bool(entry.get("isHasPrerogativeRight10"))

    return ApplicantRow(
        applicant_code=str(entry.get("idEpgu", "")).strip(),
        is_bvi=bool(entry.get("isWithoutExamsAdmReasonBool")),
        total_score=score_to_int(entry.get("sumCompetitiveScore")),
        exam_score=score_to_int(entry.get("sumEntranceTestScore")),
        achievement_score=score_to_int(entry.get("achievementsSum")),
        target_achievement_score=score_to_int(entry.get("achivementsSumTarget")) or None,
        preferential_right="Да" if (pref9 or pref10) else None,
        priority=entry.get("priority"),
        # isConcertToEnrollment — согласие на зачисление (опечатка в API ВШЭ).
        has_agreement=bool(entry.get("isConcertToEnrollment")),
        review_status=(entry.get("participantStatus") or "").strip() or None,
    )
