"""add event hash to line traffic stats

Revision ID: h1i2j3k4l5m6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-22 20:55:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "line_traffic_stats",
        sa.Column("event_hash", sa.Text(), nullable=True),
    )

    op.execute(
        """
        UPDATE line_traffic_stats
        SET event_hash = lower(hex(randomblob(16)))
        WHERE event_hash IS NULL OR event_hash = ''
        """
    )

    op.alter_column("line_traffic_stats", "event_hash", nullable=False)
    op.create_unique_constraint(
        "uq_line_traffic_event_hash", "line_traffic_stats", ["event_hash"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_line_traffic_event_hash", "line_traffic_stats", type_="unique"
    )
    op.drop_column("line_traffic_stats", "event_hash")
