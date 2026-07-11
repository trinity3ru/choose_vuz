"""Сравнение снимков парсера: последний vs предыдущий по каждому вузу."""

import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.core.database import async_session_factory
from app.models import Applicant, Major, MajorStats, ParseSnapshot, University


async def snapshot_total(session, snapshot_id: UUID) -> int:
    return (
        await session.execute(
            select(func.count(Applicant.id)).where(Applicant.snapshot_id == snapshot_id)
        )
    ).scalar_one()


async def snapshot_universities(session, snapshot_id: UUID) -> set[str]:
    rows = (
        await session.execute(
            select(University.code)
            .join(Major, Major.university_id == University.id)
            .join(Applicant, Applicant.major_id == Major.id)
            .where(Applicant.snapshot_id == snapshot_id)
            .distinct()
        )
    ).all()
    return {r[0] for r in rows}


async def by_major(session, snapshot_id: UUID) -> dict[tuple[str, str], int]:
    rows = (
        await session.execute(
            select(University.code, Major.code, func.count(Applicant.id))
            .join(Major, Major.university_id == University.id)
            .join(Applicant, Applicant.major_id == Major.id)
            .where(Applicant.snapshot_id == snapshot_id)
            .group_by(University.code, Major.code)
            .order_by(University.code, Major.code)
        )
    ).all()
    return {(u, mc): c for u, mc, c in rows}


async def latest_snapshots_per_uni(session) -> dict[str, list[ParseSnapshot]]:
    """Для каждого вуза — два последних снимка, где есть его данные."""
    snaps = (
        await session.execute(
            select(ParseSnapshot).order_by(ParseSnapshot.created_at.desc()).limit(50)
        )
    ).scalars().all()

    per_uni: dict[str, list[ParseSnapshot]] = {}
    for snap in snaps:
        unis = await snapshot_universities(session, snap.id)
        for uni in unis:
            bucket = per_uni.setdefault(uni, [])
            if len(bucket) < 2:
                bucket.append(snap)
    return per_uni


async def main() -> None:
    async with async_session_factory() as session:
        snaps = (
            await session.execute(
                select(ParseSnapshot).order_by(ParseSnapshot.created_at.desc()).limit(8)
            )
        ).scalars().all()

        print("=== Last snapshots (raw) ===")
        for s in snaps:
            cnt = await snapshot_total(session, s.id)
            unis = sorted(await snapshot_universities(session, s.id))
            uni_label = ",".join(unis) if unis else "(empty)"
            print(f"{s.created_at} | {s.status} | {cnt:>6} rows | {uni_label}")

        per_uni = await latest_snapshots_per_uni(session)
        if not per_uni:
            print("No data")
            return

        print()
        print("=== Per university: latest vs previous snapshot ===")
        grand_now = 0
        grand_was = 0

        for uni in sorted(per_uni):
            bucket = per_uni[uni]
            cur = bucket[0]
            prev = bucket[1] if len(bucket) > 1 else None

            cur_map = await by_major(session, cur.id)
            cur_total = sum(cur_map.values())
            grand_now += cur_total

            print()
            print(f"[{uni}] current: {cur.created_at} ({cur.status}), rows={cur_total}")
            if prev is None:
                print("  no previous snapshot for this university")
                continue

            prev_map = await by_major(session, prev.id)
            prev_total = sum(prev_map.values())
            grand_was += prev_total
            print(f"  previous: {prev.created_at} ({prev.status}), rows={prev_total}")
            print(f"  delta: {cur_total - prev_total:+d}")

            all_keys = sorted(set(cur_map) | set(prev_map))
            for u, mc in all_keys:
                c = cur_map.get((u, mc), 0)
                p = prev_map.get((u, mc), 0)
                if c == p:
                    continue
                print(f"    {mc}: {p} -> {c} ({c - p:+d})")

        print()
        print("=== Totals across universities (latest snapshot each) ===")
        print(f"Now: {grand_now} | Was: {grand_was} | Delta: {grand_now - grand_was:+d}")
        print()
        print("Note: /api/v1/parser/status shows only the single newest snapshot")
        print("      (2412 = SUT), not the sum of all universities.")


if __name__ == "__main__":
    asyncio.run(main())
