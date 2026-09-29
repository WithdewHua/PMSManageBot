"""add custom line settlement ledger

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_line_settlement",
        sa.Column("id", sa.BIGINT(), nullable=False),
        sa.Column("line_id", sa.BIGINT(), nullable=False),
        sa.Column("tg_id", sa.BIGINT(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("year_month", sa.Text(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("traffic_bytes", sa.BIGINT(), nullable=False),
        sa.Column("credits", sa.Numeric(), nullable=False),
        sa.Column("created_at", sa.BIGINT(), nullable=False),
        sa.CheckConstraint(
            "trigger IN ('monthly', 'delete')", name="ck_custom_line_settlement_trigger"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "line_id", "year_month", name="uq_custom_line_settlement_line_month"
        ),
    )
    op.create_index(
        "ix_custom_line_settlement_domain_month",
        "custom_line_settlement",
        ["domain", "year_month"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_custom_line_settlement_domain_month", table_name="custom_line_settlement"
    )
    op.drop_table("custom_line_settlement")
