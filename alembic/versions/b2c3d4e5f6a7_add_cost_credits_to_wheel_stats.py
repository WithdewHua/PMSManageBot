"""add_cost_credits_to_wheel_stats

Revision ID: b2c3d4e5f6a7
Revises: 9f3c2d1a4b5c
Create Date: 2026-03-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "9f3c2d1a4b5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wheel_stats",
        sa.Column(
            "cost_credits",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("wheel_stats", "cost_credits")
