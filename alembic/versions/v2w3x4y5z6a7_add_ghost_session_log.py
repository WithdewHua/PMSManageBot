"""add ghost_session_log table

Revision ID: v2w3x4y5z6a7
Revises: i7j8k9l0m1n2
Create Date: 2026-08-16 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v2w3x4y5z6a7"
down_revision: Union[str, None] = "i7j8k9l0m1n2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ghost_session_log",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("row_id", sa.BIGINT(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("friendly_name", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("rating_key", sa.Text(), nullable=True),
        sa.Column("started", sa.BIGINT(), nullable=False),
        sa.Column("stopped", sa.BIGINT(), nullable=False),
        sa.Column("play_date", sa.Text(), nullable=False),
        sa.Column("raw_seconds", sa.BIGINT(), nullable=False),
        sa.Column("media_seconds", sa.BIGINT(), nullable=True),
        sa.Column("percent_complete", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compensated_seconds", sa.BIGINT(), nullable=False),
        sa.Column("deleted", sa.SMALLINT(), nullable=False, server_default="0"),
        sa.Column("compensated", sa.SMALLINT(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.BIGINT(), nullable=False),
        sa.CheckConstraint("deleted IN (0, 1)", name="ck_ghost_session_deleted"),
        sa.CheckConstraint(
            "compensated IN (0, 1)", name="ck_ghost_session_compensated"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("row_id", name="uq_ghost_session_row_id"),
    )
    op.create_index(
        op.f("ix_ghost_session_log_user_id"), "ghost_session_log", ["user_id"]
    )
    op.create_index(
        op.f("ix_ghost_session_log_play_date"), "ghost_session_log", ["play_date"]
    )
    op.create_index(
        op.f("ix_ghost_session_log_created_at"), "ghost_session_log", ["created_at"]
    )
    op.create_index(
        "idx_ghost_session_user_date", "ghost_session_log", ["user_id", "play_date"]
    )
    op.create_index(
        "idx_ghost_session_pending", "ghost_session_log", ["compensated", "deleted"]
    )


def downgrade() -> None:
    op.drop_index("idx_ghost_session_pending", table_name="ghost_session_log")
    op.drop_index("idx_ghost_session_user_date", table_name="ghost_session_log")
    op.drop_index(
        op.f("ix_ghost_session_log_created_at"), table_name="ghost_session_log"
    )
    op.drop_index(
        op.f("ix_ghost_session_log_play_date"), table_name="ghost_session_log"
    )
    op.drop_index(op.f("ix_ghost_session_log_user_id"), table_name="ghost_session_log")
    op.drop_table("ghost_session_log")
