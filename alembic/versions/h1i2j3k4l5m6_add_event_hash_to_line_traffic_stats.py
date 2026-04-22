"""add event hash to line traffic stats

Revision ID: h1i2j3k4l5m6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-22 20:55:00.000000

"""

import uuid
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

    connection = op.get_bind()
    line_traffic_stats = sa.table(
        "line_traffic_stats",
        sa.column("id", sa.Integer),
        sa.column("event_hash", sa.Text),
    )

    rows = connection.execute(
        sa.select(line_traffic_stats.c.id).where(
            sa.or_(
                line_traffic_stats.c.event_hash.is_(None),
                line_traffic_stats.c.event_hash == "",
            )
        )
    ).fetchall()

    for row in rows:
        connection.execute(
            line_traffic_stats.update()
            .where(line_traffic_stats.c.id == row.id)
            .values(event_hash=uuid.uuid4().hex)
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
