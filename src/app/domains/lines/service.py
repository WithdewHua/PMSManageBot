from app.core.cache import (
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
    plex_last_user_defined_line_cache,
    plex_user_defined_line_cache,
)
from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.schemas import BaseResponse, TelegramUser
from app.core.telegram import get_user_name_from_tg_id, send_message_by_url
from app.databases import db
from app.databases.db import DatabaseORM
from app.domains.lines import repository as lines_repository
from app.domains.lines.rules import is_binded_premium_line
from app.integrations.emby import Emby
from app.integrations.plex import Plex


def unlock_line_schedule_with_credit(tg_id: int, service: str, cost: float) -> bool:
    """Charge credits and unlock line scheduling atomically."""
    return lines_repository.LinesRepository().unlock_line_schedule_with_credit(
        tg_id, service, cost
    )


async def unbind_emby_premium_free():
    """解绑所有 Emby Premium Free（恢复普通用户）"""

    if settings.PREMIUM_FREE:
        logger.info("Emby Premium Free 功能未启用，跳过解绑操作")
        return True, None

    try:
        # 获取所有绑定了 Emby 线路的用户
        users = db.get_emby_user_with_binded_line()
        for user in users:
            emby_username, tg_id, emby_id, emby_line, is_premium = user
            if is_premium:
                continue
            # 如果是普通用户，检查是否是高级线路
            is_premium_line = is_binded_premium_line(emby_line)
            if not is_premium_line:
                # 如果不是高级线路，跳过
                continue
            # 获取上一次绑定的非 premium 线路
            last_line = emby_last_user_defined_line_cache.get(
                str(emby_username).lower()
            )
            # 更新用户的 Emby 线路，last_line 为空则自动选择
            db.set_emby_line(last_line, tg_id=tg_id, emby_id=emby_id)
            # 更新缓存
            if last_line:
                emby_user_defined_line_cache.put(str(emby_username).lower(), last_line)
                emby_last_user_defined_line_cache.delete(str(emby_username).lower())
            else:
                emby_user_defined_line_cache.delete(str(emby_username).lower())
            # 发送通知给用户
            if tg_id:
                await send_message_by_url(
                    chat_id=tg_id,
                    text=f"通知：高级线路开放通道已关闭，您绑定的线路已切换为 `{last_line or 'AUTO'}`",
                    parse_mode="markdownv2",
                )

        return True, None
    except Exception as e:
        logger.error(f"解绑所有普通用户的 premium 线路时发生错误: {e!s}")
        return False, f"解绑所有普通用户的 premium 线路时发生错误: {e!s}"


async def unbind_plex_premium_free():
    """解绑所有 Plex Premium Free（恢复普通用户）"""

    if settings.PREMIUM_FREE:
        logger.info("Plex Premium Free 功能未启用，跳过解绑操作")
        return True, None

    try:
        # 获取所有绑定了 Plex 线路的用户
        users = db.get_plex_user_with_binded_line()
        for user in users:
            plex_username, tg_id, plex_id, plex_line, is_premium = user
            if is_premium:
                continue
            # 如果是普通用户，检查是否是高级线路
            is_premium_line = is_binded_premium_line(plex_line)
            if not is_premium_line:
                # 如果不是高级线路，跳过
                continue
            # 获取上一次绑定的非 premium 线路
            last_line = plex_last_user_defined_line_cache.get(
                str(plex_username).lower()
            )
            # 更新用户的 Plex 线路，last_line 为空则自动选择
            db.set_plex_line(last_line, tg_id=tg_id, plex_id=plex_id)
            # 更新缓存
            if last_line:
                plex_user_defined_line_cache.put(str(plex_username).lower(), last_line)
                plex_last_user_defined_line_cache.delete(str(plex_username).lower())
            else:
                plex_user_defined_line_cache.delete(str(plex_username).lower())
            # 发送通知给用户
            if tg_id:
                await send_message_by_url(
                    chat_id=tg_id,
                    text=f"通知：高级线路开放通道已关闭，您绑定的线路已切换为 `{last_line or 'AUTO'}`",
                    parse_mode="markdownv2",
                )

        return True, None
    except Exception as e:
        logger.error(f"解绑所有普通用户的 premium 线路时发生错误: {e!s}")
        return False, f"解绑所有普通用户的 premium 线路时发生错误: {e!s}"


