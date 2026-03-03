"""add service to invitation

Revision ID: t7u8v9w0x1y2
Revises: s1t2u3v4w5x6
Create Date: 2026-03-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "t7u8v9w0x1y2"
down_revision: Union[str, None] = "s1t2u3v4w5x6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add service column to invitation table
    # Possible values: 'plex', 'emby'; NULL if not yet used
    op.add_column(
        "invitation",
        sa.Column("service", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invitation", "service")
