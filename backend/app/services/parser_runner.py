"""
Раннер парсера: связывает конфиг, парсер и сохранение в БД.

Отвечает за:
- выбор парсера по коду вуза (реестр парсеров — расширяется под новые вузы);
- запуск парсинга и сохранение результата;
- защиту от одновременных запусков (один парсинг в момент времени).
"""

import logging

from app.core.config_loader import load_config
from app.parser.base import BaseParser
from app.parser.guap import GuapParser
from app.parser.hse import HseParser
from app.parser.itmo import ItmoParser
from app.parser.kpfu import KpfuParser
from app.parser.leti import LetiParser
from app.parser.mpei import MpeiParser
from app.parser.samara import SamaraParser
from app.parser.samgtu import SamgtuParser
from app.parser.spbgu import SpbguParser
from app.parser.spbau import SpbauParser
from app.parser.spbstu import SpbstuParser
from app.parser.spmi import SpmiParser
from app.parser.sut import SutParser
from app.parser.tltsu import TltsuParser
from app.parser.urfu import UrfuParser
from app.services.storage import save_parse_result

logger = logging.getLogger(__name__)

# Реестр парсеров: код вуза -> класс парсера.
# Чтобы добавить новый вуз, достаточно написать класс и внести его сюда.
PARSER_REGISTRY: dict[str, type[BaseParser]] = {
    "SPBSTU": SpbstuParser,
    "SUT": SutParser,
    "SAMARA": SamaraParser,
    "SAMGTU": SamgtuParser,
    "SPBGU": SpbguParser,
    "TLTSU": TltsuParser,
    "LETI": LetiParser,
    "MPEI": MpeiParser,
    "ITMO": ItmoParser,
    "SPBAU": SpbauParser,
    "KPFU": KpfuParser,
    "GUAP": GuapParser,
    "SPMI": SpmiParser,
    "URFU": UrfuParser,
    # ВШЭ: кампусы как отдельные вузы, общий класс парсера (кампус
    # проверяется по полю filial в заголовке группы).
    "HSE_MSK": HseParser,
    "HSE_SPB": HseParser,
    "HSE_NN": HseParser,
    "HSE_PERM": HseParser,
}

# Флаг «парсинг идёт». Приложение однопоточное (asyncio), поэтому простой
# булев флаг безопасен: проверка и установка ниже происходят без await между ними.
_running = False


class ParserBusyError(Exception):
    """Парсинг уже выполняется — новый запуск отклонён."""

    pass


def is_running() -> bool:
    """Идёт ли парсинг прямо сейчас."""
    return _running


def try_begin() -> bool:
    """
    Атомарно занять парсер, если он свободен.

    :return: True — успешно заняли (можно запускать); False — уже идёт парсинг.
    """
    global _running
    if _running:
        return False
    _running = True
    return True


def end() -> None:
    """Освободить парсер после завершения работы."""
    global _running
    _running = False


async def run_parser(major_code: str | None = None) -> list[dict]:
    """
    Запустить парсинг с захватом флага (для планировщика и прямого вызова).

    :raises ParserBusyError: если парсинг уже идёт.
    """
    if not try_begin():
        raise ParserBusyError("Парсинг уже выполняется")
    try:
        return await execute(major_code)
    finally:
        end()


async def run_university(
    code: str,
    major_code: str | None = None,
    parser_run_id=None,
) -> dict:
    """
    Спарсить один вуз (для CLI/worker) и сохранить снимок в БД.

    :param code: канонический код вуза из config.json (SPBSTU, ITMO, ...).
    :param major_code: если указан — только одно направление.
    :param parser_run_id: id запуска parser_runs (свяжет снимок с запуском).
    :return: сводка запуска (status, счётчики, ошибки) для parser_runs.
    :raises RuntimeError: если вуз не найден/выключен или нет парсера.
    """
    config = load_config()
    university = next((u for u in config.universities if u.code == code), None)
    if university is None:
        raise RuntimeError(f"вуз {code} не найден в config.json")
    if not university.enabled:
        raise RuntimeError(f"вуз {code} выключен в config.json (enabled=false)")

    parser_cls = PARSER_REGISTRY.get(university.code)
    if parser_cls is None:
        raise RuntimeError(f"нет парсера для вуза {code}")

    uni_config = university
    if major_code is not None:
        filtered = [m for m in university.majors if m.code == major_code]
        if not filtered:
            raise RuntimeError(f"направление {major_code} не найдено у {code}")
        uni_config = university.model_copy(update={"majors": filtered})

    parser = parser_cls(uni_config, config.parser_settings.request_delay_seconds)
    result = await parser.parse()
    snapshot = await save_parse_result(uni_config, result, parser_run_id=parser_run_id)

    records = sum(len(m.applicants) for m in result.majors)
    return {
        "university": university.code,
        "snapshot_id": str(snapshot.id),
        "status": snapshot.status,
        "majors_parsed": len(result.majors),
        "records_found": records,
        "records_saved": records,
        "errors": result.errors,
    }


async def execute(major_code: str | None = None) -> list[dict]:
    """
    Выполнить парсинг всех включённых вузов из конфига (без захвата флага).

    Используется, когда флаг уже занят вызывающей стороной (например, из API,
    который занимает флаг синхронно ещё до старта фоновой задачи).

    :param major_code: если указан — парсить только это направление.
    :return: список кратких итогов по снимкам (для ответа API).
    """
    config = load_config()
    summaries: list[dict] = []

    for university in config.universities:
        if not university.enabled:
            continue

        parser_cls = PARSER_REGISTRY.get(university.code)
        if parser_cls is None:
            logger.warning("Нет парсера для вуза %s — пропуск", university.code)
            continue

        # Если задано направление — оставляем в конфиге только его.
        uni_config = university
        if major_code is not None:
            filtered = [m for m in university.majors if m.code == major_code]
            if not filtered:
                continue
            uni_config = university.model_copy(update={"majors": filtered})

        parser = parser_cls(uni_config, config.parser_settings.request_delay_seconds)
        result = await parser.parse()
        snapshot = await save_parse_result(uni_config, result)

        summaries.append(
            {
                "university": university.code,
                "snapshot_id": str(snapshot.id),
                "status": snapshot.status,
                "majors_parsed": len(result.majors),
                "errors": result.errors,
            }
        )

    return summaries
