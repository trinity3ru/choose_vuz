"""
Pydantic-схемы для валидации файла config.json.

Здесь описана структура конфигурации вузов и направлений.
При загрузке конфига Pydantic проверит типы и допустимые значения
и выдаст понятную ошибку с указанием проблемного поля.

Значения study_form и finance_type ограничены допустимым набором,
так как на сайте СПбПУ они соответствуют конкретным кодам фильтров
(маппинг кодов задаётся в парсере, а не здесь).
"""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

# Допустимые формы обучения (соответствуют filter_1 на сайте СПбПУ).
StudyForm = Literal["Заочная", "Очная", "Очно-заочная"]

# Допустимые условия поступления (соответствуют filter_2 на сайте СПбПУ).
FinanceType = Literal[
    "Бюджетная основа",
    "Контракт",
    "Особое право",
    "Отдельная квота",
    "Целевой прием",
]


class MajorParams(BaseModel):
    """Параметры отбора для направления: форма обучения и условия поступления."""

    study_form: StudyForm
    finance_type: FinanceType


class MajorConfig(BaseModel):
    """Одно направление подготовки в конфиге."""

    code: str = Field(..., min_length=1, description="Код направления, напр. 09.03.04")
    name: str = Field(..., min_length=1, description="Название направления")
    params: MajorParams
    # Необязательный внешний идентификатор программы на сайте вуза.
    # Нужен для вузов, где список открывается по прямому id (напр. Самарский: ?pk=10).
    # Для СПбПУ/СПбГУТ не используется (id вычисляется парсером в рантайме).
    external_id: str | None = Field(
        default=None,
        description="Внешний id программы на сайте (напр. pk для priemsamara.ru)",
    )


class UniversityConfig(BaseModel):
    """Один вуз с его направлениями."""

    code: str = Field(..., min_length=1, description="Короткий код вуза, напр. SPBSTU")
    name: str = Field(..., min_length=1)
    url: HttpUrl
    enabled: bool = True
    majors: list[MajorConfig] = Field(..., min_length=1)


class ParserSettings(BaseModel):
    """Общие настройки работы парсера."""

    # Интервал автозапуска парсинга в часах.
    parse_interval_hours: int = Field(default=4, ge=1)
    # Пауза между запросами направлений (защита от блокировок), в секундах.
    request_delay_seconds: float = Field(default=1.5, ge=0)


class AppConfig(BaseModel):
    """Корневая модель всего файла config.json."""

    universities: list[UniversityConfig] = Field(..., min_length=1)
    parser_settings: ParserSettings = ParserSettings()
