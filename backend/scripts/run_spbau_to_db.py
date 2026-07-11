"""
Запуск парсера СПбАУ (Алферовский университет) и сохранение в PostgreSQL.

Тестовый scripts/test_spbau_mapping.py только проверяет разбор xlsx.
Фронтенд показывает вузы из БД — без этого шага Алферова в списке не будет.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config_loader import load_config
from app.parser.spbau import SpbauParser
from app.services.storage import save_parse_result


async def main() -> None:
    config = load_config()
    uni = next(u for u in config.universities if u.code == "SPBAU")

    print("Парсинг СПбАУ...")
    parser = SpbauParser(uni, config.parser_settings.request_delay_seconds)
    result = await parser.parse()

    print("Статус:", result.status)
    if result.errors:
        print("Ошибки:", result.errors)

    for major in result.majors:
        print(f"  {major.code}: {len(major.applicants)} абитуриентов")

    if not result.majors:
        print("Нет данных для сохранения.")
        sys.exit(1)

    print("Сохранение в БД...")
    snapshot = await save_parse_result(uni, result)
    print("Готово. snapshot_id =", snapshot.id)
    print("Теперь обновите страницу фронтенда — СПбАУ должен появиться в списке.")


if __name__ == "__main__":
    asyncio.run(main())
