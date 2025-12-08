"""add_last_viewed_at_to_plex_emby_users

Revision ID: 2cbae36f6f13
Revises: 170b75a69044
Create Date: 2025-12-08 17:49:11.151720

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2cbae36f6f13"
down_revision: Union[str, None] = "170b75a69044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add last_viewed_at column to plex_user table
    op.add_column("plex_user", sa.Column("last_viewed_at", sa.BIGINT(), nullable=True))

    # Add last_viewed_at column to emby_user table
    op.add_column("emby_user", sa.Column("last_viewed_at", sa.BIGINT(), nullable=True))


def downgrade() -> None:
    # Remove last_viewed_at column from emby_user table
    op.drop_column("emby_user", "last_viewed_at")

    # Remove last_viewed_at column from plex_user table
    op.drop_column("plex_user", "last_viewed_at")
