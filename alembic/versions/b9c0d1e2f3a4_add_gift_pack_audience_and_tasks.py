"""add gift pack audience, requirements and task reminder state

Revision ID: b9c0d1e2f3a4
Revises: 1eb9d9af29e8

Only additive columns and check constraints; legacy eligibility rows are not rewritten.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: str | None = "1eb9d9af29e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode rebuilds SQLite tables to install CHECK constraints; on PostgreSQL
    # Alembic emits ordinary ALTER TABLE statements.
    with op.batch_alter_table("gift_pack") as batch:
        batch.add_column(sa.Column("audience", sa.Text(), nullable=True))
        batch.add_column(sa.Column("requirements", sa.Text(), nullable=True))
        batch.add_column(sa.Column("task_end_at", sa.BIGINT(), nullable=True))
        batch.add_column(
            sa.Column(
                "max_task_prompt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "notify_audience_on_start",
                sa.SMALLINT(),
                nullable=False,
                server_default="0",
            )
        )
        batch.create_check_constraint(
            "ck_gift_pack_task_window",
            "task_end_at IS NULL OR (task_end_at > start_at AND task_end_at <= end_at)",
        )
        batch.create_check_constraint(
            "ck_gift_pack_max_task_prompt_count", "max_task_prompt_count >= 0"
        )
        batch.create_check_constraint(
            "ck_gift_pack_notify_audience_on_start",
            "notify_audience_on_start IN (0, 1)",
        )

    with op.batch_alter_table("gift_pack_user_state") as batch:
        batch.add_column(sa.Column("audience_locked_at", sa.BIGINT(), nullable=True))
        batch.add_column(
            sa.Column(
                "task_prompt_count", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch.add_column(sa.Column("last_task_prompted_at", sa.BIGINT(), nullable=True))
        batch.add_column(sa.Column("start_dm_sent_at", sa.BIGINT(), nullable=True))
        batch.create_check_constraint(
            "ck_gift_pack_state_task_prompt_count", "task_prompt_count >= 0"
        )


def downgrade() -> None:
    with op.batch_alter_table("gift_pack_user_state") as batch:
        batch.drop_constraint("ck_gift_pack_state_task_prompt_count", type_="check")
        batch.drop_column("start_dm_sent_at")
        batch.drop_column("last_task_prompted_at")
        batch.drop_column("task_prompt_count")
        batch.drop_column("audience_locked_at")

    with op.batch_alter_table("gift_pack") as batch:
        batch.drop_constraint("ck_gift_pack_notify_audience_on_start", type_="check")
        batch.drop_constraint("ck_gift_pack_max_task_prompt_count", type_="check")
        batch.drop_constraint("ck_gift_pack_task_window", type_="check")
        batch.drop_column("notify_audience_on_start")
        batch.drop_column("max_task_prompt_count")
        batch.drop_column("task_end_at")
        batch.drop_column("requirements")
        batch.drop_column("audience")
