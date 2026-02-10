"""add custom line total traffic field

Revision ID: s1t2u3v4w5x6
Revises: n5o6p7q8r9s0
Create Date: 2026-02-10 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "s1t2u3v4w5x6"
down_revision: Union[str, None] = "n5o6p7q8r9s0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add total_traffic field to custom_lines table
    op.add_column("custom_lines", sa.Column("total_traffic", sa.Float(), nullable=True))
    # Add auto_offline_reason field to custom_lines table
    op.add_column(
        "custom_lines", sa.Column("auto_offline_reason", sa.String(), nullable=True)
    )


def downgrade() -> None:
    # Remove columns
    op.drop_column("custom_lines", "auto_offline_reason")
    op.drop_column("custom_lines", "total_traffic")
