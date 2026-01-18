"""add download sync unlock fields

Revision ID: a1b2c3d4e5f6
Revises: m3n4o5p6q7r8
Create Date: 2026-01-18 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add sync_unlocked and sync_unlock_time to plex_user table
    op.add_column(
        "plex_user",
        sa.Column("sync_unlocked", sa.SMALLINT(), nullable=False, server_default="0"),
    )
    op.add_column(
        "plex_user",
        sa.Column("sync_unlock_time", sa.BIGINT(), nullable=True),
    )

    # Add download_unlocked and download_unlock_time to emby_user table
    op.add_column(
        "emby_user",
        sa.Column(
            "download_unlocked", sa.SMALLINT(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "emby_user",
        sa.Column("download_unlock_time", sa.BIGINT(), nullable=True),
    )


def downgrade() -> None:
    # Remove columns from emby_user table
    op.drop_column("emby_user", "download_unlock_time")
    op.drop_column("emby_user", "download_unlocked")

    # Remove columns from plex_user table
    op.drop_column("plex_user", "sync_unlock_time")
    op.drop_column("plex_user", "sync_unlocked")
