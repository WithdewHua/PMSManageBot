"""remove_is_default_from_line_schedule

Revision ID: 170b75a69044
Revises: g7h8i9j0k1l2
Create Date: 2025-12-08 02:38:10.701882

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "170b75a69044"
down_revision: Union[str, None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Get connection to check if objects exist
    conn = op.get_bind()
    inspector = inspect(conn)

    # Drop index on is_default (if exists)
    indexes = [idx["name"] for idx in inspector.get_indexes("line_schedule")]
    if "idx_schedule_user_service_default" in indexes:
        op.drop_index("idx_schedule_user_service_default", table_name="line_schedule")

    # Drop check constraint on is_default (if exists)
    # PostgreSQL stores check constraints, we'll use execute to check
    conn.execute(
        sa.text("""
        DO $$ 
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname = 'ck_schedule_is_default'
            ) THEN
                ALTER TABLE line_schedule DROP CONSTRAINT ck_schedule_is_default;
            END IF;
        END $$;
    """)
    )

    # Drop is_default column (if exists)
    columns = [col["name"] for col in inspector.get_columns("line_schedule")]
    if "is_default" in columns:
        op.drop_column("line_schedule", "is_default")


def downgrade() -> None:
    # Add back is_default column
    op.add_column(
        "line_schedule",
        sa.Column("is_default", sa.SMALLINT(), nullable=False, server_default="0"),
    )

    # Add back check constraint
    op.create_check_constraint(
        "ck_schedule_is_default",
        "line_schedule",
        "is_default IN (0, 1)",
    )

    # Add back index
    op.create_index(
        "idx_schedule_user_service_default",
        "line_schedule",
        ["tg_id", "service", "is_default"],
        unique=False,
    )
