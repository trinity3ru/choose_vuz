"""Быстрая проверка парсера GUAP без БД."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app.core.config_loader import load_config
from app.parser.guap import GuapParser


async def main() -> None:
    config = load_config()
    uni = next(u for u in config.universities if u.code == "GUAP")
    parser = GuapParser(uni, request_delay_seconds=0.3)
    result = await parser.parse()
    print("status:", result.status)
    if result.errors:
        print("errors:")
        for err in result.errors:
            print(" ", err)
    for major in result.majors:
        s = major.summary
        print(
            f"{major.code}: rows={len(major.applicants)} places={s.places if s else None} "
            f"agreements={s.agreements if s else None} formed_at={s.list_formed_at if s else None}"
        )


if __name__ == "__main__":
    asyncio.run(main())
