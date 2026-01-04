#!/usr/bin/env python3
"""
修复 PostgreSQL 表的序列问题
当出现 "duplicate key value violates unique constraint" 错误时，
这通常意味着序列值与表中的实际最大 ID 不同步

使用方法：
    python scripts/fix_postgres_sequence.py                 # 自动检测并修复所有有 id 列的表（默认）
    python scripts/fix_postgres_sequence.py table_name      # 修复指定表
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.log import logger
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as sqlalchemy_inspect


def fix_table_sequence(table_name: str, engine):
    """修复指定表的主键序列"""
    try:
        with engine.connect() as conn:
            # 查询当前表中最大的 ID
            result = conn.execute(text(f"SELECT MAX(id) FROM {table_name}"))
            max_id = result.scalar()

            if max_id is None:
                logger.info(f"{table_name} 表为空，无需修复序列")
                return True

            logger.info(f"当前 {table_name} 表中最大 ID: {max_id}")

            # 重置序列值为最大 ID + 1
            conn.execute(text(f"SELECT setval('{table_name}_id_seq', {max_id}, true)"))
            conn.commit()

            logger.info(f"已将 {table_name}_id_seq 序列重置为 {max_id}")

            # 验证序列当前值
            result = conn.execute(text(f"SELECT last_value FROM {table_name}_id_seq"))
            current_seq = result.scalar()
            logger.info(f"当前序列值: {current_seq}")

            print(f"✓ {table_name} 序列修复成功")
            return True

    except Exception as e:
        logger.error(f"修复 {table_name} 序列失败: {e}")
        print(f"✗ 修复 {table_name} 失败: {e}")
        return False


def get_tables_with_id_column(engine):
    """获取所有包含 id 列的表"""
    inspector = sqlalchemy_inspect(engine)
    tables_with_id = []

    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        for column in columns:
            if column["name"] == "id" and column.get("autoincrement", False):
                tables_with_id.append(table_name)
                break

    return tables_with_id


def fix_all_sequences(engine):
    """自动检测并修复所有包含 id 列的表的序列"""
    print("\n" + "=" * 60)
    print("正在检测数据库中包含 id 列的表...")
    print("=" * 60)

    tables = get_tables_with_id_column(engine)

    if not tables:
        print("未找到包含 id 列的表")
        return True

    print(f"找到 {len(tables)} 个表需要检查序列：")
    for table in tables:
        print(f"  - {table}")
    print("=" * 60)

    success_count = 0
    fail_count = 0

    for table in tables:
        if fix_table_sequence(table, engine):
            success_count += 1
        else:
            fail_count += 1
        print("-" * 60)

    print("=" * 60)
    print(f"成功修复: {success_count} 个表")
    print(f"失败: {fail_count} 个表")
    print("=" * 60)

    return fail_count == 0


if __name__ == "__main__":
    if settings.DATABASE_TYPE != "postgresql":
        print(f"当前数据库类型为 {settings.DATABASE_TYPE}，此脚本仅支持 PostgreSQL")
        sys.exit(1)

    engine = create_engine(settings.DB_URL)

    # 检查命令行参数
    if len(sys.argv) > 1:
        # 修复指定表
        table_name = sys.argv[1]
        print(f"\n正在修复表: {table_name}")
        success = fix_table_sequence(table_name, engine)
        sys.exit(0 if success else 1)
    else:
        # 默认自动检测并修复所有有 id 列的表
        success = fix_all_sequences(engine)
        sys.exit(0 if success else 1)
