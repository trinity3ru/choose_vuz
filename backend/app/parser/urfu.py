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

Под одним кодом направления у УрФУ бывает несколько образовательных программ
(и в разных институтах). Модель проекта — одно направление = один код на вуз,
поэтому программы одного кода агрегируются в один список (см. merge_programs).

external_id направления в конфиге = список номеров институтов через запятую,
где встречается этот код, напр. "003,017". Парсер качает эти институты и
собирает все списки нужного кода.
"""

import logging

import httpx

from app.parser.http_base import HttpParser, raise_for_status
from app.parser.urfu_mapping import (
    STUDY_FORM_NAMES,
    ParsedList,
    code_of,
    merge_programs,
    parse_institute_lists,
)
from app.schemas.config_schema import MajorConfig
from app.schemas.parser_schema import MajorResult, MajorSummary

logger = logging.getLogger(__name__)

# Шаблон адреса файла рейтинга: институт + основной конкурс + бюджет.
FILE_URL = "https://urfu.ru/api/entrants/files/rating-0002-{institute:03d}-01-1.html"
_REFERER = "https://urfu.ru/ru/alpha/ranzhirovannye-spiski-postupajushchikh/"

# Разделитель институтов в external_id: "003,017".
_INSTITUTE_SEP = ","

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
        institutes = self._institutes_of(major)
        study_form = STUDY_FORM_NAMES.get(
            major.params.study_form, major.params.study_form
        )

        # Собрать все программы этого кода из указанных институтов.
        programs: list[ParsedList] = []
        for institute in institutes:
            if institute not in context:
                context[institute] = await self._load_institute(client, institute, study_form)
            for direction, places_applicants in context[institute].items():
                if code_of(direction) == major.code:
                    programs.append(places_applicants)

        if not programs:
            raise RuntimeError(
                f"направление {major.code} не найдено в институтах {institutes}"
            )

        places, applicants = merge_programs(programs)
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
            applicants=applicants,
        )

    @staticmethod
    def _institutes_of(major: MajorConfig) -> list[str]:
        """Разобрать external_id на список номеров институтов ("003,017")."""
        raw = (major.external_id or "").strip()
        institutes = [p.strip() for p in raw.split(_INSTITUTE_SEP) if p.strip()]
        if not institutes:
            raise RuntimeError(
                f"external_id направления {major.code} должен содержать номера "
                f"институтов через запятую, получено: {raw!r}"
            )
        return institutes
