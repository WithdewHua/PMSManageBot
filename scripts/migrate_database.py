#!/usr/bin/env python3
"""
从旧的 SQLite 数据库迁移到新的 ORM 系统
此脚本可以帮助你从现有的 data.db 迁移到新的数据库系统
"""

import sqlite3
import sys
from pathlib import Path

from app.config import settings
from app.databases.session import get_session, init_db
from app.log import logger
from app.models.models import (
    AuctionBids,
    Auctions,
    CryptoDonationOrders,
    DonationRegistrations,
    EmbyUser,
    Invitation,
    LineTrafficMonthlyStats,
    LineTrafficStats,
    Overseerr,
    PlexUser,
    Statistics,
    WheelStats,
)


def migrate_from_sqlite(old_db_path: Path):
    """
    从旧的 SQLite 数据库迁移数据

    Args:
        old_db_path: 旧数据库文件路径
    """
    if not old_db_path.exists():
        logger.error(f"Old database file not found: {old_db_path}")
        return False

    logger.info(f"Starting migration from {old_db_path}")

    # 连接到旧数据库
    old_conn = sqlite3.connect(old_db_path)
    old_cur = old_conn.cursor()

    # 迁移统计
    migration_stats = {
        "user": {"success": False, "count": 0},
        "emby_user": {"success": False, "count": 0},
        "invitation": {"success": False, "count": 0},
        "statistics": {"success": False, "count": 0},
        "overseerr": {"success": False, "count": 0},
        "wheel_stats": {"success": False, "count": 0},
        "auctions": {"success": False, "count": 0},
        "auction_bids": {"success": False, "count": 0},
        "line_traffic_stats": {"success": False, "count": 0},
        "line_traffic_monthly_stats": {"success": False, "count": 0},
        "donation_registrations": {"success": False, "count": 0},
        "crypto_donation_orders": {"success": False, "count": 0},
    }

    try:
        # 数据库表会在使用 get_session 时自动创建
        logger.info("Database tables will be auto-created if needed...")
        init_db()

        with get_session() as session:
            # 迁移 User 表
            logger.info("Migrating user table...")
            old_cur.execute("SELECT * FROM user")
            columns = [description[0] for description in old_cur.description]
            count = 0
            for row in old_cur.fetchall():
                user_data = dict(zip(columns, row))
                user = PlexUser(**user_data)
                session.add(user)
                count += 1
            migration_stats["user"] = {"success": True, "count": count}
            logger.info(f"User table migrated ({count} records)")

            # 迁移 EmbyUser 表
            logger.info("Migrating emby_user table...")
            old_cur.execute("SELECT * FROM emby_user")
            columns = [description[0] for description in old_cur.description]
            count = 0
            for row in old_cur.fetchall():
                row = [r if r != "" else None for r in row]
                emby_data = dict(zip(columns, row))
                emby_user = EmbyUser(**emby_data)
                session.add(emby_user)
                count += 1
            migration_stats["emby_user"] = {"success": True, "count": count}
            logger.info(f"Emby user table migrated ({count} records)")

            # 迁移 Invitation 表
            logger.info("Migrating invitation table...")
            old_cur.execute("SELECT * FROM invitation")
            columns = [description[0] for description in old_cur.description]
            count = 0
            for row in old_cur.fetchall():
                invitation_data = dict(zip(columns, row))
                invitation = Invitation(**invitation_data)
                session.add(invitation)
                count += 1
            migration_stats["invitation"] = {"success": True, "count": count}
            logger.info(f"Invitation table migrated ({count} records)")

            # 迁移 Statistics 表
            logger.info("Migrating statistics table...")
            old_cur.execute("SELECT * FROM statistics")
            columns = [description[0] for description in old_cur.description]
            count = 0
            for row in old_cur.fetchall():
                stats_data = dict(zip(columns, row))
                stats = Statistics(**stats_data)
                session.add(stats)
                count += 1
            migration_stats["statistics"] = {"success": True, "count": count}
            logger.info(f"Statistics table migrated ({count} records)")

            # 迁移 Overseerr 表
            try:
                logger.info("Migrating overseerr table...")
                old_cur.execute("SELECT * FROM overseerr")
                columns = [description[0] for description in old_cur.description]
                count = 0
                for row in old_cur.fetchall():
                    overseerr_data = dict(zip(columns, row))
                    overseerr = Overseerr(**overseerr_data)
                    session.add(overseerr)
                    count += 1
                migration_stats["overseerr"] = {"success": True, "count": count}
                logger.info(f"Overseerr table migrated ({count} records)")
            except sqlite3.OperationalError as e:
                migration_stats["overseerr"] = {
                    "success": False,
                    "count": 0,
                    "error": str(e),
                }
                logger.warning(f"Overseerr table migration skipped: {e}")

            # 迁移 WheelStats 表
            try:
                logger.info("Migrating wheel_stats table...")
                old_cur.execute("SELECT * FROM wheel_stats")
                columns = [description[0] for description in old_cur.description]
                count = 0
                for row in old_cur.fetchall():
                    wheel_data = dict(zip(columns, row))
                    wheel = WheelStats(**wheel_data)
                    session.add(wheel)
                    count += 1
                migration_stats["wheel_stats"] = {"success": True, "count": count}
                logger.info(f"WheelStats table migrated ({count} records)")
            except sqlite3.OperationalError as e:
                migration_stats["wheel_stats"] = {
                    "success": False,
                    "count": 0,
                    "error": str(e),
                }
                logger.warning(f"WheelStats table migration skipped: {e}")

            # 迁移 Auctions 表
            try:
                logger.info("Migrating auctions table...")
                old_cur.execute("SELECT * FROM auctions")
                columns = [description[0] for description in old_cur.description]
                count = 0
                for row in old_cur.fetchall():
                    auction_data = dict(zip(columns, row))
                    auction = Auctions(**auction_data)
                    session.add(auction)
                    count += 1
                migration_stats["auctions"] = {"success": True, "count": count}
                logger.info(f"Auctions table migrated ({count} records)")
            except sqlite3.OperationalError as e:
                migration_stats["auctions"] = {
                    "success": False,
                    "count": 0,
                    "error": str(e),
                }
                logger.warning(f"Auctions table migration skipped: {e}")

            # 迁移 AuctionBids 表
            try:
                logger.info("Migrating auction_bids table...")
                old_cur.execute("SELECT * FROM auction_bids")
                columns = [description[0] for description in old_cur.description]
                count = 0
                for row in old_cur.fetchall():
                    bid_data = dict(zip(columns, row))
                    bid = AuctionBids(**bid_data)
                    session.add(bid)
                    count += 1
                migration_stats["auction_bids"] = {"success": True, "count": count}
                logger.info(f"AuctionBids table migrated ({count} records)")
            except sqlite3.OperationalError as e:
                migration_stats["auction_bids"] = {
                    "success": False,
                    "count": 0,
                    "error": str(e),
                }
                logger.warning(f"AuctionBids table migration skipped: {e}")

            # 迁移 LineTrafficStats 表
            try:
                logger.info("Migrating line_traffic_stats table...")
                old_cur.execute("SELECT * FROM line_traffic_stats")
                columns = [description[0] for description in old_cur.description]
                count = 0
                for row in old_cur.fetchall():
                    traffic_data = dict(zip(columns, row))
                    traffic = LineTrafficStats(**traffic_data)
                    session.add(traffic)
                    count += 1
                    # 分批提交，避免大量数据时内存问题
                    if count % 1000 == 0:
                        # flush 将待处理的变更发送到数据库，但不提交事务
                        session.flush()
                        logger.info(f"  Migrated {count} traffic records...")
                migration_stats["line_traffic_stats"] = {
                    "success": True,
                    "count": count,
                }
                logger.info(f"LineTrafficStats table migrated ({count} records)")
            except sqlite3.OperationalError as e:
                migration_stats["line_traffic_stats"] = {
                    "success": False,
                    "count": 0,
                    "error": str(e),
                }
                logger.warning(f"LineTrafficStats table migration skipped: {e}")

            # 迁移 LineTrafficMonthlyStats 表
            try:
                logger.info("Migrating line_traffic_monthly_stats table...")
                old_cur.execute("SELECT * FROM line_traffic_monthly_stats")
                columns = [description[0] for description in old_cur.description]
                count = 0
                for row in old_cur.fetchall():
                    monthly_data = dict(zip(columns, row))
                    monthly = LineTrafficMonthlyStats(**monthly_data)
                    session.add(monthly)
                    count += 1
                migration_stats["line_traffic_monthly_stats"] = {
                    "success": True,
                    "count": count,
                }
                logger.info(f"LineTrafficMonthlyStats table migrated ({count} records)")
            except sqlite3.OperationalError as e:
                migration_stats["line_traffic_monthly_stats"] = {
                    "success": False,
                    "count": 0,
                    "error": str(e),
                }
                logger.warning(f"LineTrafficMonthlyStats table migration skipped: {e}")

            # 迁移 DonationRegistrations 表
            try:
                logger.info("Migrating donation_registrations table...")
                old_cur.execute("SELECT * FROM donation_registrations")
                columns = [description[0] for description in old_cur.description]
                count = 0
                for row in old_cur.fetchall():
                    donation_data = dict(zip(columns, row))
                    donation = DonationRegistrations(**donation_data)
                    session.add(donation)
                    count += 1
                migration_stats["donation_registrations"] = {
                    "success": True,
                    "count": count,
                }
                logger.info(f"DonationRegistrations table migrated ({count} records)")
            except sqlite3.OperationalError as e:
                migration_stats["donation_registrations"] = {
                    "success": False,
                    "count": 0,
                    "error": str(e),
                }
                logger.warning(f"DonationRegistrations table migration skipped: {e}")

            # 迁移 CryptoDonationOrders 表
            try:
                logger.info("Migrating crypto_donation_orders table...")
                old_cur.execute("SELECT * FROM crypto_donation_orders")
                columns = [description[0] for description in old_cur.description]
                count = 0
                for row in old_cur.fetchall():
                    crypto_data = dict(zip(columns, row))
                    crypto = CryptoDonationOrders(**crypto_data)
                    session.add(crypto)
                    count += 1
                migration_stats["crypto_donation_orders"] = {
                    "success": True,
                    "count": count,
                }
                logger.info(f"CryptoDonationOrders table migrated ({count} records)")
            except sqlite3.OperationalError as e:
                migration_stats["crypto_donation_orders"] = {
                    "success": False,
                    "count": 0,
                    "error": str(e),
                }
                logger.warning(f"CryptoDonationOrders table migration skipped: {e}")

        # 显示迁移总结
        logger.info("\n" + "=" * 60)
        logger.info("Migration Summary")
        logger.info("=" * 60)
        total_records = 0
        successful_tables = 0
        failed_tables = 0

        for table_name, stats in migration_stats.items():
            if stats["success"]:
                status = "✅ SUCCESS"
                successful_tables += 1
                total_records += stats["count"]
                logger.info(
                    f"{status:12} | {table_name:30} | {stats['count']:6} records"
                )
            else:
                status = "⚠️  SKIPPED"
                failed_tables += 1
                error = stats.get("error", "Table not found")
                logger.info(f"{status:12} | {table_name:30} | {error}")

        logger.info("=" * 60)
        logger.info(f"Tables migrated: {successful_tables}/{len(migration_stats)}")
        logger.info(f"Total records:   {total_records}")
        logger.info("=" * 60)

        logger.info("Migration completed successfully!")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        old_conn.close()


