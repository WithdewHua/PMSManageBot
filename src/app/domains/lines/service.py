from app.core.log import uvicorn_logger as logger
from app.domains.identity import service as identity_service
from app.domains.lines import catalog
from app.domains.lines import repository as lines_repository
from app.domains.lines.config import LINES_CONFIG
from app.domains.lines.gateway_cache import (
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
    plex_last_user_defined_line_cache,
    plex_user_defined_line_cache,
)
from app.domains.lines.rules import is_binded_premium_line
from app.integrations.emby import Emby
from app.integrations.telegram.messaging import send_message_by_url
from app.integrations.telegram.profiles import get_user_name_from_tg_id


def _line_cache_pair(service: str):
    normalized = service.lower()
    if normalized == "plex":
        return plex_user_defined_line_cache, plex_last_user_defined_line_cache
    if normalized == "emby":
        return emby_user_defined_line_cache, emby_last_user_defined_line_cache
    raise ValueError("不支持的服务类型")


def get_cached_line(service: str, username: str, *, last: bool = False):
    current_cache, last_cache = _line_cache_pair(service)
    return (last_cache if last else current_cache).get(str(username).lower())


def put_cached_line(service: str, username: str, value: str) -> None:
    current_cache, _ = _line_cache_pair(service)
    current_cache.put(str(username).lower(), value)


def delete_cached_line(service: str, username: str, *, last: bool = False) -> None:
    current_cache, last_cache = _line_cache_pair(service)
    (last_cache if last else current_cache).delete(str(username).lower())


def unbind_premium_line(service: str, username: str, tg_id: int) -> str:
    """Restore the previous ordinary line after Premium expiry."""
    if service not in ("plex", "emby"):
        raise ValueError("不支持的服务类型")
    try:
        last_line = get_cached_line(service, username, last=True)
    except Exception as error:
        logger.warning("读取用户 %s 的历史线路失败: %s", username, error)
        last_line = None
    if service == "plex":
        updated = lines_repository.set_plex_line(last_line, tg_id=tg_id)
    else:
        updated = lines_repository.set_emby_line(last_line, tg_id=tg_id)
    if not updated:
        raise RuntimeError("恢复 Premium 线路失败")
    try:
        if last_line:
            put_cached_line(service, username, last_line)
            delete_cached_line(service, username, last=True)
        else:
            delete_cached_line(service, username)
    except Exception as error:
        logger.warning("清理用户 %s 的线路缓存失败: %s", username, error)
    return last_line or "AUTO"


def is_premium_free_enabled() -> bool:
    return bool(LINES_CONFIG.get().premium_free)


def get_line_schedule_unlock_credits() -> int:
    return int(LINES_CONFIG.get().line_schedule_unlock_credits)


def set_premium_free(enabled: bool):
    return LINES_CONFIG.update(premium_free=enabled)


def set_line_schedule_unlock_credits(credits: int) -> int:
    return int(
        LINES_CONFIG.update(
            line_schedule_unlock_credits=credits
        ).line_schedule_unlock_credits
    )


from app.integrations.plex import Plex


def unlock_line_schedule_with_credit(tg_id: int, service: str, cost: float) -> bool:
    """Charge credits and unlock line scheduling atomically."""
    return lines_repository.unlock_line_schedule_with_credit(tg_id, service, cost)


