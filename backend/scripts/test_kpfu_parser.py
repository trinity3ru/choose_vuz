"""Быстрая проверка парсера КФУ без БД."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

from app.core.config_loader import load_config
from app.parser.kpfu import KpfuParser


async def main():
    config = load_config()
    uni = next(u for u in config.universities if u.code == "KPFU")
    parser = KpfuParser(uni, request_delay_seconds=0.5)
    result = await parser.parse()
    print("status:", result.status, "errors:", result.errors)
    for major in result.majors:
        s = major.summary
        print(
            f"{major.code}: rows={len(major.applicants)} places={s.places if s else None} "
            f"agreements={s.agreements if s else None} spec_id={major.internal_id}"
        )


if __name__ == "__main__":
    asyncio.run(main())
