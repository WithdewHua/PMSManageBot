"""
Premium 会员相关功能,包括检查过期状态和即将过期的用户。
"""

from datetime import datetime, timedelta

from app.config import settings
from app.databases import db
from app.databases.cache import (
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
    plex_last_user_defined_line_cache,
    plex_user_defined_line_cache,
)
from app.databases.session import get_session
from app.log import logger
from app.models.models import EmbyUser, PlexUser
from app.utils.utils import (
    format_traffic_size,
    get_user_name_from_tg_id,
    is_binded_premium_line,
    send_message_by_url,
)
from sqlalchemy import update as sql_update


async def check_premium_expiry():
    """检查并更新 Premium 会员过期状态"""

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

                # 检查用户是否单独解锁了下载权限，如果没有则撤销
                download_status = db.check_download_unlock(
                    user["tg_id"], user["service"]
                )
                if not download_status.get("unlock_time"):
                    # 用户没有单独解锁下载权限，撤销媒体服务器的下载权限
                    try:
                        if user["service"] == "plex":
                            from app.modules.plex import Plex

                            plex = Plex()
                            plex_email = user.get("email")
                            if plex_email:
                                plex.update_sync_for_user(plex_email, allow_sync=False)
                                logger.info(f"已撤销用户 {user_name} 的 Plex 同步权限")
                        elif user["service"] == "emby":
                            from app.modules.emby import Emby

                            emby = Emby()
                            emby_id = user.get("emby_id")
                            if emby_id:
                                emby.update_download_permission_for_user(
                                    emby_id, allow_download=False
                                )
                                logger.info(f"已撤销用户 {user_name} 的 Emby 下载权限")
                    except Exception as e:
                        logger.warning(f"撤销用户 {user_name} 的下载权限失败: {e}")

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


async def check_premium_expiring_soon(days: int = 3):
    """检查即将过期的 Premium 用户并记录日志"""

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


def update_premium_status(db, tg_id: int, service: str, days: int = 30) -> datetime:
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
        with get_session() as session:
            stmt = (
                sql_update(PlexUser)
                .where(PlexUser.tg_id == tg_id)
                .values(is_premium=1, premium_expiry_time=new_expiry.isoformat())
            )
            session.execute(stmt)

        # 检查用户是否已经用积分单独解锁了下载权限
        download_status = db.check_download_unlock(tg_id, "plex")
        if not download_status.get("unlock_time"):
            # 用户未单独解锁，Premium 用户自动拥有下载权限，更新媒体服务器
            try:
                from app.modules.plex import Plex

                plex_email = user_info[3]  # plex_email
                if plex_email:
                    plex = Plex()
                    plex.update_sync_for_user(plex_email, allow_sync=True)
                    logger.info(f"已为 Premium 用户 {tg_id} 启用 Plex 同步权限")
            except Exception as e:
                logger.warning(f"为 Premium 用户 {tg_id} 启用 Plex 同步权限失败: {e}")
        else:
            logger.info(f"用户 {tg_id} 已用积分解锁 Plex 下载权限，跳过 Premium 授权")

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
        with get_session() as session:
            stmt = (
                sql_update(EmbyUser)
                .where(EmbyUser.tg_id == tg_id)
                .values(is_premium=1, premium_expiry_time=new_expiry.isoformat())
            )
            session.execute(stmt)

        # 检查用户是否已经用积分单独解锁了下载权限
        download_status = db.check_download_unlock(tg_id, "emby")
        if not download_status.get("unlock_time"):
            # 用户未单独解锁，Premium 用户自动拥有下载权限，更新媒体服务器
            try:
                from app.modules.emby import Emby

                emby_id = user_info[1]  # emby_id
                if emby_id:
                    emby = Emby()
                    emby.update_download_permission_for_user(
                        emby_id, allow_download=True
                    )
                    logger.info(f"已为 Premium 用户 {tg_id} 启用 Emby 下载权限")
            except Exception as e:
                logger.warning(f"为 Premium 用户 {tg_id} 启用 Emby 下载权限失败: {e}")
        else:
            logger.info(f"用户 {tg_id} 已用积分解锁 Emby 下载权限，跳过 Premium 授权")

    return new_expiry


