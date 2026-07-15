"""
Парсер ранжированных списков поступающих УрФУ (urfu.ru).

Официальная страница /ru/alpha/ranzhirovannye-spiski-postupajushchikh/ рендерится
JS, но данные лежат в статических HTML-файлах рейтингов (по одному на институт):

    https://urfu.ru/api/entrants/files/rating-0002-{institute:03d}-01-1.html
      0002 — уровень (бакалавриат/специалитет)
      {institute} — номер института (001..017)
      01 — основной конкурс; 1 — бюджет

Один файл (~7 МБ) содержит десятки списков всех направлений института. Браузер
не нужен — httpx + разбор HTML в urfu_mapping. Файл кэшируется по номеру института,
чтобы несколько направлений одного института скачивали его один раз (как у Горного).

external_id направления в конфиге = "NNN::<Направление (образовательная программа)>",
где NNN — номер института. Направление в пределах института уникально.
"""

import logging

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.urfu_mapping import (
    STUDY_FORM_NAMES,
    ParsedList,
    normalize_direction,
    parse_institute_lists,
)
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)

# Шаблон адреса файла рейтинга: институт + основной конкурс + бюджет.
FILE_URL = "https://urfu.ru/api/entrants/files/rating-0002-{institute:03d}-01-1.html"
_REFERER = "https://urfu.ru/ru/alpha/ranzhirovannye-spiski-postupajushchikh/"

# Разделитель в external_id: "003::09.03.01 Информатика ... (Алгоритмы ИИ)".
_EXTERNAL_ID_SEP = "::"

# Файлы рейтингов тяжёлые (единицы–десятки МБ) — увеличенный таймаут.
_TIMEOUT_MS = 180_000

# Кэш института: номер -> {направление: (места, строки)}.
_Cache = dict[str, dict[str, ParsedList]]


class UrfuParser(HttpParser):
    """Парсер УрФУ. Реализует интерфейс HttpParser (httpx, без браузера)."""

    request_timeout_ms = _TIMEOUT_MS

    def extra_headers(self) -> dict[str, str]:
        return {"Referer": _REFERER}

    async def _prepare(self, client: httpx.AsyncClient) -> _Cache:
        """Пустой кэш институтов; файлы качаются лениво в _parse_major."""
        return {}

    async def _load_institute(
        self, client: httpx.AsyncClient, institute: str, study_form: str
    ) -> dict[str, ParsedList]:
        """Скачать и разобрать HTML-файл института (все его основные бюджетные списки)."""
        try:
            number = int(institute)
        except ValueError as exc:
            raise RuntimeError(f"неверный номер института в external_id: {institute!r}") from exc

        url = FILE_URL.format(institute=number)
        resp = await client.get(url)
        raise_for_status(resp, f"файл института {institute}")

        lists = parse_institute_lists(resp.text, study_form=study_form)
        if not lists:
            raise RuntimeError(f"в файле института {institute} нет основных бюджетных списков")
        return lists

    async def _parse_major(
        self, client: httpx.AsyncClient, major: MajorConfig, context: _Cache
    ) -> MajorResult:
        institute, direction = self._split_external_id(major)
        study_form = STUDY_FORM_NAMES.get(
            major.params.study_form, major.params.study_form
        )

        if institute not in context:
            context[institute] = await self._load_institute(client, institute, study_form)

        lists = context[institute]
        places_applicants = lists.get(direction)
        if places_applicants is None:
            available = ", ".join(sorted(lists)[:5])
            raise RuntimeError(
                f"направление {direction!r} не найдено в институте {institute} "
                f"(есть, напр.: {available})"
            )

        places, applicants = places_applicants
        summary = MajorSummary(
            places=places,
            applications=len(applicants),
            agreements=sum(1 for a in applicants if a.has_agreement),
            list_formed_at=None,
        )
        return MajorResult(
            code=major.code,
            name=major.name,
            internal_id=None,
            summary=summary,
            applicants=list(applicants),
        )

    @staticmethod
    def _split_external_id(major: MajorConfig) -> tuple[str, str]:
        """Разобрать external_id на номер института и строку направления."""
        raw = (major.external_id or "").strip()
        if _EXTERNAL_ID_SEP not in raw:
            raise RuntimeError(
                f"external_id направления {major.code} должен быть "
                f"'NNN{_EXTERNAL_ID_SEP}<направление>', получено: {raw!r}"
            )
        institute, direction = raw.split(_EXTERNAL_ID_SEP, 1)
        return institute.strip(), normalize_direction(direction)
