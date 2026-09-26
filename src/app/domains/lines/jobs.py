import json

from sqlalchemy import or_, select

from app.core.cache import (
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
    plex_last_user_defined_line_cache,
    plex_user_defined_line_cache,
    user_info_cache,
)
from app.core.db import get_session
from app.core.log import logger
from app.core.telegram import get_user_name_from_tg_id
from app.databases.db import db
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.lines.rules import is_binded_premium_line


def write_user_info_cache():
    """
    将 user info 写入 redis 缓存
    """
    try:
        # 获取 Plex 用户信息
        with get_session() as session:
            stmt = select(
                PlexUser.plex_id,
                PlexUser.tg_id,
                PlexUser.plex_username,
                PlexUser.plex_email,
                PlexUser.is_premium,
                PlexUser.plex_line,
            )
            plex_users = session.execute(stmt).fetchall()
        for user in plex_users:
            plex_id = user[0]
            # 未接受邀请，此时数据库中的 plex_id 为空
            if not plex_id:
                continue
            tg_id = user[1]
            plex_username = user[2]
            plex_email = user[3]
            is_premium = user[4]
            plex_line = user[5]
            if plex_username:
                user_info_cache.put(
                    f"plex:{plex_username.lower()}",
                    json.dumps(
                        {
                            "plex_id": plex_id,
                            "tg_id": tg_id,
                            "plex_username": plex_username,
                            "plex_email": plex_email,
                            "is_premium": is_premium,
                        }
                    ),
                )
                if plex_line:
                    plex_user_defined_line_cache.put(
                        str(plex_username).lower(), plex_line
                    )
        # 获取 Emby 用户信息
        with get_session() as session:
            stmt = select(
                EmbyUser.emby_id,
                EmbyUser.tg_id,
                EmbyUser.emby_username,
                EmbyUser.is_premium,
                EmbyUser.emby_line,
            )
            emby_users = session.execute(stmt).fetchall()
        for user in emby_users:
            emby_id = user[0]
            tg_id = user[1]
            emby_username = user[2]
            is_premium = user[3]
            emby_line = user[4]
            if emby_username:
                user_info_cache.put(
                    f"emby:{emby_username.lower()}",
                    json.dumps(
                        {
                            "emby_id": emby_id,
                            "tg_id": tg_id,
                            "emby_username": emby_username,
                            "is_premium": is_premium,
                        }
                    ),
                )
                if emby_line:
                    emby_user_defined_line_cache.put(
                        str(emby_username).lower(), emby_line
                    )
    except Exception as e:
        logger.error(f"写入用户信息缓存时发生错误: {e}")