def unbind_premium_line(db, service: str, username: str, tg_id: int):
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


def format_premium_statistics_message(stats) -> str:
    """
    格式化 Premium 线路统计信息为 Telegram 消息格式
    :param stats: 统计数据列表
    :return: 格式化后的消息字符串
    """
    if not stats:
        return "📊 Premium 线路统计信息\n\n❌ 暂无统计数据"

    current_time = datetime.now(settings.TZ).strftime("%Y-%m-%d %H:%M:%S")

    message_parts = [
        "📊 Premium 线路统计信息",
        f"⏰ 统计时间: {current_time}",
        "─" * 40,
    ]

    total_today = 0
    total_week = 0
    total_month = 0

    for line_stat in stats:
        line = line_stat["line"]
        today_traffic = line_stat["today_traffic"]
        week_traffic = line_stat["week_traffic"]
        month_traffic = line_stat["month_traffic"]
        top_users = line_stat["top_users"]

        total_today += today_traffic
        total_week += week_traffic
        total_month += month_traffic

        # 清理线路名称中的多余字符
        clean_line = line.strip("[]'\"")
        message_parts.append(f"🔗 线路: {clean_line}")
        message_parts.append(f"📈 今日流量: {format_traffic_size(today_traffic)}")
        message_parts.append(f"📊 本周流量: {format_traffic_size(week_traffic)}")
        message_parts.append(f"📉 本月流量: {format_traffic_size(month_traffic)}")

        if top_users:
            message_parts.append("👥 今日TOP用户:")
            for i, user in enumerate(top_users, 1):
                username = user["username"]
                traffic = format_traffic_size(user["traffic"])
                message_parts.append(f"  {i}. {username}: {traffic}")
        else:
            message_parts.append("👥 今日暂无用户使用")

        message_parts.append("")  # 空行分隔

    # 添加总计信息
    message_parts.extend(
        [
            "📋 总计统计:",
            f"📈 今日总流量: {format_traffic_size(total_today)}",
            f"📊 本周总流量: {format_traffic_size(total_week)}",
            f"📉 本月总流量: {format_traffic_size(total_month)}",
            "─" * 40,
        ]
    )

    return "\n".join(message_parts)


async def get_and_send_premium_statistics():
    """
    获取Premium线路统计信息并发送给管理员
    """

    try:
        logger.info("开始获取Premium线路统计信息")

        # 获取统计数据
        stats = db.get_premium_line_traffic_statistics()

        if not stats:
            logger.warning("未获取到 Premium 线路统计数据")
            return

        # 格式化消息
        message = format_premium_statistics_message(stats)

        # 发送给所有管理员
        admin_chat_ids = settings.TG_ADMIN_CHAT_ID
        if not admin_chat_ids:
            logger.warning("未配置管理员 ID，无法发送统计信息")
            return

        success_count = 0
        for admin_id in admin_chat_ids:
            try:
                # 转换为整数类型（如果是字符串）
                chat_id = int(admin_id) if isinstance(admin_id, str) else admin_id

                success = await send_message_by_url(
                    chat_id=chat_id, text=message, parse_mode="HTML"
                )

                if success:
                    success_count += 1
                    logger.info(f"成功发送 Premium 统计信息给管理员 {chat_id}")
                else:
                    logger.error(f"发送 Premium 统计信息给管理员 {chat_id} 失败")

            except Exception as e:
                logger.error(f"发送消息给管理员 {admin_id} 时发生错误: {str(e)}")

        logger.info(
            f"Premium 统计信息发送完成，成功发送给 {success_count}/{len(admin_chat_ids)} 个管理员"
        )

    except Exception as e:
        logger.error(f"获取并发送 Premium 统计信息时出错: {str(e)}")