async def handle_free_premium_lines_change(removed_lines: list | set):
    """处理免费高级线路变更，检查并处理不再免费的线路"""

    try:
        if not removed_lines:
            return True, None

        # 获取所有绑定了被移除线路的普通用户
        users = db.get_emby_user_with_binded_line()
        for user in users:
            emby_username, tg_id, emby_id, emby_line, is_premium = user
            if is_premium:
                continue

            # 检查用户绑定的线路是否在被移除的免费线路中
            line_removed = False
            for removed_line in removed_lines:
                if removed_line in emby_line:
                    line_removed = True
                    break

            if not line_removed:
                continue

            # 获取上一次绑定的非 premium 线路
            last_line = emby_last_user_defined_line_cache.get(
                str(emby_username).lower()
            )
            # 更新用户的 Emby 线路，last_line 为空则自动选择
            db.set_emby_line(last_line, tg_id=tg_id, emby_id=emby_id)
            # 更新缓存
            if last_line:
                emby_user_defined_line_cache.put(str(emby_username).lower(), last_line)
                emby_last_user_defined_line_cache.delete(str(emby_username).lower())
            else:
                emby_user_defined_line_cache.delete(str(emby_username).lower())
            # 发送通知给用户
            if tg_id:
                await send_message_by_url(
                    chat_id=tg_id,
                    text=f"通知：线路 `{emby_line}` 已不再免费开放，您的 Emby 绑定线路已切换为 `{last_line or 'AUTO'}`",
                    parse_mode="markdownv2",
                )

        # 获取所有绑定了被移除线路的 Plex 用户
        users = db.get_plex_user_with_binded_line()
        for user in users:
            plex_username, tg_id, plex_id, plex_line, is_premium = user
            if is_premium:
                continue
            # 检查用户绑定的线路是否在被移除的免费线路中
            line_removed = False
            for removed_line in removed_lines:
                if removed_line in plex_line:
                    line_removed = True
                    break
            if not line_removed:
                continue
            # 获取上一次绑定的非 premium 线路
            last_line = plex_last_user_defined_line_cache.get(
                str(plex_username).lower()
            )
            # 更新用户的 Plex 线路，last_line 为空则自动选择
            db.set_plex_line(last_line, tg_id=tg_id, plex_id=plex_id)
            # 更新缓存
            if last_line:
                plex_user_defined_line_cache.put(str(plex_username).lower(), last_line)
                plex_last_user_defined_line_cache.delete(str(plex_username).lower())
            else:
                plex_user_defined_line_cache.delete(str(plex_username).lower())
            # 发送通知给用户
            if tg_id:
                await send_message_by_url(
                    chat_id=tg_id,
                    text=f"通知：线路 `{plex_line}` 已不再开放，您绑定的 Plex 线路已切换为 `{last_line or 'AUTO'}`",
                    parse_mode="markdownv2",
                )

        # 禁用被移除线路的所有调度并通知用户（只影响非 premium 用户）
        for removed_line in removed_lines:
            await disable_line_schedules_and_notify(
                removed_line, "线路已不再免费开放", only_non_premium=True
            )

        return True, None
    except Exception as e:
        logger.error(f"处理免费高级线路变更时发生错误: {e!s}")
        return False, f"处理免费高级线路变更时发生错误: {e!s}"


