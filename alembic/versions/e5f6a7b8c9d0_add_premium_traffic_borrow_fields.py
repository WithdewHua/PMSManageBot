"""add premium traffic debt fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plex_user",
        sa.Column("premium_status_updated_at", sa.BIGINT(), nullable=True),
    )
    op.add_column(
        "plex_user",
        sa.Column(
            "premium_traffic_debt_bytes",
            sa.BIGINT(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "plex_user",
        sa.Column("premium_traffic_debt_updated_date", sa.String(), nullable=True),
    )
    op.add_column(
        "emby_user",
        sa.Column("premium_status_updated_at", sa.BIGINT(), nullable=True),
    )
    op.add_column(
        "emby_user",
        sa.Column(
            "premium_traffic_debt_bytes",
            sa.BIGINT(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "emby_user",
        sa.Column("premium_traffic_debt_updated_date", sa.String(), nullable=True),
    )

    with op.batch_alter_table("plex_user") as batch_op:
        batch_op.alter_column("premium_traffic_debt_bytes", server_default=None)

    with op.batch_alter_table("emby_user") as batch_op:
        batch_op.alter_column("premium_traffic_debt_bytes", server_default=None)


def downgrade() -> None:
    op.drop_column("emby_user", "premium_traffic_debt_updated_date")
    op.drop_column("emby_user", "premium_traffic_debt_bytes")
    op.drop_column("emby_user", "premium_status_updated_at")
    op.drop_column("plex_user", "premium_traffic_debt_updated_date")
    op.drop_column("plex_user", "premium_traffic_debt_bytes")
    op.drop_column("plex_user", "premium_status_updated_at")
