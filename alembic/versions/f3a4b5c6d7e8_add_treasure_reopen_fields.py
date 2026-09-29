"""add treasure automatic reopen fields

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("treasure_issue") as batch:
        batch.add_column(sa.Column("auto_reopen_due_at", sa.BIGINT(), nullable=True))
        batch.add_column(sa.Column("auto_reopen_issue_id", sa.BIGINT(), nullable=True))
        batch.create_index(
            "ix_treasure_issue_reopen_due",
            ["auto_reopen_due_at", "auto_reopen_issue_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("treasure_issue") as batch:
        batch.drop_index("ix_treasure_issue_reopen_due")
        batch.drop_column("auto_reopen_issue_id")
        batch.drop_column("auto_reopen_due_at")
