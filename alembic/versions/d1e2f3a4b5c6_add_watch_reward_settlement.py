"""add watch reward settlement ledger

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watch_reward_settlement",
        sa.Column("id", sa.BIGINT(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("account_key", sa.Text(), nullable=False),
        sa.Column("settlement_date", sa.Text(), nullable=False),
        sa.Column("tg_id", sa.BIGINT(), nullable=True),
        sa.Column("credits_delta", sa.Numeric(), nullable=False),
        sa.Column("premium_charge", sa.Numeric(), nullable=False),
        sa.Column("inviter_tg_id", sa.BIGINT(), nullable=True),
        sa.Column("inviter_bonus", sa.Numeric(), nullable=False),
        sa.Column("created_at", sa.BIGINT(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "service",
            "account_key",
            "settlement_date",
            name="uq_watch_reward_settlement_account_date",
        ),
    )
    op.create_index(
        "ix_watch_reward_settlement_date",
        "watch_reward_settlement",
        ["settlement_date"],
    )
    op.create_index(
        "ix_watch_reward_settlement_tg_id",
        "watch_reward_settlement",
        ["tg_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_watch_reward_settlement_tg_id", table_name="watch_reward_settlement"
    )
    op.drop_index(
        "ix_watch_reward_settlement_date", table_name="watch_reward_settlement"
    )
    op.drop_table("watch_reward_settlement")
