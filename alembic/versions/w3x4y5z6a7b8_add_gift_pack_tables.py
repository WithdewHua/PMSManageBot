"""add gift pack tables

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-08-19 11:05:49.534155

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w3x4y5z6a7b8"
down_revision: Union[str, None] = "v2w3x4y5z6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gift_pack",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rewards", sa.Text(), nullable=False),
        sa.Column("eligibility", sa.Text(), nullable=True),
        sa.Column("total_quantity", sa.Integer(), nullable=True),
        sa.Column("claimed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_at", sa.BIGINT(), nullable=False),
        sa.Column("end_at", sa.BIGINT(), nullable=False),
        sa.Column("max_prompt_count", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("is_enabled", sa.SMALLINT(), nullable=False, server_default="1"),
        sa.Column("expiry_notified", sa.SMALLINT(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.BIGINT(), nullable=True),
        sa.Column("created_at", sa.BIGINT(), nullable=False),
        sa.Column("updated_at", sa.BIGINT(), nullable=False),
        sa.CheckConstraint("end_at > start_at", name="ck_gift_pack_window"),
        sa.CheckConstraint("claimed_count >= 0", name="ck_gift_pack_claimed_count"),
        sa.CheckConstraint(
            "total_quantity IS NULL OR total_quantity > 0",
            name="ck_gift_pack_total_quantity",
        ),
        sa.CheckConstraint(
            "max_prompt_count > 0", name="ck_gift_pack_max_prompt_count"
        ),
        sa.CheckConstraint("is_enabled IN (0, 1)", name="ck_gift_pack_enabled"),
        sa.CheckConstraint(
            "expiry_notified IN (0, 1)", name="ck_gift_pack_expiry_notified"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_gift_pack_start_at"), "gift_pack", ["start_at"])
    op.create_index(op.f("ix_gift_pack_end_at"), "gift_pack", ["end_at"])
    op.create_index(
        "idx_gift_pack_window_enabled",
        "gift_pack",
        ["start_at", "end_at", "is_enabled"],
    )
    op.create_index(
        "idx_gift_pack_expiry_scan", "gift_pack", ["end_at", "expiry_notified"]
    )

    op.create_table(
        "gift_pack_user_state",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("pack_id", sa.BIGINT(), nullable=False),
        sa.Column("tg_id", sa.BIGINT(), nullable=False),
        sa.Column("claimed_at", sa.BIGINT(), nullable=True),
        sa.Column("reward_snapshot", sa.Text(), nullable=True),
        sa.Column("last_prompted_at", sa.BIGINT(), nullable=True),
        sa.Column("prompt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("prompt_count >= 0", name="ck_gift_pack_state_prompt_count"),
        sa.ForeignKeyConstraint(["pack_id"], ["gift_pack.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tg_id"], ["statistics.tg_id"], onupdate="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pack_id", "tg_id", name="uq_gift_pack_user"),
    )
    op.create_index(
        op.f("ix_gift_pack_user_state_pack_id"), "gift_pack_user_state", ["pack_id"]
    )
    op.create_index(
        op.f("ix_gift_pack_user_state_tg_id"), "gift_pack_user_state", ["tg_id"]
    )
    op.create_index(
        "idx_gift_pack_state_user_claimed",
        "gift_pack_user_state",
        ["tg_id", "claimed_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_gift_pack_state_user_claimed", table_name="gift_pack_user_state")
    op.drop_index(
        op.f("ix_gift_pack_user_state_tg_id"), table_name="gift_pack_user_state"
    )
    op.drop_index(
        op.f("ix_gift_pack_user_state_pack_id"), table_name="gift_pack_user_state"
    )
    op.drop_table("gift_pack_user_state")
    op.drop_index("idx_gift_pack_expiry_scan", table_name="gift_pack")
    op.drop_index("idx_gift_pack_window_enabled", table_name="gift_pack")
    op.drop_index(op.f("ix_gift_pack_end_at"), table_name="gift_pack")
    op.drop_index(op.f("ix_gift_pack_start_at"), table_name="gift_pack")
    op.drop_table("gift_pack")
