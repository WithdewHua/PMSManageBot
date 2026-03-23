"""add prediction market tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-23 17:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prediction_market",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("result_option", sa.SmallInteger(), nullable=True),
        sa.Column("betting_deadline", sa.BigInteger(), nullable=True),
        sa.Column("real_yes_pool", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("real_no_pool", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "virtual_yes_pool", sa.Integer(), nullable=False, server_default="500"
        ),
        sa.Column(
            "virtual_no_pool", sa.Integer(), nullable=False, server_default="500"
        ),
        sa.Column("fee_rate_bp", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("fee_burn_bp", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("fee_glory_bp", sa.Integer(), nullable=False, server_default="200"),
        sa.Column(
            "max_bet_per_user", sa.Integer(), nullable=False, server_default="500"
        ),
        sa.Column(
            "total_fee_collected", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("fee_burned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fee_to_glory", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("resolved_by", sa.BigInteger(), nullable=True),
        sa.Column("resolved_at", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("status IN (1,2,3,4)", name="ck_prediction_market_status"),
        sa.CheckConstraint(
            "result_option IS NULL OR result_option IN (0,1)",
            name="ck_prediction_market_result_option",
        ),
        sa.CheckConstraint(
            "real_yes_pool >= 0", name="ck_prediction_market_real_yes_nonneg"
        ),
        sa.CheckConstraint(
            "real_no_pool >= 0", name="ck_prediction_market_real_no_nonneg"
        ),
        sa.CheckConstraint(
            "virtual_yes_pool >= 0", name="ck_prediction_market_virtual_yes_nonneg"
        ),
        sa.CheckConstraint(
            "virtual_no_pool >= 0", name="ck_prediction_market_virtual_no_nonneg"
        ),
        sa.CheckConstraint(
            "fee_rate_bp >= 0 AND fee_rate_bp <= 10000",
            name="ck_prediction_market_fee_rate_bp",
        ),
        sa.CheckConstraint(
            "fee_burn_bp >= 0 AND fee_burn_bp <= 10000",
            name="ck_prediction_market_fee_burn_bp",
        ),
        sa.CheckConstraint(
            "fee_glory_bp >= 0 AND fee_glory_bp <= 10000",
            name="ck_prediction_market_fee_glory_bp",
        ),
        sa.CheckConstraint(
            "fee_burn_bp + fee_glory_bp = fee_rate_bp",
            name="ck_prediction_market_fee_split",
        ),
        sa.CheckConstraint(
            "max_bet_per_user > 0", name="ck_prediction_market_max_bet_per_user"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prediction_market_status"),
        "prediction_market",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_market_betting_deadline"),
        "prediction_market",
        ["betting_deadline"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_market_created_at"),
        "prediction_market",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "prediction_bet",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("market_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("option", sa.SmallInteger(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("option IN (0,1)", name="ck_prediction_bet_option"),
        sa.CheckConstraint("amount > 0", name="ck_prediction_bet_amount_gt_0"),
        sa.ForeignKeyConstraint(["market_id"], ["prediction_market.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prediction_bet_market_id"),
        "prediction_bet",
        ["market_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_bet_tg_id"), "prediction_bet", ["tg_id"], unique=False
    )
    op.create_index(
        op.f("ix_prediction_bet_created_at"),
        "prediction_bet",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_prediction_bet_market_user",
        "prediction_bet",
        ["market_id", "tg_id"],
        unique=False,
    )
    op.create_index(
        "idx_prediction_bet_market_option",
        "prediction_bet",
        ["market_id", "option"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_prediction_bet_market_option", table_name="prediction_bet")
    op.drop_index("idx_prediction_bet_market_user", table_name="prediction_bet")
    op.drop_index(op.f("ix_prediction_bet_created_at"), table_name="prediction_bet")
    op.drop_index(op.f("ix_prediction_bet_tg_id"), table_name="prediction_bet")
    op.drop_index(op.f("ix_prediction_bet_market_id"), table_name="prediction_bet")
    op.drop_table("prediction_bet")

    op.drop_index(
        op.f("ix_prediction_market_created_at"), table_name="prediction_market"
    )
    op.drop_index(
        op.f("ix_prediction_market_betting_deadline"), table_name="prediction_market"
    )
    op.drop_index(op.f("ix_prediction_market_status"), table_name="prediction_market")
    op.drop_table("prediction_market")
