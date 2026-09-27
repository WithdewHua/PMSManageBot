"""add immutable free-spin consumption snapshots

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4

Existing free-spin rows retain their historical source. Their consumption
parameters are backfilled to the behavior that the pre-snapshot code used.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | None = "b9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("luckywheel_free_spins") as batch:
        batch.add_column(
            sa.Column(
                "cost_credits_snapshot",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "wheel_stats_source",
                sa.Text(),
                nullable=False,
                server_default="blackjack_free",
            )
        )
        batch.create_check_constraint(
            "ck_luckywheel_free_spins_cost_snapshot_nonnegative",
            "cost_credits_snapshot >= 0",
        )

    op.execute(
        sa.text(
            """
            UPDATE luckywheel_free_spins
            SET wheel_stats_source = CASE
                WHEN source = 'gift_pack' THEN 'gift_pack_free'
                ELSE 'blackjack_free'
            END,
            cost_credits_snapshot = 0
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("luckywheel_free_spins") as batch:
        batch.drop_constraint(
            "ck_luckywheel_free_spins_cost_snapshot_nonnegative", type_="check"
        )
        batch.drop_column("wheel_stats_source")
        batch.drop_column("cost_credits_snapshot")