async def unbind_emby_premium_free():
    """解绑所有 Emby Premium Free（恢复普通用户）"""

    if is_premium_free_enabled():
        logger.info("Emby Premium Free 功能未启用，跳过解绑操作")
        return True, None

    try:
        # 获取所有绑定了 Emby 线路的用户
        users = lines_repository.get_emby_user_with_binded_line()
        for user in users:
            emby_username, tg_id, emby_id, emby_line, is_premium = user
            if is_premium:
                continue
            # 如果是普通用户，检查是否是高级线路
            is_premium_line = is_binded_premium_line(emby_line, catalog.premium_lines())
            if not is_premium_line:
                # 如果不是高级线路，跳过
                continue
            # 获取上一次绑定的非 premium 线路
            last_line = emby_last_user_defined_line_cache.get(
                str(emby_username).lower()
            )
            # 更新用户的 Emby 线路，last_line 为空则自动选择
            lines_repository.set_emby_line(last_line, tg_id=tg_id, emby_id=emby_id)
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

    if is_premium_free_enabled():
        logger.info("Plex Premium Free 功能未启用，跳过解绑操作")
        return True, None

    try:
        # 获取所有绑定了 Plex 线路的用户
        users = lines_repository.get_plex_user_with_binded_line()
        for user in users:
            plex_username, tg_id, plex_id, plex_line, is_premium = user
            if is_premium:
                continue
            # 如果是普通用户，检查是否是高级线路
            is_premium_line = is_binded_premium_line(plex_line, catalog.premium_lines())
            if not is_premium_line:
                # 如果不是高级线路，跳过
                continue
            # 获取上一次绑定的非 premium 线路
            last_line = plex_last_user_defined_line_cache.get(
                str(plex_username).lower()
            )
            # 更新用户的 Plex 线路，last_line 为空则自动选择
            lines_repository.set_plex_line(last_line, tg_id=tg_id, plex_id=plex_id)
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
        users = lines_repository.get_emby_user_with_binded_line()
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
            lines_repository.set_emby_line(last_line, tg_id=tg_id, emby_id=emby_id)
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
        users = lines_repository.get_plex_user_with_binded_line()
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
            lines_repository.set_plex_line(last_line, tg_id=tg_id, plex_id=plex_id)
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
        emby_users = lines_repository.get_emby_user_with_binded_line()
        for user in emby_users:
            emby_username, tg_id, emby_id, user_emby_line, _ = user
            if line in user_emby_line:
                # 如果用户绑定的线路是指定的线路，解绑
                lines_repository.set_emby_line(line=None, tg_id=tg_id, emby_id=emby_id)
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
        plex_users = lines_repository.get_plex_user_with_binded_line()
        for user in plex_users:
            plex_username, tg_id, plex_id, user_plex_line, _ = user
            if line in user_plex_line:
                # 如果用户绑定的线路是指定的线路，解绑
                lines_repository.set_plex_line(line=None, tg_id=tg_id, plex_id=plex_id)
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
        success, disabled_count, affected_users = (
            lines_repository.disable_schedules_by_line(
                line_name, only_non_premium=only_non_premium
            )
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
    is_premium_line_flag = is_binded_premium_line(line, catalog.premium_lines())
    if not is_premium_line_flag:
        # 普通线路，所有用户都可以使用
        return True, ""

    # 高级线路需要进一步检查
    if is_premium_free_enabled():
        # 检查该高级线路是否在免费列表中
        free_premium_lines = lines_repository.get_free_premium_lines()
        if line in free_premium_lines:
            return True, ""
        else:
            return False, "该高级线路暂未开放免费使用"
    else:
        return False, "您不是 premium 用户，无法使用该线路"


async def _auth_bind_emby_line(
    tg_id: int,
    username: str,
    password: str,
    line: str,
) -> tuple[bool, str]:
    """认证并绑定Emby线路的内部方法"""
    from app.domains.lines.gateway_cache import (
        emby_last_user_defined_line_cache,
        emby_user_defined_line_cache,
    )

    # 验证 Emby 用户名和密码
    emby = Emby()
    auth_success, emby_id = emby.authenticate_user(username, password)
    if not auth_success:
        logger.warning(f"Emby用户 {username} 认证失败")
        return False, "用户名或密码错误"

    # 获取用户信息以检查线路权限
    existing_emby_info = identity_service.get_emby_info_by_emby_username(username)

    # 检查线路权限
    # 如果用户不存在于数据库，视为普通用户；否则使用数据库中的 premium 状态
    is_premium = existing_emby_info[8] == 1 if existing_emby_info else False
    has_permission, error_msg = check_line_permission(is_premium, line)
    if not has_permission:
        return False, error_msg

    # 设置线路到数据库（如果用户存在于数据库中）
    if existing_emby_info:
        success = lines_repository.set_emby_line(line, emby_id=emby_id)
        if not success:
            logger.error(f"设置 Emby 用户 {username} 的线路失败")
            return False, "设置线路失败"

    # 更新 redis 缓存 - 记录线路绑定
    binded_line = emby_user_defined_line_cache.get(str(username).lower())
    if binded_line and not is_binded_premium_line(binded_line, catalog.premium_lines()):
        logger.debug(f"记录用户 {username} 上一次使用的普通线路 {binded_line}")
        emby_last_user_defined_line_cache.put(str(username).lower(), binded_line)
    emby_user_defined_line_cache.put(str(username).lower(), line)

    logger.info(
        f"用户 {get_user_name_from_tg_id(tg_id)} 为 {username} 成功认证并绑定Emby线路 {line}"
    )
    return True, f"认证并绑定 Emby 线路 {line} 成功！"


async def _auth_bind_plex_line(
    tg_id: int,
    username: str,
    line: str,
    password: str | None = None,
    token: str | None = None,
) -> tuple[bool, str]:
    """认证并绑定Plex线路的内部方法"""
    from app.domains.lines.gateway_cache import (
        plex_last_user_defined_line_cache,
        plex_user_defined_line_cache,
    )

    # 验证Plex用户名和密码
    plex = Plex()
    auth_success, plex_id = plex.authenticate_user(
        username=username, password=password, token=token
    )
    if not auth_success or plex_id is None:
        logger.warning(f"Plex 用户 {username} 认证失败")
        return False, "用户名或密码错误"

    # 获取 Plex 用户信息
    existing_plex_info = identity_service.get_plex_info_by_plex_id(plex_id)

    # 检查线路权限
    # 如果用户不存在于数据库，视为普通用户；否则使用数据库中的 premium 状态
    is_premium = existing_plex_info[9] == 1 if existing_plex_info else False
    has_permission, error_msg = check_line_permission(is_premium, line)
    if not has_permission:
        return False, error_msg

    # 如果用户已存在，更新数据库中的线路设置
    if existing_plex_info:
        success = lines_repository.set_plex_line(line, plex_id=plex_id)
        if not success:
            logger.error(
                f"{get_user_name_from_tg_id(tg_id)} 为 {username} 设置 Plex 线路失败"
            )
            return False, "设置线路失败"

    # 更新 redis 缓存 - 记录线路绑定
    plex_username = plex.get_username_by_user_id(plex_id)
    binded_line = plex_user_defined_line_cache.get(str(plex_username).lower())
    if binded_line and not is_binded_premium_line(binded_line, catalog.premium_lines()):
        logger.debug(f"记录用户 {plex_username} 上一次使用的普通线路 {binded_line}")
        plex_last_user_defined_line_cache.put(str(plex_username).lower(), binded_line)
    plex_user_defined_line_cache.put(str(plex_username).lower(), line)

    logger.info(
        f"用户 {get_user_name_from_tg_id(tg_id)} 为 {plex_username} 成功认证并绑定 Plex 线路 {line}"
    )
    return True, f"认证并绑定 Plex 线路 {line} 成功！"


def write_user_line_cache() -> None:
    """Refresh line-selection caches after the repository read has committed."""
    try:
        plex_users, emby_users = lines_repository.list_line_cache_rows()
        for plex_id, username, line in plex_users:
            if plex_id and username and line:
                plex_user_defined_line_cache.put(str(username).lower(), line)
        for username, line in emby_users:
            if username and line:
                emby_user_defined_line_cache.put(str(username).lower(), line)
    except Exception as error:
        logger.error(f"写入线路缓存时发生错误: {error}")


async def auto_switch_user_lines(
    tg_id: int | None = None, service: str | None = None
) -> None:
    """Apply active schedules, one committed transaction per eligible user."""
    try:
        normalized_service = service.lower() if service else None
        if normalized_service not in (None, "plex", "emby"):
            logger.error(f"不支持的服务类型: {service}")
            return

        switched_count = 0
        # This candidate read completes before any per-user write begins.
        candidates = lines_repository.get_auto_switch_candidates(
            tg_id, normalized_service
        )
        for candidate in candidates:
            result = lines_repository.apply_active_schedule(
                candidate["tg_id"], candidate["service"]
            )
            if result is None:
                continue

            # apply_active_schedule has committed before any cache is touched.
            username = result["username"]
            if username:
                cache_key = str(username).lower()
                current_cache = (
                    plex_user_defined_line_cache
                    if result["service"] == "plex"
                    else emby_user_defined_line_cache
                )
                previous_cache = (
                    plex_last_user_defined_line_cache
                    if result["service"] == "plex"
                    else emby_last_user_defined_line_cache
                )
                previous = current_cache.get(cache_key)
                if previous and not is_binded_premium_line(
                    previous, catalog.premium_lines()
                ):
                    previous_cache.put(cache_key, previous)
                current_cache.put(cache_key, result["line"])

            switched_count += 1
            logger.info(
                f"自动切换 {result['service'].capitalize()} 用户 {username} 的线路: "
                f"{result['old_line'] or 'AUTO'} -> {result['line']}"
            )

        user_info = (
            f"用户 {get_user_name_from_tg_id(tg_id)} (ID: {tg_id})"
            if tg_id is not None
            else "所有符合条件的用户"
        )
        service_info = (
            f"{normalized_service.upper()} 服务"
            if normalized_service
            else "Plex 和 Emby 服务"
        )
        if switched_count:
            logger.info(
                f"自动切换线路任务完成 - "
                f"处理范围: {user_info} | "
                f"服务类型: {service_info} | "
                f"成功切换: {switched_count} 条线路"
            )
        else:
            logger.info("自动切换线路任务完成，没有需要切换的线路")
    except Exception as error:
        logger.error(f"自动切换用户线路失败: {error}")


def set_emby_line(line: str | None, *, tg_id: int) -> bool:
    return lines_repository.set_emby_line(line, tg_id=tg_id)


def set_plex_line(line: str | None, *, tg_id: int) -> bool:
    return lines_repository.set_plex_line(line, tg_id=tg_id)


# Schedule entry points stay in the service layer; repository owns transaction boundaries.
def check_line_schedule_unlock(tg_id: int, service: str) -> dict:
    return lines_repository.check_line_schedule_unlock(tg_id, service)


def get_line_schedule_account(tg_id: int, service: str) -> dict | None:
    return lines_repository.get_line_schedule_account(tg_id, service)


def get_user_line_schedules(
    tg_id: int, service: str | None = None, enabled_only: bool = False
) -> list[dict]:
    return lines_repository.get_user_line_schedules(tg_id, service, enabled_only)


def create_line_schedule(
    tg_id: int,
    service: str,
    line: str,
    days_of_week: list[int],
    start_time: str,
    end_time: str,
    priority: int = 0,
) -> int | None:
    return lines_repository.create_line_schedule(
        tg_id, service, line, days_of_week, start_time, end_time, priority
    )


def update_line_schedule(schedule_id: int, tg_id: int, **kwargs) -> bool:
    return lines_repository.update_line_schedule(schedule_id, tg_id, **kwargs)


def delete_line_schedule(schedule_id: int, tg_id: int) -> bool:
    return lines_repository.delete_line_schedule(schedule_id, tg_id)


def get_current_active_schedule(tg_id: int, service: str) -> dict | None:
    return lines_repository.get_current_active_schedule(tg_id, service)
