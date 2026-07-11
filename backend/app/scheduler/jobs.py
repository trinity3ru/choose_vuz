"""
Планировщик периодической постановки парсинга в очередь (APScheduler).

Используется ТОЛЬКО в локальной разработке (ENABLE_SCHEDULER=true):
в проде расписание живёт на уровне VPS (systemd-таймеры -> app.cli enqueue),
см. DEPLOY_PLAN.md. Планировщик не парсит сам — он ставит задания в очередь
parser_runs, которые выполняет worker (python -m app.cli consume-queue).
Поэтому модуль не импортирует парсеры.

Интервал берётся из config.json (parser_settings.parse_interval_hours).
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config_loader import load_config
from app.services import queue

logger = logging.getLogger(__name__)

# Единый экземпляр планировщика на всё приложение.
scheduler = AsyncIOScheduler()


async def _scheduled_enqueue() -> None:
    """Задача по расписанию: поставить все включённые вузы в очередь."""
    try:
        queued = 0
        for code in queue.enabled_codes():
            run = await queue.enqueue(code)
            if run is not None:
                queued += 1
        logger.info("Плановая постановка в очередь: %d заданий", queued)
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка плановой постановки в очередь")


def start_scheduler() -> None:
    """Настроить интервал из конфига и запустить планировщик."""
    config = load_config()
    hours = config.parser_settings.parse_interval_hours

    scheduler.add_job(
        _scheduled_enqueue,
        trigger="interval",
        hours=hours,
        id="enqueue_job",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Планировщик запущен, интервал = %d ч", hours)


def stop_scheduler() -> None:
    """Остановить планировщик (при завершении приложения)."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Планировщик остановлен")
