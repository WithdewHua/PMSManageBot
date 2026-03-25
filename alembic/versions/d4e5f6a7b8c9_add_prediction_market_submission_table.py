"""add prediction market submission table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-25 14:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prediction_market_submission",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("betting_deadline", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("submitter_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.BigInteger(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("market_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN (0,1,2)",
            name="ck_prediction_market_submission_status",
        ),
        sa.CheckConstraint(
            "betting_deadline > 0",
            name="ck_prediction_market_submission_deadline_gt_0",
        ),
        sa.ForeignKeyConstraint(["market_id"], ["prediction_market.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_prediction_market_submission_betting_deadline"),
        "prediction_market_submission",
        ["betting_deadline"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_market_submission_status"),
        "prediction_market_submission",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_market_submission_submitter_tg_id"),
        "prediction_market_submission",
        ["submitter_tg_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_market_submission_market_id"),
        "prediction_market_submission",
        ["market_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_market_submission_created_at"),
        "prediction_market_submission",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_prediction_market_submission_created_at"),
        table_name="prediction_market_submission",
    )
    op.drop_index(
        op.f("ix_prediction_market_submission_market_id"),
        table_name="prediction_market_submission",
    )
    op.drop_index(
        op.f("ix_prediction_market_submission_submitter_tg_id"),
        table_name="prediction_market_submission",
    )
    op.drop_index(
        op.f("ix_prediction_market_submission_status"),
        table_name="prediction_market_submission",
    )
    op.drop_index(
        op.f("ix_prediction_market_submission_betting_deadline"),
        table_name="prediction_market_submission",
    )
    op.drop_table("prediction_market_submission")
