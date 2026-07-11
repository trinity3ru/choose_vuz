"""Показать дату последнего success-снимка по каждому вузу (как во frontend)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.core.database import async_session_factory
from app.models import Applicant, Major, ParseSnapshot, University


async def main() -> None:
    async with async_session_factory() as session:
        unis = (
            await session.execute(
                select(University.code, University.name).order_by(University.code)
            )
        ).all()

        print("=== Latest SUCCESS snapshot per university (frontend logic) ===")
        for code, name in unis:
            stmt = (
                select(ParseSnapshot.created_at, ParseSnapshot.status, func.count(Applicant.id))
                .join(Applicant, Applicant.snapshot_id == ParseSnapshot.id)
                .join(Major, Major.id == Applicant.major_id)
                .join(University, University.id == Major.university_id)
                .where(University.code == code, ParseSnapshot.status == "success")
                .group_by(ParseSnapshot.id, ParseSnapshot.created_at, ParseSnapshot.status)
                .order_by(ParseSnapshot.created_at.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).first()
            if row is None:
                print(f"{code:8} | NO success snapshot")
            else:
                created_at, status, cnt = row
                print(f"{code:8} | {created_at} | {status} | {cnt} rows")

        latest_any = (
            await session.execute(
                select(ParseSnapshot.created_at, ParseSnapshot.status).order_by(
                    ParseSnapshot.created_at.desc()
                ).limit(1)
            )
        ).first()
        print()
        if latest_any:
            print(f"Newest snapshot in DB (any status): {latest_any[0]} ({latest_any[1]})")


if __name__ == "__main__":
    asyncio.run(main())
