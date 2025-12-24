"""add_traffic_log_fields

Revision ID: m3n4o5p6q7r8
Revises: 2cbae36f6f13
Create Date: 2025-12-24 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, None] = "2cbae36f6f13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add request_uri, upstream, and upstream_response_time columns to line_traffic_stats table
    op.add_column(
        "line_traffic_stats", sa.Column("request_uri", sa.Text(), nullable=True)
    )
    op.add_column("line_traffic_stats", sa.Column("upstream", sa.Text(), nullable=True))
    op.add_column(
        "line_traffic_stats",
        sa.Column("upstream_response_time", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # Remove the newly added columns from line_traffic_stats table
    op.drop_column("line_traffic_stats", "upstream_response_time")
    op.drop_column("line_traffic_stats", "upstream")
    op.drop_column("line_traffic_stats", "request_uri")
