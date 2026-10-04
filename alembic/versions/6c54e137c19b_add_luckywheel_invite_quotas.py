"""Add luckywheel invite quota accounting (schema only).

Revision ID: 6c54e137c19b
Revises: b5c6d7e8f9a0

Current-week data is initialized separately after operator verification.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6c54e137c19b"
down_revision: str | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite needs INTEGER PRIMARY KEY for generated wheel-stat audit anchors.
    # Existing ID values and the PostgreSQL BIGINT schema are unchanged.
    if op.get_bind().dialect.name == "sqlite":
        columns = sa.inspect(op.get_bind()).get_columns("wheel_stats")
        id_type = next(column["type"] for column in columns if column["name"] == "id")
        if isinstance(id_type, sa.BigInteger):
            with op.batch_alter_table("wheel_stats") as batch:
                batch.alter_column(
                    "id",
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=False,
                )

    op.create_table(
        "wheel_invite_quota_week",
        sa.Column("week_start_ms", sa.BIGINT(), autoincrement=False, nullable=False),
        sa.Column("issued", sa.Integer(), nullable=False),
        sa.Column("initialized_at_ms", sa.BIGINT(), nullable=False),
        sa.Column("is_baseline", sa.Boolean(), nullable=False),
        sa.Column("baseline_digest", sa.Text(), nullable=True),
        sa.Column("baseline_cutoff_ms", sa.BIGINT(), nullable=True),
        sa.CheckConstraint("issued >= 0", name="ck_wheel_invite_quota_issued"),
        sa.PrimaryKeyConstraint("week_start_ms"),
    )
    op.create_table(
        "wheel_invite_audit",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("wheel_stats_id", sa.BIGINT(), nullable=False),
        sa.Column("week_start_ms", sa.BIGINT(), nullable=False),
        sa.Column("tg_id", sa.BIGINT(), nullable=False),
        sa.Column("issued", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("candidate_name", sa.Text(), nullable=False),
        sa.Column("final_name", sa.Text(), nullable=False),
        sa.Column("global_blocked", sa.Boolean(), nullable=False),
        sa.Column("personal_blocked", sa.Boolean(), nullable=False),
        sa.Column("global_limit", sa.Integer(), nullable=True),
        sa.Column("personal_limit", sa.Integer(), nullable=True),
        sa.Column("global_used_after", sa.Integer(), nullable=True),
        sa.Column("recorded_at_ms", sa.BIGINT(), nullable=False),
        sa.Column("historical", sa.Boolean(), nullable=False),
        sa.Column("privileged", sa.Boolean(), nullable=True),
        sa.CheckConstraint("issued IN (0, 1)", name="ck_wheel_invite_audit_issued"),
        sa.ForeignKeyConstraint(
            ["week_start_ms"], ["wheel_invite_quota_week.week_start_ms"]
        ),
        sa.ForeignKeyConstraint(["wheel_stats_id"], ["wheel_stats.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wheel_stats_id"),
    )
    op.create_index(
        "ix_wheel_invite_audit_week_user",
        "wheel_invite_audit",
        ["week_start_ms", "tg_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_wheel_invite_audit_week_user", table_name="wheel_invite_audit")
    op.drop_table("wheel_invite_audit")
    op.drop_table("wheel_invite_quota_week")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("wheel_stats") as batch:
            batch.alter_column(
                "id",
                existing_type=sa.Integer(),
                type_=sa.BigInteger(),
                existing_nullable=False,
            )
