"""add plex_id and emby_id to invitation

Revision ID: u1v2w3x4y5z6
Revises: t7u8v9w0x1y2
Create Date: 2026-03-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "u1v2w3x4y5z6"
down_revision: Union[str, None] = "t7u8v9w0x1y2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add plex_id column to invitation table
    # Stores the Plex user ID after the invitation code is redeemed for Plex
    op.add_column(
        "invitation",
        sa.Column("plex_id", sa.BIGINT(), nullable=True),
    )
    # Add emby_id column to invitation table
    # Stores the Emby user ID after the invitation code is redeemed for Emby
    op.add_column(
        "invitation",
        sa.Column("emby_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invitation", "emby_id")
    op.drop_column("invitation", "plex_id")
