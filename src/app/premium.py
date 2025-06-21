"""
Premium 会员过期检查任务
"""

from datetime import datetime

from app.db import DB
from app.log import logger
from app.utils import get_user_name_from_tg_id, send_message_by_url


async def check_premium_expiry():
    """检查并更新 Premium 会员过期状态"""
    db = DB()
    try:
        logger.info("开始检查 Premium 会员过期状态")

        # 获取过期用户列表
        expired_users = db.get_expired_premium_users()

        if expired_users:
            logger.info(f"发现 {len(expired_users)} 个过期的 Premium 用户")

            # 批量更新过期状态
            updated_count = db.update_expired_premium_status()

            # 记录过期用户信息
            for user in expired_users:
                user_name = get_user_name_from_tg_id(user["tg_id"])
                logger.info(
                    f"用户 {user_name} ({user['username']}) 的 {user['service']} Premium 已过期 (原到期时间: {user['expiry_time']})"
                )
                # 发送通知消息
                message = f"您的 {user['service']} Premium 已过期，到期时间为 {user['expiry_time']}。"
                await send_message_by_url(user["tg_id"], message)

            logger.info(f"已更新 {updated_count} 个用户的 Premium 状态")
        else:
            logger.debug("未发现过期的 Premium 用户")

    except Exception as e:
        logger.error(f"检查 Premium 过期状态时出错: {str(e)}")
    finally:
        db.close()


async def check_premium_expiring_soon(days: int = 3):
    """检查即将过期的 Premium 用户并记录日志"""
    db = DB()
    try:
        logger.info(f"检查 {days} 天内即将过期的 Premium 用户")
        expiring_users = db.get_premium_users_expiring_soon(days)

        if expiring_users:
            logger.info(f"发现 {len(expiring_users)} 个即将过期的 Premium 用户")

            for user in expiring_users:
                user_name = get_user_name_from_tg_id(user["tg_id"])
                logger.info(
                    f"用户 {user_name} ({user['username']}) 的 {user['service']} Premium 将在 {user['days_remaining']} 天后过期 (到期时间: {user['expiry_time']})"
                )
                # 发送通知消息
                message = f"您的 {user['service']} Premium 将在 {user['days_remaining']} 天后过期，到期时间为 {user['expiry_time']}。"
                await send_message_by_url(user["tg_id"], message)
        else:
            logger.debug(f"未发现 {days} 天内即将过期的 Premium 用户")

    except Exception as e:
        logger.error(f"检查即将过期的 Premium 用户时出错: {str(e)}")
    finally:
        db.close()


def get_premium_statistics():
    """获取 Premium 用户统计信息"""
    db = DB()
    try:
        # 统计当前活跃的 Premium 用户
        current_time = datetime.now().isoformat()

        plex_premium_count = db.cur.execute(
            "SELECT COUNT(*) FROM user WHERE is_premium=1 AND (premium_expiry_time IS NULL OR premium_expiry_time > ?)",
            (current_time,),
        ).fetchone()[0]

        emby_premium_count = db.cur.execute(
            "SELECT COUNT(*) FROM emby_user WHERE is_premium=1 AND (premium_expiry_time IS NULL OR premium_expiry_time > ?)",
            (current_time,),
        ).fetchone()[0]

        # 统计今天过期的用户
        today_start = (
            datetime.now()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        today_end = (
            datetime.now()
            .replace(hour=23, minute=59, second=59, microsecond=999999)
            .isoformat()
        )

        plex_expired_today = db.cur.execute(
            "SELECT COUNT(*) FROM user WHERE premium_expiry_time >= ? AND premium_expiry_time <= ?",
            (today_start, today_end),
        ).fetchone()[0]

        emby_expired_today = db.cur.execute(
            "SELECT COUNT(*) FROM emby_user WHERE premium_expiry_time >= ? AND premium_expiry_time <= ?",
            (today_start, today_end),
        ).fetchone()[0]

        stats = {
            "active_plex_premium": plex_premium_count,
            "active_emby_premium": emby_premium_count,
            "total_active_premium": plex_premium_count + emby_premium_count,
            "expired_today": plex_expired_today + emby_expired_today,
        }

        logger.info(
            f"Premium 统计 - 活跃 Plex: {plex_premium_count}, 活跃 Emby: {emby_premium_count}, 今日过期: {stats['expired_today']}"
        )

        return stats

    except Exception as e:
        logger.error(f"获取 Premium 统计信息时出错: {str(e)}")
        return None
    finally:
        db.close()
