"""add ON UPDATE CASCADE to statistics.tg_id foreign keys

换绑用户 tg_id 时需要更新 statistics 表的主键，所有引用 statistics.tg_id 的
外键改为 ON UPDATE CASCADE，使子表自动跟随主键变化（ON DELETE 保持 NO ACTION，
避免误删子表数据）。

Revision ID: i7j8k9l0m1n2
Revises: h1i2j3k4l5m6
Create Date: 2026-06-14

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i7j8k9l0m1n2"
down_revision: Union[str, None] = "h1i2j3k4l5m6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 动态重建所有引用 statistics.tg_id 的外键为 ON UPDATE CASCADE。
    # 不依赖固定约束名，幂等（已是 CASCADE 的会被跳过）。
    op.execute(
        """
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN
                SELECT con.conname,
                       rel.relname  AS table_name,
                       att.attname  AS column_name
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_attribute att
                  ON att.attrelid = con.conrelid
                 AND att.attnum = con.conkey[1]
                WHERE con.contype = 'f'
                  AND con.confrelid = 'statistics'::regclass
                  AND con.confupdtype <> 'c'
            LOOP
                EXECUTE format(
                    'ALTER TABLE %I DROP CONSTRAINT %I',
                    r.table_name, r.conname
                );
                EXECUTE format(
                    'ALTER TABLE %I ADD CONSTRAINT %I '
                    'FOREIGN KEY (%I) REFERENCES statistics(tg_id) ON UPDATE CASCADE',
                    r.table_name, r.conname, r.column_name
                );
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # 还原为默认 ON UPDATE NO ACTION。
    op.execute(
        """
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN
                SELECT con.conname,
                       rel.relname  AS table_name,
                       att.attname  AS column_name
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_attribute att
                  ON att.attrelid = con.conrelid
                 AND att.attnum = con.conkey[1]
                WHERE con.contype = 'f'
                  AND con.confrelid = 'statistics'::regclass
                  AND con.confupdtype = 'c'
            LOOP
                EXECUTE format(
                    'ALTER TABLE %I DROP CONSTRAINT %I',
                    r.table_name, r.conname
                );
                EXECUTE format(
                    'ALTER TABLE %I ADD CONSTRAINT %I '
                    'FOREIGN KEY (%I) REFERENCES statistics(tg_id)',
                    r.table_name, r.conname, r.column_name
                );
            END LOOP;
        END $$;
        """
    )
