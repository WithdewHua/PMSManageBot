"""add blackjack hand table

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-08-21 13:55:37.541707

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "x4y5z6a7b8c9"
down_revision: Union[str, None] = "w3x4y5z6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "blackjack_hand",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("tg_id", sa.BIGINT(), nullable=False),
        sa.Column("status", sa.SMALLINT(), nullable=False, server_default="1"),
        sa.Column("bet_credits", sa.Integer(), nullable=False),
        sa.Column("doubled", sa.SMALLINT(), nullable=False, server_default="0"),
        sa.Column("deck_seed", sa.Text(), nullable=False),
        sa.Column("next_card_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("player_cards", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("dealer_cards", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("payout_credits", sa.Float(), nullable=True),
        sa.Column("rake_credits", sa.Float(), nullable=True),
        sa.Column(
            "rake_bp_on_profit", sa.Integer(), nullable=False, server_default="300"
        ),
        sa.Column("rake_glory_bp", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("blackjack_payout", sa.Float(), nullable=False, server_default="1.5"),
        sa.Column(
            "dealer_hits_soft_17", sa.SMALLINT(), nullable=False, server_default="0"
        ),
        sa.Column(
            "hand_timeout_minutes", sa.Integer(), nullable=False, server_default="15"
        ),
        sa.Column("tournament_id", sa.BIGINT(), nullable=True),
        sa.Column("created_at_ms", sa.BIGINT(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("settled_at", sa.BIGINT(), nullable=True),
        sa.CheckConstraint("bet_credits > 0", name="ck_blackjack_hand_bet_gt_0"),
        sa.CheckConstraint("status IN (1,2,3,4)", name="ck_blackjack_hand_status"),
        sa.CheckConstraint("doubled IN (0,1)", name="ck_blackjack_hand_doubled"),
        sa.CheckConstraint(
            "next_card_index >= 0", name="ck_blackjack_hand_next_card_index_nonneg"
        ),
        sa.CheckConstraint(
            "hand_timeout_minutes > 0", name="ck_blackjack_hand_timeout_gt_0"
        ),
        sa.ForeignKeyConstraint(["tg_id"], ["statistics.tg_id"], onupdate="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_blackjack_hand_tg_id"), "blackjack_hand", ["tg_id"])
    op.create_index(
        op.f("ix_blackjack_hand_created_at"), "blackjack_hand", ["created_at"]
    )
    op.create_index(
        "idx_blackjack_hand_user_status", "blackjack_hand", ["tg_id", "status"]
    )
    op.create_index(
        "idx_blackjack_hand_user_time", "blackjack_hand", ["tg_id", "created_at_ms"]
    )


def downgrade() -> None:
    op.drop_index("idx_blackjack_hand_user_time", table_name="blackjack_hand")
    op.drop_index("idx_blackjack_hand_user_status", table_name="blackjack_hand")
    op.drop_index(op.f("ix_blackjack_hand_created_at"), table_name="blackjack_hand")
    op.drop_index(op.f("ix_blackjack_hand_tg_id"), table_name="blackjack_hand")
    op.drop_table("blackjack_hand")