async def auto_switch_user_lines(tg_id: int | None = None, service: str | None = None):
    """
    自动切换用户线路调度

    Args:
        tg_id: 可选，指定用户 ID，如果不指定则处理所有用户
        service: 可选，指定服务类型 ('plex' 或 'emby')，如果不指定则处理两种服务
    """
    try:
        switched_count = 0

        # 确定要处理的服务类型
        services_to_process = []
        if service:
            if service.lower() not in ["plex", "emby"]:
                logger.error(f"不支持的服务类型: {service}")
                return
            services_to_process = [service.lower()]
        else:
            services_to_process = ["plex", "emby"]

        # 获取所有解锁了线路调度功能的 Plex 用户（包括 premium 用户和解锁用户）
        with get_session() as session:
            # 处理 Plex 用户
            if "plex" in services_to_process:
                # 查询所有解锁了线路调度的 Plex 用户（包括 premium 用户）
                plex_query = select(
                    PlexUser.tg_id, PlexUser.plex_line, PlexUser.plex_username
                ).where(
                    or_(PlexUser.line_schedule_unlocked == 1, PlexUser.is_premium == 1)
                )

                # 如果指定了用户 ID，添加过滤条件
                if tg_id is not None:
                    plex_query = plex_query.where(PlexUser.tg_id == tg_id)

                plex_users = session.execute(plex_query).fetchall()
            else:
                plex_users = []

            for user_tg_id, current_line, plex_username in plex_users:
                logger.debug(f"开始处理 Plex 用户 {plex_username} 的线路调度任务")
                # 获取当前生效的调度
                active_schedule = db.get_current_active_schedule(user_tg_id, "plex")

                if active_schedule:
                    # 有生效的调度，使用调度指定的线路
                    # 线路可能为具体线路名，也可能为 'auto'（表示自动选择）
                    target_line = active_schedule["line"]
                else:
                    # 没有生效的调度，跳过不做修改
                    continue

                # 检查是否需要切换
                if current_line != target_line and db.set_plex_line(
                    line=target_line, tg_id=user_tg_id
                ):
                    # 更新 Redis 缓存
                    if plex_username:
                        if target_line is None or target_line == "auto":
                            # 切换到自动选择，删除 Redis 缓存
                            plex_user_defined_line_cache.delete(
                                str(plex_username).lower()
                            )
                        else:
                            # 切换到指定线路
                            binded_line = plex_user_defined_line_cache.get(
                                str(plex_username).lower()
                            )
                            if binded_line and not is_binded_premium_line(binded_line):
                                # 满足如下条件：
                                # 1. 缓存中存在绑定的线路，且该线路不是高级线路；
                                # 将其记录到上一次使用的普通线路缓存中
                                logger.debug(
                                    f"记录用户 {plex_username} 上一次使用的普通线路 {binded_line}"
                                )
                                plex_last_user_defined_line_cache.put(
                                    str(plex_username).lower(), binded_line
                                )
                            plex_user_defined_line_cache.put(
                                str(plex_username).lower(), target_line
                            )

                    switched_count += 1
                    logger.info(
                        f"自动切换 Plex 用户 {plex_username} 的线路: {current_line or 'AUTO'} -> {target_line if target_line != 'auto' else 'AUTO'}"
                    )

            # 处理 Emby 用户
            if "emby" in services_to_process:
                # 查询所有解锁了线路调度的 Emby 用户（包括 premium 用户）
                emby_query = select(
                    EmbyUser.tg_id, EmbyUser.emby_line, EmbyUser.emby_username
                ).where(
                    or_(EmbyUser.line_schedule_unlocked == 1, EmbyUser.is_premium == 1)
                )

                # 如果指定了用户 ID，添加过滤条件
                if tg_id is not None:
                    emby_query = emby_query.where(EmbyUser.tg_id == tg_id)

                emby_users = session.execute(emby_query).fetchall()
            else:
                emby_users = []

            for user_tg_id, current_line, emby_username in emby_users:
                logger.debug(f"开始处理 Emby 用户 {emby_username} 的线路调度任务")
                # 获取当前生效的调度
                active_schedule = db.get_current_active_schedule(user_tg_id, "emby")

                if active_schedule:
                    # 有生效的调度，使用调度指定的线路
                    # 线路可能为具体线路名，也可能为 'auto'（表示自动选择）
                    target_line = active_schedule["line"]
                else:
                    # 没有生效的调度，跳过不做修改
                    continue

                # 检查是否需要切换
                if current_line != target_line and db.set_emby_line(
                    line=target_line, tg_id=user_tg_id
                ):
                    # 更新 Redis 缓存
                    if emby_username:
                        if target_line is None or target_line == "auto":
                            # 切换到自动选择，删除 Redis 缓存
                            emby_user_defined_line_cache.delete(
                                str(emby_username).lower()
                            )
                        else:
                            # 切换到指定线路
                            binded_line = emby_user_defined_line_cache.get(
                                str(emby_username).lower()
                            )
                            if binded_line and not is_binded_premium_line(binded_line):
                                # 满足如下条件：
                                # 1. 缓存中存在绑定的线路，且该线路不是高级线路；
                                # 将其记录到上一次使用的普通线路缓存中
                                logger.debug(
                                    f"记录用户 {emby_username} 上一次使用的普通线路 {binded_line}"
                                )
                                emby_last_user_defined_line_cache.put(
                                    str(emby_username).lower(), binded_line
                                )
                            emby_user_defined_line_cache.put(
                                str(emby_username).lower(), target_line
                            )

                    switched_count += 1
                    logger.info(
                        f"自动切换 Emby 用户 {emby_username} 的线路: {current_line or 'AUTO'} -> {target_line if target_line != 'auto' else 'AUTO'}"
                    )
        # 生成详细的日志信息
        if tg_id is not None:
            user_info = f"用户 {get_user_name_from_tg_id(tg_id)} (ID: {tg_id})"
        else:
            user_info = "所有符合条件的用户"

        if service:
            service_info = f"{service.upper()} 服务"
        else:
            service_info = "Plex 和 Emby 服务"

        if switched_count > 0:
            logger.info(
                f"自动切换线路任务完成 - "
                f"处理范围: {user_info} | "
                f"服务类型: {service_info} | "
                f"成功切换: {switched_count} 条线路"
            )
        else:
            logger.info("自动切换线路任务完成，没有需要切换的线路")

    except Exception as e:
        logger.error(f"自动切换用户线路失败: {e}")
