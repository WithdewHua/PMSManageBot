"""add blackjack surrender_enabled snapshot column

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2026-08-23 13:20:00.000000

为 21 点新增投降动作补一列参数快照：

- surrender_enabled  发牌时投降是否可用

`server_default="0"` 使存量手牌一律落到「发牌时投降不可用」，与其真实情况一致：
它们的决策评判继续走不含投降的策略表，历史准确率逐位不变。新发出的手牌按发牌
当时的配置写入。

用 batch_alter_table：新列要配 CheckConstraint，而 SQLite 不支持
ALTER TABLE ADD CONSTRAINT，需整表重建；PostgreSQL 上 batch 模式直接透传为普通
ALTER，无额外开销。重建会保留数据、外键与索引。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "z6a7b8c9d0e1"
down_revision: Union[str, None] = "y5z6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("blackjack_hand") as batch_op:
        batch_op.add_column(
            sa.Column(
                "surrender_enabled", sa.SMALLINT(), nullable=False, server_default="0"
            )
        )
        batch_op.create_check_constraint(
            "ck_blackjack_hand_surrender_enabled", "surrender_enabled IN (0,1)"
        )


def downgrade() -> None:
    with op.batch_alter_table("blackjack_hand") as batch_op:
        batch_op.drop_constraint("ck_blackjack_hand_surrender_enabled", type_="check")
        batch_op.drop_column("surrender_enabled")