def main():
    """主函数"""
    # 默认从当前 SQLite 数据库迁移
    old_db_path = settings.DATA_PATH / "data.db"

    # 检查是否指定了其他数据库文件
    if len(sys.argv) > 1:
        old_db_path = Path(sys.argv[1])

    logger.info("=" * 60)
    logger.info("Database Migration Tool")
    logger.info("=" * 60)
    logger.info(f"Source database: {old_db_path}")
    logger.info(f"Target database type: {settings.DATABASE_TYPE}")
    logger.info(
        f"Target database URL: {settings.DB_URL.split('@')[-1] if '@' in settings.DB_URL else settings.DB_URL}"
    )
    logger.info("=" * 60)

    # 确认是否继续
    if (
        settings.DATABASE_TYPE == "sqlite"
        and old_db_path == settings.DATA_PATH / "data.db"
    ):
        logger.warning("Source and target are the same SQLite database!")
        logger.warning(
            "This operation is only needed when migrating to a different database."
        )
        response = input("Continue anyway? (yes/no): ")
        if response.lower() != "yes":
            logger.info("Migration cancelled")
            return 0

    response = input("Start migration? (yes/no): ")
    if response.lower() != "yes":
        logger.info("Migration cancelled")
        return 0

    # 执行迁移
    success = migrate_from_sqlite(old_db_path)

    if success:
        logger.info("=" * 60)
        logger.info("Migration completed successfully!")
        logger.info("Please verify the data in the new database.")
        logger.info("=" * 60)
        return 0
    else:
        logger.error("=" * 60)
        logger.error("Migration failed!")
        logger.error("Please check the logs above for details.")
        logger.error("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
