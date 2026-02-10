"""add offline status to custom_lines

Revision ID: n5o6p7q8r9s0
Revises: a1b2c3d4e5f6
Create Date: 2026-02-10 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n5o6p7q8r9s0"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old check constraint
    op.drop_constraint("ck_custom_line_status", "custom_lines", type_="check")

    # Create the new check constraint with 'offline' status
    op.create_check_constraint(
        "ck_custom_line_status",
        "custom_lines",
        "status IN ('pending', 'approved', 'rejected', 'expired', 'offline')",
    )


def downgrade() -> None:
    # Drop the new check constraint
    op.drop_constraint("ck_custom_line_status", "custom_lines", type_="check")

    # Recreate the old check constraint without 'offline' status
    op.create_check_constraint(
        "ck_custom_line_status",
        "custom_lines",
        "status IN ('pending', 'approved', 'rejected', 'expired')",
    )
