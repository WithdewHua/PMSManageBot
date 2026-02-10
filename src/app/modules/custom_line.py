"""
自定义线路管理模块
"""

from datetime import datetime
from typing import List

from app.config import settings
from app.databases.session import get_session
from app.log import logger
from app.models.models import CustomLine
from app.utils.utils import send_message_by_url
from app.webapp.routers.admin import unbind_specified_line_for_all_users
from sqlalchemy import and_, select


async def check_expired_custom_lines():
    """
    检查即将过期和已过期的自定义线路

    功能：
    1. 检查即将在1天内过期的线路，发送提醒通知
    2. 处理已过期的线路：
       - 更新状态为 expired
       - 解绑所有使用该线路的用户
       - 发送过期通知给线路所有者
    """

    try:
        logger.info("开始检查即将过期和已过期的自定义线路")

        with get_session() as session:
            current_time = int(datetime.now().timestamp())
            # 1天后的时间戳（用于提前提醒）
            one_day_later = current_time + (24 * 60 * 60)

            # 1. 查询即将在1天内过期的线路（还未过期，但快到期了）
            expiring_soon_lines = await _get_expiring_soon_lines(
                session, current_time, one_day_later
            )

            # 发送即将过期的提醒通知
            if expiring_soon_lines:
                await _send_expiring_soon_notifications(
                    expiring_soon_lines, current_time
                )

            # 2. 查询已经过期的线路
            expired_lines = await _get_expired_lines(session, current_time)

            if not expired_lines:
                logger.info("没有需要下线的过期自定义线路")
            else:
                # 批量更新过期线路状态并解绑用户
                await _process_expired_lines(
                    session,
                    expired_lines,
                    current_time,
                    unbind_specified_line_for_all_users,
                )

                session.commit()
                logger.info(f"已将 {len(expired_lines)} 条过期自定义线路标记为已过期")

    except Exception as e:
        logger.error(f"检查过期自定义线路失败: {e}", exc_info=True)


async def _get_expiring_soon_lines(
    session, current_time: int, one_day_later: int
) -> List[CustomLine]:
    """获取即将在1天内过期的线路"""
    stmt_expiring_soon = select(CustomLine).where(
        and_(
            CustomLine.status == "approved",
            CustomLine.is_permanent == 0,
            CustomLine.expires_at.isnot(None),
            CustomLine.expires_at > current_time,  # 还没过期
            CustomLine.expires_at <= one_day_later,  # 但1天内会过期
        )
    )

    result = session.execute(stmt_expiring_soon)
    return result.scalars().all()


async def _get_expired_lines(session, current_time: int) -> List[CustomLine]:
    """获取已经过期的线路"""
    stmt_expired = select(CustomLine).where(
        and_(
            CustomLine.status == "approved",
            CustomLine.is_permanent == 0,
            CustomLine.expires_at.isnot(None),
            CustomLine.expires_at <= current_time,
        )
    )

    result = session.execute(stmt_expired)
    return result.scalars().all()


async def _send_expiring_soon_notifications(lines: List[CustomLine], current_time: int):
    """发送即将过期的提醒通知"""
    logger.info(f"找到 {len(lines)} 条即将过期的自定义线路")

    for line in lines:
        try:
            # 计算剩余时间（小时）
            remaining_hours = round((line.expires_at - current_time) / 3600, 1)
            expire_time_str = datetime.fromtimestamp(
                line.expires_at, tz=settings.TZ
            ).strftime("%Y-%m-%d %H:%M:%S")

            message = (
                f"⏰ 自定义线路即将过期提醒\n\n"
                f"域名：{line.domain}\n"
                f"网络情况：{line.network_info}\n"
                f"过期时间：{expire_time_str}\n"
                f"剩余时间：约 {remaining_hours} 小时\n\n"
                f"⚠️ 过期后线路将自动下线并解绑所有用户\n"
                f"请及时在个人中心续期以继续使用"
            )

            await send_message_by_url(
                chat_id=line.tg_id, text=message, disable_notification=False
            )

            logger.info(
                f"已发送即将过期提醒给用户 {line.tg_id}，线路域名：{line.domain}，剩余 {remaining_hours} 小时"
            )
        except Exception as e:
            logger.error(
                f"发送即将过期提醒失败 (用户 {line.tg_id}，线路 {line.domain}): {e}"
            )


async def _process_expired_lines(
    session, lines: List[CustomLine], current_time: int, unbind_func
):
    """处理已过期的线路"""
    for line in lines:
        # 将状态改为 expired
        line.status = "expired"
        line.updated_at = current_time

        # 解绑所有使用该线路的用户
        try:
            success, unbind_count = await unbind_func(line.domain, reason="已过期")
            if success and unbind_count > 0:
                logger.info(
                    f"自定义线路 {line.domain} 过期，已解绑 {unbind_count} 个用户"
                )
        except Exception as e:
            logger.error(f"解绑过期线路 {line.domain} 用户时失败: {e}")

        # 发送通知给提交用户
        try:
            message = (
                f"📢 自定义线路过期通知\n\n"
                f"您提交的自定义线路已过期：\n"
                f"域名：{line.domain}\n"
                f"网络情况：{line.network_info}\n\n"
                f"线路已自动下线并解绑所有用户\n"
                f"您可以在个人中心续期或删除该线路"
            )

            await send_message_by_url(
                chat_id=line.tg_id, text=message, disable_notification=False
            )

            logger.info(f"已发送过期通知给用户 {line.tg_id}，线路域名：{line.domain}")
        except Exception as e:
            logger.error(
                f"发送过期通知失败 (用户 {line.tg_id}，线路 {line.domain}): {e}"
            )
