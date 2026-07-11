"""Тест парсера СПбАУ (Алферовский университет)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config_loader import load_config
from app.parser.spbau import SpbauParser


async def main() -> None:
    config = load_config()
    uni = next(u for u in config.universities if u.code == "SPBAU")
    parser = SpbauParser(uni, config.parser_settings.request_delay_seconds)
    result = await parser.parse()

    print("status:", result.status)
    print("errors:", result.errors)
    for major in result.majors:
        s = major.summary
        print(
            f"{major.code} {major.name}: applicants={len(major.applicants)}, "
            f"places={s.places if s else None}, agreements={s.agreements if s else None}"
        )
        if major.applicants:
            a = major.applicants[0]
            print("  first:", a.applicant_code, a.total_score, a.has_agreement, a.is_bvi)


if __name__ == "__main__":
    asyncio.run(main())
