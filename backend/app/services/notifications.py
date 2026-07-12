"""
Telegram-уведомления о проблемах парсеров (ТЗ §13).

События:
- parser failed / partial;
- records_found = 0 (запуск «успешен», но данных нет);
- резкое падение записей: records_saved упал на PARSER_RECORDS_DROP_PERCENT %
  и больше относительно последнего успешного запуска вуза (для первого
  запуска сравнения нет);
- worker interrupted (зависшие задачи, найденные recover-stuck-runs);
- stale-данные (check-parser-health).

Правила:
- уведомления best-effort: любая ошибка отправки логируется и глотается —
  алерты никогда не роняют парсинг;
- модуль DB-only (без импорта парсеров): вызывается и в worker, и в api.

Настройки: TELEGRAM_ALERTS_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
"""

import logging
import uuid

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.config_loader import load_config
from app.core.database import async_session_factory
from app.models import ParserRun

logger = logging.getLogger(__name__)

_API_TIMEOUT_S = 15


def _university_name(code: str) -> str:
    """Название вуза по коду (для читаемых сообщений)."""
    try:
        for uni in load_config().universities:
            if uni.code == code:
                return uni.name
    except Exception:  # noqa: BLE001 (сообщение важнее конфига)
        pass
    return code


async def send_telegram(text: str) -> bool:
    """
    Отправить сообщение в Telegram. Возвращает успех отправки.

    Выключенные алерты или незаполненные токены — тихий пропуск (False).
    """
    if not settings.telegram_alerts_enabled:
        return False
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram-алерты включены, но TOKEN/CHAT_ID не заданы")
        return False

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=_API_TIMEOUT_S) as client:
            resp = await client.post(
                url,
                json={"chat_id": settings.telegram_chat_id, "text": text},
            )
        if resp.status_code != 200:
            logger.error("Telegram вернул %s: %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception:  # noqa: BLE001 (алерт не должен ронять запуск)
        logger.exception("Не удалось отправить Telegram-уведомление")
        return False


def _format_run_alert(title: str, run: ParserRun, extra: str = "") -> str:
    """Собрать текст алерта по запуску (формат ТЗ §13)."""
    started = run.started_at.strftime("%Y-%m-%d %H:%M") if run.started_at else "—"
    lines = [
        f"VuzFinder: {title}",
        "",
        f"Вуз: {_university_name(run.university_code)}",
        f"Код: {run.university_code}",
        f"Статус: {run.status}",
        f"Время запуска: {started}",
    ]
    if run.records_saved is not None:
        lines.append(f"Записей: {run.records_saved}")
    if run.error_message:
        lines.append(f"Ошибка: {run.error_message[:500]}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


async def _previous_success_records(run: ParserRun) -> int | None:
    """records_saved последнего успешного запуска вуза ДО текущего."""
    async with async_session_factory() as s:
        prev = (
            await s.execute(
                select(ParserRun.records_saved)
                .where(
                    ParserRun.university_code == run.university_code,
                    ParserRun.id != run.id,
                    ParserRun.status == "success",
                    ParserRun.records_saved.is_not(None),
                    ParserRun.created_at < run.created_at,
                )
                .order_by(ParserRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    return prev


async def notify_run_finished(run_id: uuid.UUID) -> None:
    """
    Проверить завершённый запуск и отправить алерты по событиям ТЗ §13.

    Вызывается из CLI после finalize; ошибки не пробрасываются.
    """
    try:
        async with async_session_factory() as s:
            run = (
                await s.execute(select(ParserRun).where(ParserRun.id == run_id))
            ).scalar_one_or_none()
        if run is None:
            return

        if run.status == "failed":
            await send_telegram(_format_run_alert("ошибка парсера ❌", run))
            return
        if run.status == "partial":
            await send_telegram(_format_run_alert("частичный результат парсера ⚠️", run))
            return

        # Успешный запуск: проверяем подозрительные данные.
        if not run.records_saved:
            await send_telegram(
                _format_run_alert("парсер не нашёл ни одной записи ⚠️", run)
            )
            return

        previous = await _previous_success_records(run)
        if previous:
            drop_percent = (previous - run.records_saved) / previous * 100
            if drop_percent >= settings.parser_records_drop_percent:
                await send_telegram(
                    _format_run_alert(
                        "резкое падение числа записей ⚠️",
                        run,
                        extra=(
                            f"Было (последний успешный): {previous}, "
                            f"стало: {run.records_saved} "
                            f"(-{drop_percent:.0f}%, порог "
                            f"{settings.parser_records_drop_percent}%)"
                        ),
                    )
                )
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка проверки алертов запуска %s", run_id)


async def notify_worker_interrupted(runs: list[ParserRun]) -> None:
    """Алерт о зависших задачах, восстановленных recover-stuck-runs."""
    try:
        for run in runs:
            await send_telegram(_format_run_alert("worker прерван (зависший запуск) ❌", run))
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка алерта worker interrupted")


async def notify_stale(stale: list[dict]) -> None:
    """
    Сводный алерт об устаревших данных (из check-parser-health).

    :param stale: элементы отчёта health с is_stale=true.
    """
    if not stale:
        return
    try:
        lines = [
            "VuzFinder: данные устарели ⚠️",
            "",
            f"Порог свежести: {settings.parser_stale_hours} ч",
            "",
        ]
        for uni in stale:
            age = f"{uni['age_hours']} ч" if uni.get("age_hours") is not None else "никогда"
            lines.append(f"- {uni['code']}: последнее обновление {age}")
        await send_telegram("\n".join(lines))
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка stale-алерта")
