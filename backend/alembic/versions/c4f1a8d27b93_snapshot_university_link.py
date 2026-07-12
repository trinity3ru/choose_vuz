"""parse_snapshots: прямая ссылка на вуз и на запуск парсера

Revision ID: c4f1a8d27b93
Revises: b7c2d9e41a05
Create Date: 2026-07-12

Правило backfill university_id для существующих снимков (DEPLOY_PLAN, раунд C):
1) через заявления:  Applicant -> Major -> University;
2) при их отсутствии через сводки: MajorStats -> Major -> University;
3) оставшиеся неатрибутируемые legacy-снимки удаляются (у них нет ни заявлений,
   ни сводок — восстановить принадлежность невозможно), затем NOT NULL.

parser_run_id — ON DELETE SET NULL: retention снимков и истории запусков
независимы друг от друга.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4f1a8d27b93"
down_revision: Union[str, None] = "b7c2d9e41a05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "parse_snapshots", sa.Column("university_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "parse_snapshots", sa.Column("parser_run_id", sa.UUID(), nullable=True)
    )

    # Шаг 1: атрибуция через заявления (Applicant -> Major -> University).
    op.execute(
        """
        UPDATE parse_snapshots ps
        SET university_id = sub.university_id
        FROM (
            SELECT DISTINCT a.snapshot_id, m.university_id
            FROM applicants a
            JOIN majors m ON m.id = a.major_id
        ) sub
        WHERE sub.snapshot_id = ps.id AND ps.university_id IS NULL
        """
    )

    # Шаг 2: атрибуция через сводки (MajorStats -> Major -> University).
    op.execute(
        """
        UPDATE parse_snapshots ps
        SET university_id = sub.university_id
        FROM (
            SELECT DISTINCT s.snapshot_id, m.university_id
            FROM major_stats s
            JOIN majors m ON m.id = s.major_id
        ) sub
        WHERE sub.snapshot_id = ps.id AND ps.university_id IS NULL
        """
    )

    # Шаг 3: неатрибутируемые legacy-снимки удаляем (тех. решение, раунд C).
    op.execute("DELETE FROM parse_snapshots WHERE university_id IS NULL")

    op.alter_column("parse_snapshots", "university_id", nullable=False)
    op.create_foreign_key(
        "fk_parse_snapshots_university_id",
        "parse_snapshots",
        "universities",
        ["university_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_parse_snapshots_parser_run_id",
        "parse_snapshots",
        "parser_runs",
        ["parser_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_parse_snapshots_university_id"), "parse_snapshots", ["university_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_parse_snapshots_university_id"), table_name="parse_snapshots")
    op.drop_constraint(
        "fk_parse_snapshots_parser_run_id", "parse_snapshots", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_parse_snapshots_university_id", "parse_snapshots", type_="foreignkey"
    )
    op.drop_column("parse_snapshots", "parser_run_id")
    op.drop_column("parse_snapshots", "university_id")
