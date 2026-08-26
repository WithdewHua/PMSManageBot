"""add blackjack tournament tables

Revision ID: a7b8c9d0e1f2
Revises: z6a7b8c9d0e1
Create Date: 2026-08-24 14:10:00.000000

21 点锦标赛的两张新表，外加为既有 `blackjack_hand.tournament_id` 补一个索引。

`tournament_id` 列本身在 21 点上线时就已预留（可空、无外键、无索引），故本次
**不改既有表结构、不写数据迁移**——当初留那一列的收益在此兑现。索引支撑两类
查询：赛事清场（结算一场赛事的全部在局手牌）与赛内手牌的归属查询。

奖池金额有意不落列：`entrant_count × buy_in_credits + seeded_prize_credits`
恒等于真值，累加列会引入「报名成功但累加失败 / 退款后忘记回退 / 并发累加丢失」
一整类漂移 bug。

`blackjack_tournament_entry` 的 `UNIQUE(tournament_id, tg_id)` 是重复报名的唯一
防线：名额占位的条件 UPDATE 与该约束在同一事务内，插入撞约束时整个事务回滚、
计数增量随之回退，不需要补偿性减一。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "z6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "blackjack_tournament",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # 1=报名中 2=进行中 3=已结算 4=已取消
        sa.Column("status", sa.SMALLINT(), nullable=False, server_default="1"),
        # 报名与筹码
        sa.Column("buy_in_credits", sa.Integer(), nullable=False),
        sa.Column("starting_chips", sa.Integer(), nullable=False),
        sa.Column("total_hands", sa.Integer(), nullable=False),
        sa.Column("min_bet_chips", sa.Integer(), nullable=False),
        sa.Column("max_bet_chips", sa.Integer(), nullable=False),
        sa.Column("bet_step_chips", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("min_entrants", sa.Integer(), nullable=False),
        sa.Column("max_entrants", sa.Integer(), nullable=False),
        sa.Column("entrant_count", sa.Integer(), nullable=False, server_default="0"),
        # 奖池
        sa.Column("rake_bp", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column(
            "seeded_prize_credits", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "payout_structure",
            sa.Text(),
            nullable=False,
            server_default="[50, 30, 20]",
        ),
        # 参数快照（创建时生效的全局配置）
        sa.Column(
            "dealer_hits_soft_17", sa.SMALLINT(), nullable=False, server_default="0"
        ),
        sa.Column("blackjack_payout", sa.Float(), nullable=False, server_default="1.5"),
        sa.Column(
            "surrender_enabled", sa.SMALLINT(), nullable=False, server_default="1"
        ),
        sa.Column(
            "hand_timeout_minutes", sa.Integer(), nullable=False, server_default="15"
        ),
        sa.Column("register_deadline_ms", sa.BIGINT(), nullable=False),
        sa.Column("play_deadline_ms", sa.BIGINT(), nullable=False),
        # 完赛提醒的去重标记
        sa.Column("reminder_sent_at", sa.BIGINT(), nullable=True),
        sa.Column("created_by", sa.BIGINT(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("settled_at", sa.BIGINT(), nullable=True),
        sa.CheckConstraint(
            "status IN (1,2,3,4)", name="ck_blackjack_tournament_status"
        ),
        sa.CheckConstraint(
            "buy_in_credits > 0", name="ck_blackjack_tournament_buy_in_gt_0"
        ),
        sa.CheckConstraint(
            "starting_chips > 0", name="ck_blackjack_tournament_chips_gt_0"
        ),
        sa.CheckConstraint(
            "total_hands > 0", name="ck_blackjack_tournament_hands_gt_0"
        ),
        sa.CheckConstraint(
            "bet_step_chips > 0", name="ck_blackjack_tournament_bet_step_gt_0"
        ),
        sa.CheckConstraint(
            "min_bet_chips > 0 AND min_bet_chips <= max_bet_chips",
            name="ck_blackjack_tournament_bet_range",
        ),
        sa.CheckConstraint(
            "min_entrants > 0 AND min_entrants <= max_entrants",
            name="ck_blackjack_tournament_entrant_range",
        ),
        sa.CheckConstraint(
            "entrant_count >= 0 AND entrant_count <= max_entrants",
            name="ck_blackjack_tournament_entrant_count",
        ),
        sa.CheckConstraint(
            "rake_bp >= 0 AND rake_bp <= 10000", name="ck_blackjack_tournament_rake_bp"
        ),
        sa.CheckConstraint(
            "seeded_prize_credits >= 0", name="ck_blackjack_tournament_seed_nonneg"
        ),
        sa.CheckConstraint(
            "surrender_enabled IN (0,1)",
            name="ck_blackjack_tournament_surrender_enabled",
        ),
        sa.CheckConstraint(
            "dealer_hits_soft_17 IN (0,1)", name="ck_blackjack_tournament_dealer_h17"
        ),
        sa.CheckConstraint(
            "hand_timeout_minutes > 0", name="ck_blackjack_tournament_timeout_gt_0"
        ),
        sa.CheckConstraint(
            "register_deadline_ms <= play_deadline_ms",
            name="ck_blackjack_tournament_deadline_order",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_blackjack_tournament_created_at",
        "blackjack_tournament",
        ["created_at"],
    )
    # tick 任务按 (status, 各截止时点) 扫待处理的赛事
    op.create_index(
        "idx_blackjack_tournament_status_reg",
        "blackjack_tournament",
        ["status", "register_deadline_ms"],
    )
    op.create_index(
        "idx_blackjack_tournament_status_play",
        "blackjack_tournament",
        ["status", "play_deadline_ms"],
    )

    op.create_table(
        "blackjack_tournament_entry",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("tournament_id", sa.BIGINT(), nullable=False),
        sa.Column("tg_id", sa.BIGINT(), nullable=False),
        sa.Column("chips", sa.Integer(), nullable=False),
        sa.Column("hands_played", sa.Integer(), nullable=False, server_default="0"),
        # 1=进行中 2=已打完 3=已淘汰；只有 2、3 具备派奖资格
        sa.Column("status", sa.SMALLINT(), nullable=False, server_default="1"),
        sa.Column("final_rank", sa.Integer(), nullable=True),
        sa.Column("prize_credits", sa.Float(), nullable=True),
        sa.Column("registered_at_ms", sa.BIGINT(), nullable=False),
        sa.CheckConstraint(
            "status IN (1,2,3)", name="ck_blackjack_tournament_entry_status"
        ),
        sa.CheckConstraint(
            "chips >= 0", name="ck_blackjack_tournament_entry_chips_nonneg"
        ),
        sa.CheckConstraint(
            "hands_played >= 0", name="ck_blackjack_tournament_entry_hands_nonneg"
        ),
        sa.CheckConstraint(
            "prize_credits IS NULL OR prize_credits >= 0",
            name="ck_blackjack_tournament_entry_prize_nonneg",
        ),
        sa.ForeignKeyConstraint(["tournament_id"], ["blackjack_tournament.id"]),
        sa.ForeignKeyConstraint(["tg_id"], ["statistics.tg_id"], onupdate="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tournament_id", "tg_id", name="uq_blackjack_tournament_entry"
        ),
    )
    op.create_index(
        "ix_blackjack_tournament_entry_tournament_id",
        "blackjack_tournament_entry",
        ["tournament_id"],
    )
    op.create_index(
        "ix_blackjack_tournament_entry_tg_id",
        "blackjack_tournament_entry",
        ["tg_id"],
    )
    # 排名（按 chips 降序）与「找某用户在某赛事的报名」
    op.create_index(
        "idx_blackjack_tournament_entry_rank",
        "blackjack_tournament_entry",
        ["tournament_id", "chips"],
    )

    # 赛事清场与赛内手牌归属查询。列早已存在，此处只补索引
    op.create_index(
        "idx_blackjack_hand_tournament",
        "blackjack_hand",
        ["tournament_id", "tg_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_blackjack_hand_tournament", table_name="blackjack_hand")

    op.drop_index(
        "idx_blackjack_tournament_entry_rank", table_name="blackjack_tournament_entry"
    )
    op.drop_index(
        "ix_blackjack_tournament_entry_tg_id", table_name="blackjack_tournament_entry"
    )
    op.drop_index(
        "ix_blackjack_tournament_entry_tournament_id",
        table_name="blackjack_tournament_entry",
    )
    op.drop_table("blackjack_tournament_entry")

    op.drop_index(
        "idx_blackjack_tournament_status_play", table_name="blackjack_tournament"
    )
    op.drop_index(
        "idx_blackjack_tournament_status_reg", table_name="blackjack_tournament"
    )
    op.drop_index(
        "ix_blackjack_tournament_created_at", table_name="blackjack_tournament"
    )
    op.drop_table("blackjack_tournament")
