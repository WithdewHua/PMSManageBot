"""add expiry_notified_at to custom_lines

Revision ID: p1q2r3s4t5u6
Revises: n5o6p7q8r9s0
Create Date: 2026-03-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p1q2r3s4t5u6"
down_revision: str | None = "u1v2w3x4y5z6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 添加 expiry_notified_at 字段，用于记录最后一次发送即将过期提醒的时间戳
    op.add_column(
        "custom_lines",
        sa.Column("expiry_notified_at", sa.BIGINT(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("custom_lines", "expiry_notified_at")
