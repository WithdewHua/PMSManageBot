"""add blackjack retention mechanisms

Revision ID: 1eb9d9af29e8
Revises: a7b8c9d0e1f2
Create Date: 2026-09-08 02:01:53.499903

21 点留存三机制的数据层（openspec: add-blackjack-retention）：

- statistics.tournament_wallet_credits        争霸赛余额（周损失返还的发放去向）
- statistics.blackjack_lose_streak            连败计数（救济的判定依据）
- statistics.blackjack_hands_since_freespin   免费转盘机会的累计手数
- blackjack_hand.relief_credits               连败救济金额（逐手记账，可对账）
- blackjack_tournament_entry.wallet_paid_credits / credits_paid_credits
                                              报名费的支付拆分（退款按原路退回）
- wheel_stats.source                          转盘参与来源（paid / blackjack_free）
- 新表 blackjack_weekly_cashback               周返还结算行，UNIQUE 保证任务幂等
- 新表 luckywheel_free_spins                   免费转盘机会（含过期与使用留痕）

全部新列带 server_default：线上库非空，PostgreSQL 对有数据的表追加 NOT NULL
列时必须提供默认值，否则迁移在第一步就失败。默认值全部为「零值」，存量行
语义正确——老用户无余额、无计数、无拆分，参与记录默认视为付费。

注：自动生成时 SQLite 对比误报了 line_schedule.days_of_week 的 server_default
差异（create_all 建出的临时库与迁移链建出的表在表达式默认值上本就不一致），
与本次变更无关，已剔除。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1eb9d9af29e8"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blackjack_weekly_cashback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tg_id", sa.BIGINT(), nullable=False),
        sa.Column("week_start_ms", sa.BIGINT(), nullable=False),
        sa.Column("net_change", sa.Float(), nullable=False),
        sa.Column("cashback_credits", sa.Float(), nullable=False),
        sa.Column("created_at_ms", sa.BIGINT(), nullable=False),
        sa.ForeignKeyConstraint(["tg_id"], ["statistics.tg_id"], onupdate="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tg_id", "week_start_ms", name="uq_blackjack_weekly_cashback"
        ),
    )
    op.create_index(
        "idx_blackjack_weekly_cashback_week",
        "blackjack_weekly_cashback",
        ["week_start_ms"],
        unique=False,
    )

    op.create_table(
        "luckywheel_free_spins",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tg_id", sa.BIGINT(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("granted_at_ms", sa.BIGINT(), nullable=False),
        sa.Column("expires_at_ms", sa.BIGINT(), nullable=False),
        sa.Column("used_at_ms", sa.BIGINT(), nullable=True),
        sa.CheckConstraint(
            "expires_at_ms > granted_at_ms",
            name="ck_luckywheel_free_spins_expiry_after_grant",
        ),
        sa.ForeignKeyConstraint(["tg_id"], ["statistics.tg_id"], onupdate="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_luckywheel_free_spins_user",
        "luckywheel_free_spins",
        ["tg_id", "granted_at_ms"],
        unique=False,
    )
    op.create_index(
        "idx_luckywheel_free_spins_expiry",
        "luckywheel_free_spins",
        ["expires_at_ms"],
        unique=False,
    )

    # batch_alter_table：新列要配 CheckConstraint（blackjack_hand.relief_credits），
    # 而 SQLite 不支持 ALTER TABLE ADD CONSTRAINT，需整表重建；PostgreSQL 上
    # batch 模式直接透传为普通 ALTER，无额外开销。
    with op.batch_alter_table("blackjack_hand") as batch:
        batch.add_column(sa.Column("relief_credits", sa.Float(), nullable=True))
        batch.create_check_constraint(
            "ck_blackjack_hand_relief_nonneg",
            "relief_credits IS NULL OR relief_credits >= 0",
        )

    with op.batch_alter_table("blackjack_tournament_entry") as batch:
        batch.add_column(
            sa.Column(
                "wallet_paid_credits",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "credits_paid_credits",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )
        batch.create_check_constraint(
            "ck_blackjack_tournament_entry_paid_nonneg",
            "wallet_paid_credits >= 0 AND credits_paid_credits >= 0",
        )

    with op.batch_alter_table("statistics") as batch:
        batch.add_column(
            sa.Column(
                "tournament_wallet_credits",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "blackjack_lose_streak",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "blackjack_hands_since_freespin",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    with op.batch_alter_table("wheel_stats") as batch:
        batch.add_column(
            sa.Column("source", sa.Text(), nullable=True, server_default="paid")
        )


def downgrade() -> None:
    with op.batch_alter_table("wheel_stats") as batch:
        batch.drop_column("source")

    with op.batch_alter_table("statistics") as batch:
        batch.drop_column("blackjack_hands_since_freespin")
        batch.drop_column("blackjack_lose_streak")
        batch.drop_column("tournament_wallet_credits")

    with op.batch_alter_table("blackjack_tournament_entry") as batch:
        batch.drop_column("credits_paid_credits")
        batch.drop_column("wallet_paid_credits")

    with op.batch_alter_table("blackjack_hand") as batch:
        batch.drop_column("relief_credits")

    op.drop_index(
        "idx_luckywheel_free_spins_expiry", table_name="luckywheel_free_spins"
    )
    op.drop_index("idx_luckywheel_free_spins_user", table_name="luckywheel_free_spins")
    op.drop_table("luckywheel_free_spins")

    op.drop_index(
        "idx_blackjack_weekly_cashback_week", table_name="blackjack_weekly_cashback"
    )
    op.drop_table("blackjack_weekly_cashback")
