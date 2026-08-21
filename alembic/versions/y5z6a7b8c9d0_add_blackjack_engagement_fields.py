"""add blackjack engagement fields

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
Create Date: 2026-08-21 20:05:33.918204

为 21 点的吸引力设计补齐手牌列：

- jackpot_won        幸运奖池派彩，与 payout_credits 分别记账
- decisions_total    本手的决策次数
- decisions_correct  其中与基本策略一致的次数
- rake_waived        是否为当日免抽水的那一手
- rake_jackpot_bp    取代 rake_glory_bp：抽水不再注入荣耀奖池，改为供养幸运奖池

**不改写 x4y5z6a7b8c9**：21 点已部署至真实环境，该建表迁移已执行，表结构只能
用 ALTER 追加，不能靠重建建表迁移来变更。

用 batch_alter_table：新列要配 CheckConstraint，而 SQLite 不支持
ALTER TABLE ADD CONSTRAINT，需整表重建；PostgreSQL 上 batch 模式直接透传为普通
ALTER，无额外开销。重建会保留数据、外键与索引。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "y5z6a7b8c9d0"
down_revision: Union[str, None] = "x4y5z6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("blackjack_hand") as batch_op:
        batch_op.add_column(sa.Column("jackpot_won", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "decisions_total", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column(
                "decisions_correct", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column("rake_waived", sa.SMALLINT(), nullable=False, server_default="0")
        )
        # 抽水去向由荣耀奖池改为幸运奖池：重命名而非新增+删除，保住存量手牌的快照值
        batch_op.alter_column(
            "rake_glory_bp",
            new_column_name="rake_jackpot_bp",
            existing_type=sa.Integer(),
            existing_nullable=False,
            existing_server_default="120",
        )
        batch_op.create_check_constraint(
            "ck_blackjack_hand_decisions_total_nonneg", "decisions_total >= 0"
        )
        batch_op.create_check_constraint(
            "ck_blackjack_hand_decisions_correct_range",
            "decisions_correct >= 0 AND decisions_correct <= decisions_total",
        )
        batch_op.create_check_constraint(
            "ck_blackjack_hand_rake_waived", "rake_waived IN (0,1)"
        )
        batch_op.create_check_constraint(
            "ck_blackjack_hand_jackpot_won_nonneg",
            "jackpot_won IS NULL OR jackpot_won >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("blackjack_hand") as batch_op:
        batch_op.drop_constraint("ck_blackjack_hand_jackpot_won_nonneg", type_="check")
        batch_op.drop_constraint("ck_blackjack_hand_rake_waived", type_="check")
        batch_op.drop_constraint(
            "ck_blackjack_hand_decisions_correct_range", type_="check"
        )
        batch_op.drop_constraint(
            "ck_blackjack_hand_decisions_total_nonneg", type_="check"
        )
        batch_op.alter_column(
            "rake_jackpot_bp",
            new_column_name="rake_glory_bp",
            existing_type=sa.Integer(),
            existing_nullable=False,
            existing_server_default="120",
        )
        batch_op.drop_column("rake_waived")
        batch_op.drop_column("decisions_correct")
        batch_op.drop_column("decisions_total")
        batch_op.drop_column("jackpot_won")