async def unbind_specified_line_for_all_users(
    line: str, reason: str = "已被管理员下线"
):
    """解绑所有用户的指定线路（通用，同时支持Plex和Emby）

    Args:
        line: 线路名称或域名
        reason: 下线原因，用于通知用户

    Returns:
        (success, unbind_count): 成功标志和解绑用户数量
    """

    try:
        unbind_count = 0

        # 获取所有绑定了 Emby 线路的用户
        emby_users = db.get_emby_user_with_binded_line()
        for user in emby_users:
            emby_username, tg_id, emby_id, user_emby_line, _ = user
            if line in user_emby_line:
                # 如果用户绑定的线路是指定的线路，解绑
                db.set_emby_line(line=None, tg_id=tg_id, emby_id=emby_id)
                emby_user_defined_line_cache.delete(str(emby_username).lower())
                emby_last_user_defined_line_cache.delete(str(emby_username).lower())
                unbind_count += 1
                # 发送通知给用户
                if tg_id:
                    await send_message_by_url(
                        chat_id=tg_id,
                        text=f"通知：您绑定的 Emby 线路 `{line}` {reason}，已切换为 `AUTO`",
                        parse_mode="markdownv2",
                    )

        # 处理Plex用户解绑逻辑
        plex_users = db.get_plex_user_with_binded_line()
        for user in plex_users:
            plex_username, tg_id, plex_id, user_plex_line, _ = user
            if line in user_plex_line:
                # 如果用户绑定的线路是指定的线路，解绑
                db.set_plex_line(line=None, tg_id=tg_id, plex_id=plex_id)
                plex_user_defined_line_cache.delete(str(plex_username).lower())
                plex_last_user_defined_line_cache.delete(str(plex_username).lower())
                unbind_count += 1
                # 发送通知给用户
                if tg_id:
                    await send_message_by_url(
                        chat_id=tg_id,
                        text=f"通知：您绑定的 Plex 线路 `{line}` {reason}，已切换为 `AUTO`",
                        parse_mode="markdownv2",
                    )

        logger.info(f"成功解绑 {unbind_count} 个用户的线路 {line}")
        return True, unbind_count

    except Exception as e:
        logger.error(f"解绑所有用户的 {line} 线路时发生错误: {e!s}")
        return False, f"解绑所有用户的 {line} 线路时发生错误: {e!s}"


async def disable_line_schedules_and_notify(
    line_name: str, reason: str = "线路已下线", only_non_premium: bool = False
):
    """
    禁用指定线路的所有调度并通知相关用户

    Args:
        line_name: 线路名称
        reason: 禁用原因，用于通知用户
        only_non_premium: 是否只禁用非 premium 用户的调度
    """
    try:
        # 禁用调度并获取受影响的用户
        success, disabled_count, affected_users = db.disable_schedules_by_line(
            line_name, only_non_premium=only_non_premium
        )

        if not success:
            logger.error(f"禁用线路 {line_name} 的调度失败")
            return False, f"禁用线路 {line_name} 的调度失败"

        if disabled_count == 0:
            logger.info(f"没有需要禁用的调度（线路: {line_name}）")
            return True, "没有受影响的调度"

        logger.info(f"已禁用 {disabled_count} 个使用线路 {line_name} 的调度")

        # 通知所有受影响的用户
        for user_info in affected_users:
            tg_id = user_info["tg_id"]
            service = user_info["service"]
            schedule_count = user_info["schedule_count"]

            service_name = "Emby" if service == "emby" else "Plex"

            try:
                await send_message_by_url(
                    chat_id=tg_id,
                    text=f"""
⚠️ 线路调度变更通知

线路：`{line_name}`
原因：{reason}

您的 {schedule_count} 个 {service_name} 线路调度已被自动禁用。

如需继续使用该线路，请在管理面板中重新启用调度或选择其他线路。
""",
                    parse_mode="markdownv2",
                )
                logger.info(
                    f"已向用户 {get_user_name_from_tg_id(tg_id)} 发送线路调度禁用通知"
                )
            except Exception as e:
                logger.warning(f"发送线路调度禁用通知给用户 {tg_id} 失败: {e!s}")

        return (
            True,
            f"成功禁用 {disabled_count} 个调度并通知 {len(affected_users)} 位用户",
        )

    except Exception as e:
        logger.error(f"禁用线路 {line_name} 的调度并通知用户时发生错误: {e!s}")
        return False, f"禁用线路调度并通知用户时发生错误: {e!s}"


def check_line_permission(is_premium: bool, line: str) -> tuple[bool, str]:
    """
    检查用户是否有权使用指定线路

    Args:
        is_premium: 是否为 premium 用户
        line: 线路名称

    Returns:
        tuple[bool, str]: (是否有权限, 错误消息)
    """
    # Premium 用户拥有所有线路权限
    if is_premium:
        return True, ""

    # 检查是否为高级线路
    is_premium_line_flag = is_binded_premium_line(line)
    if not is_premium_line_flag:
        # 普通线路，所有用户都可以使用
        return True, ""

    # 高级线路需要进一步检查
    if settings.PREMIUM_FREE:
        # 检查该高级线路是否在免费列表中
        free_premium_lines = db.get_free_premium_lines()
        if line in free_premium_lines:
            return True, ""
        else:
            return False, "该高级线路暂未开放免费使用"
    else:
        return False, "您不是 premium 用户，无法使用该线路"


