"""Быстрая проверка парсера SPMI без БД."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app.core.config_loader import load_config
from app.parser.spmi import SpmiParser


async def main() -> None:
    config = load_config()
    uni = next(u for u in config.universities if u.code == "SPMI")
    parser = SpmiParser(uni, request_delay_seconds=0.3)
    result = await parser.parse()
    print("status:", result.status, "errors:", result.errors)
    seen: dict[str, int] = {}
    for major in result.majors:
        s = major.summary
        key = str(major.internal_id)
        seen[key] = len(major.applicants)
        print(
            f"{major.code}: rows={len(major.applicants)} places={s.places if s else None} "
            f"agreements={s.agreements if s else None} spec_id={major.internal_id}"
        )
    print("unique spec groups:", seen)


if __name__ == "__main__":
    asyncio.run(main())
