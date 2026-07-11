"""Запуск парсера одного вуза с сохранением в БД."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

from app.core.config_loader import load_config
from app.parser.kpfu import KpfuParser
from app.services.storage import save_parse_result

UNIVERSITY_CODE = "KPFU"


async def main():
    config = load_config()
    uni = next(u for u in config.universities if u.code == UNIVERSITY_CODE)
    parser = KpfuParser(uni, config.parser_settings.request_delay_seconds)
    result = await parser.parse()
    snapshot = await save_parse_result(uni, result)
    print("saved snapshot:", snapshot.id, "status:", snapshot.status, "majors:", len(result.majors))
    if result.errors:
        print("errors:", result.errors)
    for m in result.majors:
        print(f"  {m.code}: {len(m.applicants)} applicants")


if __name__ == "__main__":
    asyncio.run(main())
