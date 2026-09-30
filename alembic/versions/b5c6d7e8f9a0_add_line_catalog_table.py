"""add line_catalog table

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f9a0"
down_revision: str | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "line_catalog",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("tags", sa.Text(), server_default="[]", nullable=False),
        sa.Column("free_open", sa.SMALLINT(), server_default="0", nullable=False),
        sa.Column("created_at", sa.BIGINT(), nullable=False),
        sa.Column("updated_at", sa.BIGINT(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('normal', 'premium')", name="ck_line_catalog_kind"
        ),
        sa.CheckConstraint("position >= 0", name="ck_line_catalog_position"),
        sa.CheckConstraint(
            "free_open IN (0, 1) AND (free_open = 0 OR kind = 'premium')",
            name="ck_line_catalog_free_open",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_line_catalog_name"),
        sa.UniqueConstraint("kind", "position", name="uq_line_catalog_kind_position"),
    )


def downgrade() -> None:
    op.drop_table("line_catalog")
