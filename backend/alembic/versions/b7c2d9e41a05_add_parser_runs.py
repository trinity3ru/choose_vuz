"""add parser_runs (история и очередь запусков парсера)

Revision ID: b7c2d9e41a05
Revises: 8f6a96333820
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7c2d9e41a05"
down_revision: Union[str, None] = "8f6a96333820"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parser_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("university_code", sa.String(length=50), nullable=False),
        sa.Column("parser_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("records_found", sa.Integer(), nullable=True),
        sa.Column("records_saved", sa.Integer(), nullable=True),
        sa.Column("records_changed", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("log_path", sa.String(length=500), nullable=True),
        sa.Column("screenshot_path", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_parser_runs_university_code"), "parser_runs", ["university_code"]
    )
    op.create_index(op.f("ix_parser_runs_status"), "parser_runs", ["status"])
    op.create_index(op.f("ix_parser_runs_started_at"), "parser_runs", ["started_at"])
    op.create_index(op.f("ix_parser_runs_created_at"), "parser_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_parser_runs_created_at"), table_name="parser_runs")
    op.drop_index(op.f("ix_parser_runs_started_at"), table_name="parser_runs")
    op.drop_index(op.f("ix_parser_runs_status"), table_name="parser_runs")
    op.drop_index(op.f("ix_parser_runs_university_code"), table_name="parser_runs")
    op.drop_table("parser_runs")
