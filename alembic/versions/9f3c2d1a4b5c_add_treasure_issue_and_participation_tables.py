"""add treasure issue and participation tables

Revision ID: 9f3c2d1a4b5c
Revises: p1q2r3s4t5u6
Create Date: 2026-03-13

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9f3c2d1a4b5c"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "treasure_issue",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prize_credits", sa.Integer(), nullable=False),
        sa.Column("total_credits_required", sa.Integer(), nullable=False),
        sa.Column(
            "credits_per_share", sa.Integer(), nullable=False, server_default="10"
        ),
        sa.Column("total_shares", sa.Integer(), nullable=False),
        sa.Column(
            "start_number", sa.Integer(), nullable=False, server_default="10000001"
        ),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("shares_sold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("external_random_b", sa.BigInteger(), nullable=True),
        sa.Column("winner_number", sa.Integer(), nullable=True),
        sa.Column("winner_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("settled_at", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("prize_credits > 0", name="ck_treasure_issue_prize_gt_0"),
        sa.CheckConstraint(
            "total_credits_required >= prize_credits",
            name="ck_treasure_issue_total_ge_prize",
        ),
        sa.CheckConstraint(
            "credits_per_share > 0",
            name="ck_treasure_issue_credits_per_share_gt_0",
        ),
        sa.CheckConstraint(
            "total_shares > 0",
            name="ck_treasure_issue_total_shares_gt_0",
        ),
    )
    op.create_index(
        "ix_treasure_issue_created_at", "treasure_issue", ["created_at"], unique=False
    )
    op.create_index(
        "ix_treasure_issue_winner_tg_id",
        "treasure_issue",
        ["winner_tg_id"],
        unique=False,
    )

    op.create_table(
        "treasure_participation",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "issue_id",
            sa.BigInteger(),
            sa.ForeignKey("treasure_issue.id"),
            nullable=False,
        ),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("lucky_number", sa.Integer(), nullable=False),
        sa.Column("cost_credits", sa.Integer(), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "issue_id",
            "lucky_number",
            name="uq_treasure_participation_issue_number",
        ),
    )
    op.create_index(
        "idx_treasure_participation_issue_time",
        "treasure_participation",
        ["issue_id", "created_at_ms"],
        unique=False,
    )
    op.create_index(
        "ix_treasure_participation_issue_id",
        "treasure_participation",
        ["issue_id"],
        unique=False,
    )
    op.create_index(
        "ix_treasure_participation_tg_id",
        "treasure_participation",
        ["tg_id"],
        unique=False,
    )
    op.create_index(
        "ix_treasure_participation_created_at_ms",
        "treasure_participation",
        ["created_at_ms"],
        unique=False,
    )
    op.create_index(
        "ix_treasure_participation_created_at",
        "treasure_participation",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_treasure_participation_created_at", table_name="treasure_participation"
    )
    op.drop_index(
        "ix_treasure_participation_created_at_ms", table_name="treasure_participation"
    )
    op.drop_index(
        "ix_treasure_participation_tg_id", table_name="treasure_participation"
    )
    op.drop_index(
        "ix_treasure_participation_issue_id", table_name="treasure_participation"
    )
    op.drop_index(
        "idx_treasure_participation_issue_time", table_name="treasure_participation"
    )
    op.drop_table("treasure_participation")

    op.drop_index("ix_treasure_issue_winner_tg_id", table_name="treasure_issue")
    op.drop_index("ix_treasure_issue_created_at", table_name="treasure_issue")
    op.drop_table("treasure_issue")
