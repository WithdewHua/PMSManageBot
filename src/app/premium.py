"""
Premium 会员相关功能，包括检查过期状态和即将过期的用户。
"""

from datetime import datetime, timedelta

from app.cache import (
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
    plex_last_user_defined_line_cache,
    plex_user_defined_line_cache,
)
from app.config import settings
from app.db import DB
from app.log import logger
from app.utils import (
    get_user_name_from_tg_id,
    is_binded_premium_line,
    send_message_by_url,
)


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
                # 更新线路绑定
                line = user.get("line", "")
                # 绑定的非 Premium 线路不需要更新
                if not is_binded_premium_line(line):
                    logger.info(
                        f"用户 {user_name} ({user['username']}) 的 {user['service']} Premium 线路未绑定，跳过解绑"
                    )
                    await send_message_by_url(
                        user["tg_id"],
                        f"您的 {user['service']} Premium 已过期，到期时间为 {user['expiry_time']}。当前线路绑定线路为: {line}。请重新解锁 Premium 以继续使用高级功能。",
                    )
                    continue
                # 解绑 Premium 线路
                new_line = unbind_premium_line(
                    db, user["service"], user["username"], user["tg_id"]
                )

                # 发送通知消息
                message = f"您的 {user['service']} Premium 已过期，到期时间为 {user['expiry_time']}。已自动解绑 Premium 线路，当前线路为: {new_line}。请重新解锁 Premium 以继续使用高级功能。"
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


def update_premium_status(db: DB, tg_id: int, service: str, days: int = 30) -> datetime:
    """
    更新用户的 Premium 状态，延长 Premium 会员时间
    :param db: 数据库连接对象
    :param tg_id: 用户的 Telegram ID
    :param service: 服务类型（"plex" 或 "emby"）
    :param days: 延长的天数，默认为30天
    :return: 新的 Premium 到期时间
    """
    new_expiry = None
    # 检查用户是否绑定了对应服务
    if service == "plex":
        user_info = db.get_plex_info_by_tg_id(tg_id)
        if not user_info:
            raise NameError("请先绑定 Plex 账户")

        # 计算新的到期时间
        current_expiry = user_info[10]  # premium_expiry_time字段
        # 永久会员直接跳过
        if bool(user_info[9]) and not current_expiry:
            return None
        if current_expiry and datetime.fromisoformat(current_expiry).astimezone(
            settings.TZ
        ) > datetime.now(settings.TZ):
            # 如果当前还有Premium，从到期时间开始延长
            new_expiry = datetime.fromisoformat(current_expiry).astimezone(
                settings.TZ
            ) + timedelta(days=days)
        else:
            # 从现在开始计算
            new_expiry = datetime.now(settings.TZ) + timedelta(days=days)

        # 更新数据库 - 设置is_premium=1和到期时间
        db.cur.execute(
            "UPDATE user SET is_premium=1, premium_expiry_time=? WHERE tg_id=?",
            (new_expiry.isoformat(), tg_id),
        )

    elif service == "emby":
        user_info = db.get_emby_info_by_tg_id(tg_id)
        if not user_info:
            raise NameError("请先绑定 Emby 账户")

        # 计算新的到期时间
        current_expiry = user_info[9]  # premium_expiry_time字段
        # 永久会员直接跳过
        if bool(user_info[8]) and not current_expiry:
            return None
        if current_expiry and datetime.fromisoformat(str(current_expiry)).astimezone(
            settings.TZ
        ) > datetime.now(settings.TZ):
            # 如果当前还有Premium，从到期时间开始延长
            new_expiry = datetime.fromisoformat(str(current_expiry)).astimezone(
                settings.TZ
            ) + timedelta(days=days)
        else:
            # 从现在开始计算
            new_expiry = datetime.now(settings.TZ) + timedelta(days=days)

        # 更新数据库 - 设置is_premium=1和到期时间
        db.cur.execute(
            "UPDATE emby_user SET is_premium=1, premium_expiry_time=? WHERE tg_id=?",
            (new_expiry.isoformat(), tg_id),
        )
    return new_expiry


def unbind_premium_line(db: DB, service: str, username: str, tg_id: int):
    """
    解绑 Premium 线路
    :param service: 服务类型（"plex" 或 "emby"）
    :param username: 用户名
    """
    if service not in ["plex", "emby"]:
        raise ValueError("不支持的服务类型")
    if service == "plex":
        cache = plex_user_defined_line_cache
        last_cache = plex_last_user_defined_line_cache
        db_func = db.set_plex_line
    elif service == "emby":
        cache = emby_user_defined_line_cache
        last_cache = emby_last_user_defined_line_cache
        db_func = db.set_emby_line
    # 获取上一次绑定的非 premium 线路
    last_line = last_cache.get(str(username).lower())
    # 更新用户的 Emby 线路，last_line 为空则自动选择
    db_func(last_line, tg_id=tg_id)
    # 更新缓存
    if last_line:
        cache.put(str(username).lower(), last_line)
        last_cache.delete(str(username).lower())
    else:
        cache.delete(str(username).lower())

    return last_line or "AUTO"