async def _auth_bind_emby_line(
    db: DatabaseORM,
    tg_id: int,
    telegram_user: TelegramUser,
    username: str,
    password: str,
    line: str,
) -> BaseResponse:
    """认证并绑定Emby线路的内部方法"""
    from app.core.cache import (
        emby_last_user_defined_line_cache,
        emby_user_defined_line_cache,
    )

    # 验证 Emby 用户名和密码
    emby = Emby()
    auth_success, emby_id = emby.authenticate_user(username, password)
    if not auth_success:
        logger.warning(f"Emby用户 {username} 认证失败")
        return BaseResponse(success=False, message="用户名或密码错误")

    # 获取用户信息以检查线路权限
    existing_emby_info = db.get_emby_info_by_emby_username(username)

    # 检查线路权限
    # 如果用户不存在于数据库，视为普通用户；否则使用数据库中的 premium 状态
    is_premium = existing_emby_info[8] == 1 if existing_emby_info else False
    has_permission, error_msg = check_line_permission(is_premium, line)
    if not has_permission:
        return BaseResponse(success=False, message=error_msg)

    # 设置线路到数据库（如果用户存在于数据库中）
    if existing_emby_info:
        success = db.set_emby_line(line, emby_id=emby_id)
        if not success:
            logger.error(f"设置 Emby 用户 {username} 的线路失败")
            return BaseResponse(success=False, message="设置线路失败")

    # 更新 redis 缓存 - 记录线路绑定
    binded_line = emby_user_defined_line_cache.get(str(username).lower())
    if binded_line and not is_binded_premium_line(binded_line):
        logger.debug(f"记录用户 {username} 上一次使用的普通线路 {binded_line}")
        emby_last_user_defined_line_cache.put(str(username).lower(), binded_line)
    emby_user_defined_line_cache.put(str(username).lower(), line)

    logger.info(
        f"用户 {get_user_name_from_tg_id(tg_id)} 为 {username} 成功认证并绑定Emby线路 {line}"
    )
    return BaseResponse(success=True, message=f"认证并绑定 Emby 线路 {line} 成功！")


async def _auth_bind_plex_line(
    db: DatabaseORM,
    tg_id: int,
    telegram_user: TelegramUser,
    username: str,
    line: str,
    password: str | None = None,
    token: str | None = None,
) -> BaseResponse:
    """认证并绑定Plex线路的内部方法"""
    from app.core.cache import (
        plex_last_user_defined_line_cache,
        plex_user_defined_line_cache,
    )

    # 验证Plex用户名和密码
    plex = Plex()
    auth_success, plex_id = plex.authenticate_user(
        username=username, password=password, token=token
    )
    if not auth_success:
        logger.warning(f"Plex 用户 {username} 认证失败")
        return BaseResponse(success=False, message="用户名或密码错误")

    # 获取 Plex 用户信息
    existing_plex_info = db.get_plex_info_by_plex_id(plex_id)

    # 检查线路权限
    # 如果用户不存在于数据库，视为普通用户；否则使用数据库中的 premium 状态
    is_premium = existing_plex_info[9] == 1 if existing_plex_info else False
    has_permission, error_msg = check_line_permission(is_premium, line)
    if not has_permission:
        return BaseResponse(success=False, message=error_msg)

    # 如果用户已存在，更新数据库中的线路设置
    if existing_plex_info:
        success = db.set_plex_line(line, plex_id=plex_id)
        if not success:
            logger.error(
                f"{get_user_name_from_tg_id(tg_id)} 为 {username} 设置 Plex 线路失败"
            )
            return BaseResponse(success=False, message="设置线路失败")

    # 更新 redis 缓存 - 记录线路绑定
    plex_username = plex.get_username_by_user_id(plex_id)
    binded_line = plex_user_defined_line_cache.get(str(plex_username).lower())
    if binded_line and not is_binded_premium_line(binded_line):
        logger.debug(f"记录用户 {plex_username} 上一次使用的普通线路 {binded_line}")
        plex_last_user_defined_line_cache.put(str(plex_username).lower(), binded_line)
    plex_user_defined_line_cache.put(str(plex_username).lower(), line)

    logger.info(
        f"用户 {get_user_name_from_tg_id(tg_id)} 为 {plex_username} 成功认证并绑定 Plex 线路 {line}"
    )
    return BaseResponse(success=True, message=f"认证并绑定 Plex 线路 {line} 成功！")
