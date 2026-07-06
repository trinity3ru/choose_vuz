"""
Планировщик периодического запуска парсинга (APScheduler).

Интервал берётся из config.json (parser_settings.parse_interval_hours).
Планировщик создаётся один раз при старте приложения и останавливается
при завершении. Защита от одновременных запусков обеспечивается раннером.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config_loader import load_config
from app.services import parser_runner

logger = logging.getLogger(__name__)

# Единый экземпляр планировщика на всё приложение.
scheduler = AsyncIOScheduler()


async def _scheduled_parse() -> None:
    """Задача по расписанию: запустить парсинг, не роняя планировщик."""
    try:
        logger.info("Плановый запуск парсинга")
        await parser_runner.run_parser()
    except parser_runner.ParserBusyError:
        logger.info("Плановый запуск пропущен: парсинг уже идёт")
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка планового парсинга")


def start_scheduler() -> None:
    """Настроить интервал из конфига и запустить планировщик."""
    config = load_config()
    hours = config.parser_settings.parse_interval_hours

    scheduler.add_job(
        _scheduled_parse,
        trigger="interval",
        hours=hours,
        id="parse_job",
        replace_existing=True,
        max_instances=1,  # не запускать вторую копию, если предыдущая ещё идёт
    )
    scheduler.start()
    logger.info("Планировщик запущен, интервал = %d ч", hours)


def stop_scheduler() -> None:
    """Остановить планировщик (при завершении приложения)."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Планировщик остановлен")
