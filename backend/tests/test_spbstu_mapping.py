"""
Тесты маппинга СПбПУ (app/parser/spbstu_mapping.py).

Парсер СПбПУ работает через браузер, поэтому целиком через parse() его в
тестах не гоняем — проверяем чистое преобразование строки get-abit-list,
где и живёт вся логика нормализации.
"""

import pytest

from app.parser.spbstu_mapping import parse_summary, row_to_applicant

# Строка списка в том виде, в каком её отдаёт сайт: БВИ-иконка в base,
# "+" в approval у подавших согласие.
_BVI_ROW = {
    "num": 1,
    "code": "1839958",
    "base": (
        '<span class="fw-bold text-green-emphs" title="Без вступительных испытаний">'
        '<i class="fa-solid fa-star me-1"></i> БВИ</span>'
    ),
    "sum": None,
    "sum_vs": "",
    "counl_ind": 10,
    "count_cel": "",
    "privilege": "Отсутствует",
    "priority": 1,
    "approval": "+",
    "info": "Участвует в конкурсе",
}

_PLAIN_ROW = {
    "num": 2,
    "code": "1430744",
    "base": "Нет",
    "sum": 299,
    "sum_vs": 289,
    "counl_ind": 10,
    "count_cel": 0,
    "privilege": "Отсутствует",
    "priority": 3,
    "approval": "Отсутствует",
    "info": "Участвует в конкурсе",
}


def test_row_with_plus_has_agreement():
    """'+' в колонке approval — согласие на зачисление подано."""
    row = row_to_applicant(_BVI_ROW)
    assert row.applicant_code == "1839958"
    assert row.is_bvi is True
    assert row.has_agreement is True
    assert row.total_score is None
    assert row.priority == 1


def test_row_without_agreement():
    """'Отсутствует' — согласия нет."""
    row = row_to_applicant(_PLAIN_ROW)
    assert row.is_bvi is False
    assert row.has_agreement is False
    assert row.total_score == 299
    assert row.exam_score == 289
    assert row.priority == 3
    assert row.review_status == "Участвует в конкурсе"


@pytest.mark.parametrize(
    ("approval", "expected"),
    [
        ("+", True),
        ("Получено", True),  # прежняя формулировка сайта
        ("Отсутствует", False),
        ("Не получено", False),
        ("", False),
        ("-", False),
        (None, False),
    ],
)
def test_agreement_values(approval, expected):
    """Разные формулировки колонки согласия."""
    raw = {**_PLAIN_ROW, "approval": approval}
    assert row_to_applicant(raw).has_agreement is expected


def test_parse_summary_reads_places_and_applications():
    """Сводка направления: места и число заявлений берём с сайта."""
    summary = parse_summary(
        [
            {
                "places": 60,
                "applications": 3506,
                "date_info": "28.07.2026 20:18",
                "count_agreement": 0,
            }
        ]
    )
    assert summary is not None
    assert summary.places == 60
    assert summary.applications == 3506
    assert summary.list_formed_at == "28.07.2026 20:18"
