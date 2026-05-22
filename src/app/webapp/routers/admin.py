import asyncio

from app.config import settings
from app.databases import db
from app.databases.cache import (
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
    plex_last_user_defined_line_cache,
    plex_user_defined_line_cache,
)
from app.log import uvicorn_logger as logger
from app.utils.utils import (
    get_user_name_from_tg_id,
    is_binded_premium_line,
    send_message_by_url,
)
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import (
    AllLineTagsResponse,
    BaseResponse,
    LineTagRequest,
    LineTagResponse,
    TelegramUser,
)
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request

router = APIRouter(prefix="/api/admin", tags=["admin"])


def check_admin_permission(user: TelegramUser):
    """检查用户是否为管理员"""
    # 开发环境允许模拟管理员
    if user.id == 123456789:  # 模拟用户ID
        return True

    if user.id not in settings.TG_ADMIN_CHAT_ID:
        raise HTTPException(status_code=403, detail="权限不足，需要管理员权限")
    return True


@router.get("/settings")
@require_telegram_auth
async def get_admin_settings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取管理员设置"""
    check_admin_permission(user)

    try:
        # 从数据库获取免费高级线路列表
        free_premium_lines = db.get_free_premium_lines()

        settings_data = {
            "plex_register": settings.PLEX_REGISTER,
            "emby_register": settings.EMBY_REGISTER,
            "premium_free": settings.PREMIUM_FREE,
            "premium_unlock_enabled": settings.PREMIUM_UNLOCK_ENABLED,
            "lines": settings.STREAM_BACKEND,
            "premium_lines": settings.PREMIUM_STREAM_BACKEND,
            "free_premium_lines": free_premium_lines,
            "invitation_credits": settings.INVITATION_CREDITS,
            "unlock_credits": settings.UNLOCK_CREDITS,
            "premium_daily_credits": settings.PREMIUM_DAILY_CREDITS,
            "user_traffic_limit": settings.USER_TRAFFIC_LIMIT,
            "premium_user_traffic_limit": settings.PREMIUM_USER_TRAFFIC_LIMIT,
            "credits_transfer_enabled": settings.CREDITS_TRANSFER_ENABLED,  # 添加积分转移开关
            "line_schedule_unlock_credits": settings.LINE_SCHEDULE_UNLOCK_CREDITS,  # 解锁线路调度功能所需积分
            "download_unlock_credits": settings.DOWNLOAD_UNLOCK_CREDITS,  # 解锁下载/同步功能所需积分
        }

        logger.info(f"管理员 {user.username or user.id} 获取系统设置")
        return settings_data
    except Exception as e:
        logger.error(f"获取管理员设置失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取设置失败")


@router.post("/settings/plex-register")
@require_telegram_auth
async def set_plex_register(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置Plex注册开关"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        settings.PLEX_REGISTER = bool(enabled)
        settings.save_config_to_env_file({"PLEX_REGISTER": str(enabled).lower()})

        logger.info(
            f"管理员 {user.username or user.id} 设置 Plex 注册状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"Plex 注册已{'开启' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置 Plex 注册状态失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/emby-register")
@require_telegram_auth
async def set_emby_register(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置Emby注册开关"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        settings.EMBY_REGISTER = bool(enabled)
        settings.save_config_to_env_file({"EMBY_REGISTER": str(enabled).lower()})

        logger.info(
            f"管理员 {user.username or user.id} 设置 Emby 注册状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"Emby 注册已{'开启' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置 Emby 注册状态失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/premium-free")
@require_telegram_auth
async def set_premium_free(
    request: Request,
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置高级线路免费使用开关（通用，同时支持Plex和Emby）"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        old_status = settings.PREMIUM_FREE
        settings.PREMIUM_FREE = bool(enabled)
        settings.save_config_to_env_file({"PREMIUM_FREE": str(enabled).lower()})

        # 如果从开启变为关闭，需要处理现有用户的高级线路绑定
        if old_status and not enabled:
            # 调用解绑所有普通用户的premium线路的函数
            logger.info("添加解绑所有普通用户的高级线路任务")
            background_tasks.add_task(unbind_emby_premium_free)
            background_tasks.add_task(unbind_plex_premium_free)

        logger.info(
            f"管理员 {user.username or user.id} 设置高级线路免费使用状态为: {enabled}"
        )
        return BaseResponse(
            success=True,
            message=f"高级线路免费使用已{'开启' if enabled else '关闭'}",
        )
    except Exception as e:
        logger.error(f"设置高级线路免费使用状态失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/emby-premium-free")
@require_telegram_auth
async def set_emby_premium_free(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置Emby高级线路免费使用开关（兼容性接口，推荐使用 /settings/premium-free）"""
    return await set_premium_free(request, data, user)


@router.post("/settings/free-premium-lines")
@require_telegram_auth
async def set_free_premium_lines(
    request: Request,
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置免费的高级线路列表（通用，同时支持Plex和Emby）"""
    check_admin_permission(user)

    try:
        free_lines = data.get("free_lines", [])

        # 验证线路是否都在高级线路列表中
        for line in free_lines:
            if line not in settings.PREMIUM_STREAM_BACKEND:
                return BaseResponse(
                    success=False, message=f"线路 {line} 不在高级线路列表中"
                )

        # 保存到数据库
        old_free_lines = db.get_free_premium_lines()
        db.set_free_premium_lines(free_lines)

        removed_lines = set(old_free_lines) - set(free_lines)
        added_lines = set(free_lines) - set(old_free_lines)

        # 处理现有用户的线路绑定 - 如果某些原本免费的线路被移除，需要处理
        logger.info("增加免费高级线路变更处理任务")
        background_tasks.add_task(handle_free_premium_lines_change, removed_lines)

        # 发送频道通知 - 新增免费高级线路
        if added_lines and settings.TG_CHANNEL_ID:
            lines_list = "\n".join([f"🌐 {line}" for line in added_lines])
            channel_notification = f"""🎉 Premium 线路免费开放通知

以下 Premium 线路现已免费开放：

{lines_list}

如有需要，可在面板绑定使用"""
            background_tasks.add_task(
                send_message_by_url,
                chat_id=settings.TG_CHANNEL_ID,
                text=channel_notification,
            )

        logger.info(
            f"管理员 {user.username or user.id} 设置免费 Premium 线路为: {free_lines}"
        )
        return BaseResponse(
            success=True,
            message=f"免费 Premium 线路设置已更新，共 {len(free_lines)} 条线路",
        )
    except Exception as e:
        logger.error(f"设置免费 Premium 线路失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/emby-free-premium-lines")
@require_telegram_auth
async def set_emby_free_premium_lines(
    request: Request,
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置免费的Emby高级线路列表（兼容性接口，推荐使用 /settings/free-premium-lines）"""
    return await set_free_premium_lines(request, background_tasks, data, user)


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
        logger.error(f"解绑所有普通用户的 premium 线路时发生错误: {str(e)}")
        return False, f"解绑所有普通用户的 premium 线路时发生错误: {str(e)}"


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
        logger.error(f"解绑所有普通用户的 premium 线路时发生错误: {str(e)}")
        return False, f"解绑所有普通用户的 premium 线路时发生错误: {str(e)}"


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
        logger.error(f"处理免费高级线路变更时发生错误: {str(e)}")
        return False, f"处理免费高级线路变更时发生错误: {str(e)}"


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
        logger.error(f"解绑所有用户的 {line} 线路时发生错误: {str(e)}")
        return False, f"解绑所有用户的 {line} 线路时发生错误: {str(e)}"


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
                logger.warning(f"发送线路调度禁用通知给用户 {tg_id} 失败: {str(e)}")

        return (
            True,
            f"成功禁用 {disabled_count} 个调度并通知 {len(affected_users)} 位用户",
        )

    except Exception as e:
        logger.error(f"禁用线路 {line_name} 的调度并通知用户时发生错误: {str(e)}")
        return False, f"禁用线路调度并通知用户时发生错误: {str(e)}"


@router.post("/donation")
@require_telegram_auth
async def submit_donation_record(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """提交捐赠记录"""
    check_admin_permission(user)

    try:
        tg_id = data.get("tg_id")
        amount = data.get("amount", 0)
        note = data.get("note", "")

        if not tg_id or amount <= 0:
            return BaseResponse(success=False, message="参数错误")

        # 获取当前捐赠金额
        stats_info = db.get_stats_by_tg_id(tg_id)
        if not stats_info:
            return BaseResponse(success=False, message="用户不存在")

        current_donation = stats_info[1] if stats_info[1] else 0
        new_donation = round(current_donation + float(amount), 2)
        current_credits = stats_info[2] if stats_info[2] else 0
        new_credits = round(
            current_credits + float(amount) * settings.DONATION_MULTIPLIER, 2
        )  # 捐赠金额的倍数作为积分

        # 更新捐赠金额
        success = db.update_user_donation(new_donation, tg_id)

        if success:
            # 更新积分
            db.update_user_credits(new_credits, tg_id=tg_id)

            # 获取用户显示名称
            user_name = get_user_name_from_tg_id(tg_id)

            logger.info(
                f"管理员 {user.username or user.id} 为用户 {user_name}({tg_id}) 添加捐赠记录: {amount}元"
                + (f", 备注: {note}" if note else "")
            )

            # 发送通知给用户
            try:
                await send_message_by_url(
                    chat_id=tg_id,
                    text=f"""
感谢您的捐赠！

💰 本次捐赠: {amount}元
💳 累计捐赠: {new_donation}元
"""
                    + (f"""📝 备注: {note}""" if note else ""),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning(f"发送捐赠通知失败: {str(e)}")

            # 检查并授予至尊贡献者勋章（异步后台任务）
            from app.databases.db_func import (
                check_and_award_supreme_contributor_badge,
            )

            asyncio.create_task(check_and_award_supreme_contributor_badge(tg_id))

            return BaseResponse(
                success=True, message=f"成功为 {user_name} 添加 {amount}元 捐赠记录"
            )
        else:
            return BaseResponse(success=False, message="更新捐赠记录失败")

    except Exception as e:
        logger.error(f"提交捐赠记录失败: {str(e)}")
        return BaseResponse(success=False, message="提交失败")


# ==================== 线路标签管理 API ==================== #


@router.post("/line_tags", response_model=BaseResponse)
@require_telegram_auth
async def set_line_tags(
    request: Request,
    data: LineTagRequest = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置线路标签（管理员功能）"""
    check_admin_permission(user)

    try:
        # 使用数据库函数设置标签
        success = db.set_line_tags(data.line_name, data.tags)

        if success:
            logger.info(
                f"管理员 {user.username or user.id} 设置线路 {data.line_name} 的标签: {data.tags}"
            )
            return BaseResponse(
                success=True, message=f"线路 {data.line_name} 的标签设置成功"
            )
        else:
            return BaseResponse(success=False, message="设置标签失败")
    except Exception as e:
        logger.error(f"设置线路标签失败: {str(e)}")
        return BaseResponse(success=False, message="设置标签失败")


@router.get("/line_tags/{line_name}", response_model=LineTagResponse)
@require_telegram_auth
async def get_line_tags_admin(
    line_name: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取指定线路的标签（管理员功能）"""
    check_admin_permission(user)

    try:
        tags = db.get_line_tags(line_name)
        return LineTagResponse(line_name=line_name, tags=tags)
    except Exception as e:
        logger.error(f"获取线路标签失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取标签失败")


@router.get("/all_line_tags", response_model=AllLineTagsResponse)
@require_telegram_auth
async def get_all_line_tags(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取所有线路的标签信息（管理员功能）"""
    check_admin_permission(user)

    try:
        # 获取所有线路名称
        all_lines = set()
        all_lines.update(settings.STREAM_BACKEND)
        all_lines.update(settings.PREMIUM_STREAM_BACKEND)

        # 获取每个线路的标签
        lines_tags = {}
        for line in all_lines:
            tags = db.get_line_tags(line)
            lines_tags[line] = tags

        return AllLineTagsResponse(lines=lines_tags)
    except Exception as e:
        logger.error(f"获取所有线路标签失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取所有标签失败")


@router.delete("/line_tags/{line_name}", response_model=BaseResponse)
@require_telegram_auth
async def delete_line_tags(
    line_name: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """删除指定线路的所有标签（管理员功能）"""
    check_admin_permission(user)

    try:
        # 检查标签是否存在
        existing_tags = db.get_line_tags(line_name)
        if existing_tags:
            success = db.delete_line_tags(line_name)
            if success:
                logger.info(
                    f"管理员 {user.username or user.id} 删除线路 {line_name} 的所有标签"
                )
                return BaseResponse(
                    success=True, message=f"线路 {line_name} 的标签已清空"
                )
            else:
                return BaseResponse(success=False, message="删除标签失败")
        else:
            return BaseResponse(success=True, message=f"线路 {line_name} 没有设置标签")
    except Exception as e:
        logger.error(f"删除线路标签失败: {str(e)}")
        return BaseResponse(success=False, message="删除标签失败")


@router.post("/settings/invitation-credits")
@require_telegram_auth
async def set_invitation_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置邀请码生成所需积分"""
    check_admin_permission(user)

    try:
        credits = data.get("credits", 288)

        # 验证积分值的合理性
        if not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        settings.INVITATION_CREDITS = credits
        settings.save_config_to_env_file({"INVITATION_CREDITS": str(credits)})

        logger.info(
            f"管理员 {user.username or user.id} 设置邀请码生成所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"邀请码生成所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置邀请码积分失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/unlock-credits")
@require_telegram_auth
async def set_unlock_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置解锁NSFW所需积分"""
    check_admin_permission(user)

    try:
        credits = data.get("credits", 100)

        # 验证积分值的合理性
        if not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        settings.UNLOCK_CREDITS = credits
        settings.save_config_to_env_file({"UNLOCK_CREDITS": str(credits)})

        logger.info(
            f"管理员 {user.username or user.id} 设置解锁 NSFW 所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"解锁 NSFW 所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置解锁积分失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/premium-daily-credits")
@require_telegram_auth
async def set_premium_daily_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置解锁 Premium 每日所需积分"""
    check_admin_permission(user)

    try:
        credits = data.get("credits", 15)

        # 验证积分值的合理性
        if not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        settings.PREMIUM_DAILY_CREDITS = credits
        settings.save_config_to_env_file({"PREMIUM_DAILY_CREDITS": str(credits)})

        logger.info(
            f"管理员 {user.username or user.id} 设置解锁 Premium 每日所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"解锁 Premium 每日所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置 Premium 每日积分失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/user-traffic-limit")
@require_telegram_auth
async def set_user_traffic_limit(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置普通用户每日免费 Premium 流量额度"""
    check_admin_permission(user)

    try:
        traffic_limit = data.get("traffic_limit", settings.USER_TRAFFIC_LIMIT)

        if (
            isinstance(traffic_limit, bool)
            or not isinstance(traffic_limit, int)
            or traffic_limit < 0
        ):
            return BaseResponse(success=False, message="流量额度必须是非负整数")

        settings.USER_TRAFFIC_LIMIT = traffic_limit
        settings.save_config_to_env_file({"USER_TRAFFIC_LIMIT": str(traffic_limit)})

        logger.info(
            f"管理员 {user.username or user.id} 设置普通用户每日免费 Premium 流量额度为: {traffic_limit} 字节"
        )
        return BaseResponse(
            success=True,
            message=f"普通用户每日免费 Premium 流量额度已设置为 {traffic_limit} 字节",
        )
    except Exception as e:
        logger.error(f"设置普通用户每日免费 Premium 流量额度失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/premium-user-traffic-limit")
@require_telegram_auth
async def set_premium_user_traffic_limit(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置高级用户每日免费 Premium 流量额度"""
    check_admin_permission(user)

    try:
        traffic_limit = data.get("traffic_limit", settings.PREMIUM_USER_TRAFFIC_LIMIT)

        if (
            isinstance(traffic_limit, bool)
            or not isinstance(traffic_limit, int)
            or traffic_limit < 0
        ):
            return BaseResponse(success=False, message="流量额度必须是非负整数")

        settings.PREMIUM_USER_TRAFFIC_LIMIT = traffic_limit
        settings.save_config_to_env_file(
            {"PREMIUM_USER_TRAFFIC_LIMIT": str(traffic_limit)}
        )

        logger.info(
            f"管理员 {user.username or user.id} 设置高级用户每日免费 Premium 流量额度为: {traffic_limit} 字节"
        )
        return BaseResponse(
            success=True,
            message=f"高级用户每日免费 Premium 流量额度已设置为 {traffic_limit} 字节",
        )
    except Exception as e:
        logger.error(f"设置高级用户每日免费 Premium 流量额度失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/premium-unlock-enabled")
@require_telegram_auth
async def set_premium_unlock_enabled(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置 Premium 解锁开放状态"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        settings.PREMIUM_UNLOCK_ENABLED = bool(enabled)
        settings.save_config_to_env_file(
            {"PREMIUM_UNLOCK_ENABLED": str(enabled).lower()}
        )

        logger.info(
            f"管理员 {user.username or user.id} 设置 Premium 解锁开放状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"Premium 解锁已{'开放' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置 Premium 解锁开放状态失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/credits-transfer-enabled")
@require_telegram_auth
async def set_credits_transfer_enabled(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置积分转移功能开关"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        settings.CREDITS_TRANSFER_ENABLED = bool(enabled)
        settings.save_config_to_env_file(
            {"CREDITS_TRANSFER_ENABLED": str(enabled).lower()}
        )

        logger.info(
            f"管理员 {user.username or user.id} 设置积分转移功能状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"积分转移功能已{'开启' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置积分转移功能状态失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/line-schedule-unlock-credits")
@require_telegram_auth
async def set_line_schedule_unlock_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置解锁线路调度功能所需积分"""
    check_admin_permission(user)

    try:
        credits = data.get("credits", settings.LINE_SCHEDULE_UNLOCK_CREDITS)

        # 验证积分值的合理性
        if not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        settings.LINE_SCHEDULE_UNLOCK_CREDITS = credits
        settings.save_config_to_env_file({"LINE_SCHEDULE_UNLOCK_CREDITS": str(credits)})

        logger.info(
            f"管理员 {user.username or user.id} 设置解锁线路调度功能所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"解锁线路调度功能所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置解锁线路调度功能积分失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/download-unlock-credits")
@require_telegram_auth
async def set_download_unlock_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置解锁下载/同步功能所需积分"""
    check_admin_permission(user)

    try:
        credits = data.get("credits", settings.DOWNLOAD_UNLOCK_CREDITS)

        # 验证积分值的合理性
        if not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        settings.DOWNLOAD_UNLOCK_CREDITS = credits
        settings.save_config_to_env_file({"DOWNLOAD_UNLOCK_CREDITS": str(credits)})

        logger.info(
            f"管理员 {user.username or user.id} 设置解锁下载/同步功能所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"解锁下载/同步功能所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置解锁下载/同步功能积分失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.get("/lines")
@require_telegram_auth
async def get_lines_config(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取所有线路配置（通用，同时支持Plex和Emby）"""
    check_admin_permission(user)

    try:
        lines_data = {
            "normal_lines": settings.STREAM_BACKEND,
            "premium_lines": settings.PREMIUM_STREAM_BACKEND,
        }

        logger.info(f"管理员 {user.username or user.id} 获取线路配置")
        return lines_data
    except Exception as e:
        logger.error(f"获取线路配置失败: {str(e)}")
        return BaseResponse(success=False, message="获取线路配置失败")


@router.post("/lines/normal")
@require_telegram_auth
async def add_normal_line_generic(
    request: Request,
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """添加普通线路（通用，同时支持Plex和Emby）"""
    check_admin_permission(user)

    try:
        line_name = data.get("line_name", "").strip()
        if not line_name:
            return BaseResponse(success=False, message="线路名称不能为空")

        if line_name in settings.STREAM_BACKEND:
            return BaseResponse(success=False, message="该普通线路已存在")

        if line_name in settings.PREMIUM_STREAM_BACKEND:
            return BaseResponse(success=False, message="该线路已存在于高级线路中")

        # 添加到普通线路列表
        new_lines = settings.STREAM_BACKEND + [line_name]
        settings.STREAM_BACKEND = new_lines
        # 保存时使用通用的环境变量名
        settings.save_config_to_env_file({"STREAM_BACKEND": ",".join(new_lines)})

        logger.info(f"管理员 {user.username or user.id} 添加普通线路: {line_name}")

        # 发送频道通知
        if settings.TG_CHANNEL_ID:
            channel_notification = f"""🎉 新线路上线通知

🌐 线路: {line_name}
⭐ 类型: 普通线路

"""
            background_tasks.add_task(
                send_message_by_url,
                chat_id=settings.TG_CHANNEL_ID,
                text=channel_notification,
            )

        return BaseResponse(success=True, message=f"普通线路 '{line_name}' 添加成功")
    except Exception as e:
        logger.error(f"添加普通线路失败: {str(e)}")
        return BaseResponse(success=False, message="添加普通线路失败")


@router.post("/lines/premium")
@require_telegram_auth
async def add_premium_line_generic(
    request: Request,
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """添加高级线路（通用，同时支持Plex和Emby）"""
    check_admin_permission(user)

    try:
        line_name = data.get("line_name", "").strip()
        if not line_name:
            return BaseResponse(success=False, message="线路名称不能为空")

        if line_name in settings.PREMIUM_STREAM_BACKEND:
            return BaseResponse(success=False, message="该高级线路已存在")

        if line_name in settings.STREAM_BACKEND:
            return BaseResponse(success=False, message="该线路已存在于普通线路中")

        # 添加到高级线路列表
        new_lines = settings.PREMIUM_STREAM_BACKEND + [line_name]
        settings.PREMIUM_STREAM_BACKEND = new_lines
        # 保存时使用通用的环境变量名
        settings.save_config_to_env_file(
            {"PREMIUM_STREAM_BACKEND": ",".join(new_lines)}
        )

        logger.info(f"管理员 {user.username or user.id} 添加高级线路: {line_name}")

        # 发送频道通知
        if settings.TG_CHANNEL_ID:
            channel_notification = f"""🎉 新线路上线通知

🌐 线路: {line_name}
⭐ 类型: Premium 线路

"""
            background_tasks.add_task(
                send_message_by_url,
                chat_id=settings.TG_CHANNEL_ID,
                text=channel_notification,
            )

        return BaseResponse(success=True, message=f"高级线路 '{line_name}' 添加成功")
    except Exception as e:
        logger.error(f"添加高级线路失败: {str(e)}")
        return BaseResponse(success=False, message="添加高级线路失败")


@router.delete("/lines/normal/{line_name}")
@require_telegram_auth
async def delete_normal_line_generic(
    line_name: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """删除普通线路（通用，同时支持Plex和Emby）"""
    check_admin_permission(user)

    try:
        if line_name not in settings.STREAM_BACKEND:
            return BaseResponse(success=False, message="该普通线路不存在")

        # 从普通线路列表中移除
        new_lines = [line for line in settings.STREAM_BACKEND if line != line_name]
        settings.STREAM_BACKEND = new_lines
        # 保存时使用通用的环境变量名
        settings.save_config_to_env_file({"STREAM_BACKEND": ",".join(new_lines)})

        # 删除该线路的标签（如果有）
        db.delete_line_tags(line_name)
        # 解绑所有绑定了该线路的用户
        await unbind_specified_line_for_all_users(line_name)
        # 禁用该线路的所有调度并通知用户
        await disable_line_schedules_and_notify(line_name, "线路已被管理员下线")

        logger.info(f"管理员 {user.username or user.id} 删除普通线路: {line_name}")
        return BaseResponse(success=True, message=f"普通线路 '{line_name}' 删除成功")
    except Exception as e:
        logger.error(f"删除普通线路失败: {str(e)}")
        return BaseResponse(success=False, message="删除普通线路失败")


@router.delete("/lines/premium/{line_name}")
@require_telegram_auth
async def delete_premium_line_generic(
    line_name: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """删除高级线路（通用，同时支持Plex和Emby）"""
    check_admin_permission(user)

    try:
        if line_name not in settings.PREMIUM_STREAM_BACKEND:
            return BaseResponse(success=False, message="该高级线路不存在")

        # 从高级线路列表中移除
        new_lines = [
            line for line in settings.PREMIUM_STREAM_BACKEND if line != line_name
        ]
        settings.PREMIUM_STREAM_BACKEND = new_lines
        # 保存时使用通用的环境变量名
        settings.save_config_to_env_file(
            {"PREMIUM_STREAM_BACKEND": ",".join(new_lines)}
        )

        # 从免费高级线路列表中移除（如果存在）
        free_premium_lines = db.get_free_premium_lines()
        if line_name in free_premium_lines:
            free_premium_lines.remove(line_name)
            db.set_free_premium_lines(free_premium_lines)

        # 删除该线路的标签（如果有）
        db.delete_line_tags(line_name)

        # 处理绑定了该线路的用户
        await unbind_specified_line_for_all_users(line_name)
        # 禁用该线路的所有调度并通知用户
        await disable_line_schedules_and_notify(line_name, "高级线路已被管理员下线")

        logger.info(f"管理员 {user.username or user.id} 删除高级线路: {line_name}")
        return BaseResponse(success=True, message=f"高级线路 '{line_name}' 删除成功")
    except Exception as e:
        logger.error(f"删除高级线路失败: {str(e)}")
        return BaseResponse(success=False, message="删除高级线路失败")


# 为兼容性保留原来的Emby特定端点
@router.get("/emby-lines")
@require_telegram_auth
async def get_emby_lines(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取所有Emby线路配置（兼容性接口，推荐使用 /lines）"""
    return await get_lines_config(request, user)


@router.post("/emby-lines/normal")
@require_telegram_auth
async def add_normal_line(
    request: Request,
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """添加普通线路（兼容性接口，推荐使用 /lines/normal）"""
    return await add_normal_line_generic(request, background_tasks, data, user)


@router.post("/emby-lines/premium")
@require_telegram_auth
async def add_premium_line(
    request: Request,
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """添加高级线路（兼容性接口，推荐使用 /lines/premium）"""
    return await add_premium_line_generic(request, background_tasks, data, user)


@router.delete("/emby-lines/normal/{line_name}")
@require_telegram_auth
async def delete_normal_line(
    line_name: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """删除普通线路（兼容性接口，推荐使用 /lines/normal/{line_name}）"""
    return await delete_normal_line_generic(line_name, request, user)


@router.delete("/emby-lines/premium/{line_name}")
@require_telegram_auth
async def delete_premium_line(
    line_name: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """删除高级线路（兼容性接口，推荐使用 /lines/premium/{line_name}）"""
    return await delete_premium_line_generic(line_name, request, user)


@router.post("/invite-codes/generate")
@require_telegram_auth
async def generate_admin_invite_codes(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员生成邀请码"""
    check_admin_permission(user)

    try:
        tg_id = data.get("tg_id")
        count = data.get("count", 1)
        is_premium = data.get("is_premium", False)
        note = data.get("note", "")

        if not tg_id or count <= 0 or count > 100:
            return BaseResponse(success=False, message="参数错误")

        # 导入生成邀请码的函数
        from app.databases.db_func import add_redeem_code

        # 检查目标用户是否存在
        stats_info = db.get_stats_by_tg_id(tg_id)
        if not stats_info:
            return BaseResponse(success=False, message="目标用户不存在")

        # 使用 add_redeem_code 生成邀请码
        try:
            add_redeem_code(tg_id=tg_id, num=count, is_privileged=is_premium)
            success_count = count
        except Exception as e:
            logger.error(f"生成邀请码失败: {str(e)}")
            return BaseResponse(success=False, message=f"生成邀请码失败: {str(e)}")

        # 获取用户显示名称
        user_name = get_user_name_from_tg_id(tg_id)

        logger.info(
            f"管理员 {user.username or user.id} 为用户 {user_name}({tg_id}) 生成了 {success_count} 个{'特权' if is_premium else '普通'}邀请码"
            + (f", 备注: {note}" if note else "")
        )

        # 发送通知给用户
        try:
            await send_message_by_url(
                chat_id=tg_id,
                text=f"""
🎫 管理员为您生成了{"特权" if is_premium else "普通"}邀请码！

📊 生成数量: {success_count} 个

您可以在面板中查看完整的邀请码列表。
"""
                + (f"""📝 备注: {note}""" if note else ""),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"发送邀请码通知失败: {str(e)}")

        message = f"成功为 {user_name} 生成 {success_count} 个{'特权' if is_premium else '普通'}邀请码"

        return BaseResponse(success=True, message=message)

    except Exception as e:
        logger.error(f"管理员生成邀请码失败: {str(e)}")
        return BaseResponse(success=False, message=f"生成邀请码失败: {str(e)}")


# ==================== 自定义线路管理接口 ====================


@router.get("/custom-lines")
@require_telegram_auth
async def get_all_custom_lines(
    request: Request,
    status: str = None,
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员获取所有自定义线路列表（可按状态过滤）"""
    check_admin_permission(user)

    try:
        import json

        from app.databases.session import get_session
        from app.models.models import CustomLine
        from app.webapp.schemas import CustomLineInfo, CustomLineListResponse
        from sqlalchemy import select

        with get_session() as session:
            stmt = select(CustomLine)

            # 按状态过滤
            if status:
                if status not in ["pending", "approved", "rejected", "expired"]:
                    return CustomLineListResponse(
                        success=False, message="无效的状态", lines=[], total=0
                    )
                stmt = stmt.where(CustomLine.status == status)

            stmt = stmt.order_by(CustomLine.created_at.desc())
            result = session.execute(stmt)
            lines = result.scalars().all()

            lines_data = [
                CustomLineInfo(
                    id=line.id,
                    tg_id=line.tg_id,
                    domain=line.domain,
                    network_info=line.network_info,
                    price_monthly=line.price_monthly,
                    price_yearly=line.price_yearly,
                    traffic_limit=line.traffic_limit,
                    traffic_type=line.traffic_type,
                    valid_days=line.valid_days,
                    is_permanent=bool(line.is_permanent),
                    status=line.status,
                    admin_note=line.admin_note,
                    user_note=line.user_note,
                    tags=(
                        json.loads(line.tags)
                        if isinstance(line.tags, str) and line.tags
                        else (line.tags or [])
                    ),
                    approved_at=line.approved_at,
                    approved_by=line.approved_by,
                    expires_at=line.expires_at,
                    created_at=line.created_at,
                    updated_at=line.updated_at,
                    total_traffic=line.total_traffic,
                )
                for line in lines
            ]

            return CustomLineListResponse(
                success=True,
                message="获取成功",
                lines=lines_data,
                total=len(lines_data),
            )

    except Exception as e:
        logger.error(f"获取自定义线路列表失败: {e}")
        from app.webapp.schemas import CustomLineListResponse

        return CustomLineListResponse(
            success=False, message=f"获取失败: {str(e)}", lines=[], total=0
        )


@router.post("/custom-lines/{line_id}/approve")
@require_telegram_auth
async def approve_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员审批自定义线路（批准或拒绝）"""
    check_admin_permission(user)

    try:
        from time import time

        from app.databases.session import get_session
        from app.models.models import CustomLine
        from app.webapp.schemas import BaseResponse, CustomLineApproveRequest
        from sqlalchemy import select

        # 解析请求数据
        approve_req = CustomLineApproveRequest(**data)

        if approve_req.action not in ["approve", "reject"]:
            return BaseResponse(success=False, message="无效的操作")

        admin_id = user.id
        current_time = int(time())

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 只能审批 pending 状态的线路
            if line.status != "pending":
                return BaseResponse(
                    success=False,
                    message=f"只能审批待审核的线路，当前状态: {line.status}",
                )

            domain = line.domain
            submitter_id = line.tg_id
            submitter_name = get_user_name_from_tg_id(submitter_id)

            if approve_req.action == "approve":
                line.status = "approved"
                line.approved_at = current_time
                line.approved_by = admin_id

                # 管理员可以覆盖用户提交的有效期设置
                if approve_req.is_permanent is not None:
                    line.is_permanent = 1 if approve_req.is_permanent else 0
                if approve_req.valid_days is not None:
                    line.valid_days = approve_req.valid_days

                # 重新计算过期时间
                if line.is_permanent:
                    line.expires_at = None
                elif line.valid_days:
                    line.expires_at = current_time + (line.valid_days * 24 * 60 * 60)

                if approve_req.admin_note:
                    line.admin_note = approve_req.admin_note

                line.updated_at = current_time

                session.commit()

                logger.info(
                    f"管理员 {user.username or user.id} 批准了用户 {submitter_name} 的自定义线路: {domain}"
                )

                # 通知用户
                traffic_info = (
                    f"{line.traffic_limit} GB" if line.traffic_limit else "无限制"
                )

                user_notification = f"""✅ 您的自定义线路已通过审核

🌐 域名: {line.domain}
📊 流量限制: {traffic_info}
⏰ 有效期: {"长期可用" if line.is_permanent else f"{line.valid_days}天"}
"""
                if approve_req.admin_note:
                    user_notification += f"\n📝 管理员备注: {approve_req.admin_note}"

                background_tasks.add_task(
                    send_message_by_url,
                    chat_id=submitter_id,
                    text=user_notification,
                )

                # 发送频道通知，让其他用户知晓新线路
                if settings.TG_CHANNEL_ID:
                    channel_notification = f"""🎉 新线路上线通知

🌐 线路: {line.domain}
🌍 网络信息: {line.network_info or "未提供"}
📊 流量限制: {traffic_info}
⏰ 有效期: {"长期可用" if line.is_permanent else f"{line.valid_days} 天"}

感谢 {submitter_name} 分享线路！"""

                    background_tasks.add_task(
                        send_message_by_url,
                        chat_id=settings.TG_CHANNEL_ID,
                        text=channel_notification,
                    )

                return BaseResponse(success=True, message=f"已批准线路: {domain}")

            else:  # reject
                line.status = "rejected"
                if approve_req.admin_note:
                    line.admin_note = approve_req.admin_note
                line.updated_at = current_time

                session.commit()

                logger.info(
                    f"管理员 {user.username or user.id} 拒绝了用户 {submitter_name} 的自定义线路: {domain}"
                )

                # 通知用户
                user_notification = f"""❌ 您的自定义线路未通过审核

🌐 域名: {line.domain}
"""
                if approve_req.admin_note:
                    user_notification += f"\n📝 拒绝原因: {approve_req.admin_note}"

                background_tasks.add_task(
                    send_message_by_url,
                    chat_id=submitter_id,
                    text=user_notification,
                )

                return BaseResponse(success=True, message=f"已拒绝线路: {domain}")

    except Exception as e:
        logger.error(f"审批自定义线路失败: {e}")
        from app.webapp.schemas import BaseResponse

        return BaseResponse(success=False, message=f"审批失败: {str(e)}")


@router.put("/custom-lines/{line_id}")
@require_telegram_auth
async def admin_update_custom_line(
    request: Request,
    line_id: int,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员更新自定义线路"""
    check_admin_permission(user)

    try:
        from time import time

        from app.databases.session import get_session
        from app.models.models import CustomLine
        from app.webapp.schemas import AdminCustomLineUpdateRequest, BaseResponse
        from sqlalchemy import select

        # 解析请求数据
        update_req = AdminCustomLineUpdateRequest(**data)

        current_time = int(time())

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 更新字段
            if update_req.domain is not None:
                # 检查新域名是否已被使用（pending、approved 或 offline 状态）
                stmt_check = select(CustomLine).where(
                    CustomLine.domain == update_req.domain,
                    CustomLine.id != line_id,
                    CustomLine.status.in_(["pending", "approved", "offline"]),
                )
                result_check = session.execute(stmt_check)
                if result_check.scalar_one_or_none():
                    return BaseResponse(
                        success=False, message=f"域名 '{update_req.domain}' 已被使用"
                    )
                line.domain = update_req.domain
            if update_req.network_info is not None:
                line.network_info = update_req.network_info
            if update_req.price_monthly is not None:
                line.price_monthly = update_req.price_monthly
            if update_req.price_yearly is not None:
                line.price_yearly = update_req.price_yearly
            if update_req.traffic_limit is not None:
                line.traffic_limit = update_req.traffic_limit
            if update_req.traffic_type is not None:
                if update_req.traffic_type not in ["one_way", "two_way"]:
                    return BaseResponse(success=False, message="无效的流量类型")
                line.traffic_type = update_req.traffic_type
            if update_req.total_traffic is not None:
                line.total_traffic = update_req.total_traffic
            if update_req.valid_days is not None:
                line.valid_days = update_req.valid_days
            if update_req.is_permanent is not None:
                line.is_permanent = 1 if update_req.is_permanent else 0
            if update_req.admin_note is not None:
                line.admin_note = update_req.admin_note
            if update_req.status is not None:
                if update_req.status not in [
                    "pending",
                    "approved",
                    "rejected",
                    "expired",
                ]:
                    return BaseResponse(success=False, message="无效的状态")
                line.status = update_req.status

            # 重新计算过期时间
            if update_req.is_permanent is not None or update_req.valid_days is not None:
                if line.is_permanent:
                    line.expires_at = None
                elif line.valid_days:
                    # 如果线路已批准，从批准时间开始计算
                    base_time = line.approved_at if line.approved_at else current_time
                    line.expires_at = base_time + (line.valid_days * 24 * 60 * 60)

            line.updated_at = current_time

            session.commit()

            logger.info(
                f"管理员 {user.username or user.id} 更新了自定义线路: {line.domain}"
            )

            return BaseResponse(success=True, message="更新成功")

    except Exception as e:
        logger.error(f"管理员更新自定义线路失败: {e}")
        from app.webapp.schemas import BaseResponse

        return BaseResponse(success=False, message=f"更新失败: {str(e)}")


@router.post("/custom-lines/{line_id}/offline")
@require_telegram_auth
async def admin_offline_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员下线自定义线路"""
    check_admin_permission(user)

    try:
        from time import time

        from app.databases.session import get_session
        from app.models.models import CustomLine
        from app.webapp.schemas import BaseResponse
        from sqlalchemy import select

        current_time = int(time())

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 只能下线已批准的线路
            if line.status != "approved":
                return BaseResponse(
                    success=False,
                    message=f"只能下线已批准的线路，当前状态: {line.status}",
                )

            domain = line.domain
            submitter_id = line.tg_id
            submitter_name = get_user_name_from_tg_id(submitter_id)

            # 解绑所有使用该线路的用户
            logger.info(f"管理员下线线路 {domain}，开始解绑所有用户")
            try:
                success, unbind_count = await unbind_specified_line_for_all_users(
                    domain, "已被管理员下线"
                )
                if success and unbind_count > 0:
                    logger.info(f"已解绑 {unbind_count} 个用户的线路 {domain}")
            except Exception as e:
                logger.error(f"解绑用户失败: {e}")

            # 更新状态为 offline
            line.status = "offline"
            line.updated_at = current_time

            session.commit()

            logger.info(
                f"管理员 {user.username or user.id} 下线了用户 {submitter_name} 的自定义线路: {domain}"
            )

            # 通知用户
            user_notification = f"""📢 您的自定义线路已被管理员下线

🌐 域名: {line.domain}

您可以随时重新上线该线路。
如有疑问，请联系管理员。"""

            background_tasks.add_task(
                send_message_by_url,
                chat_id=submitter_id,
                text=user_notification,
            )

            return BaseResponse(success=True, message=f"已下线线路: {domain}")

    except Exception as e:
        logger.error(f"管理员下线自定义线路失败: {e}")
        from app.webapp.schemas import BaseResponse

        return BaseResponse(success=False, message=f"下线失败: {str(e)}")


@router.delete("/custom-lines/{line_id}")
@require_telegram_auth
async def admin_delete_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员删除自定义线路（从数据库中删除，可删除任何状态的线路）"""
    check_admin_permission(user)

    try:
        from app.databases.session import get_session
        from app.models.models import CustomLine
        from app.modules.custom_line import settle_custom_line_traffic
        from app.webapp.schemas import BaseResponse
        from sqlalchemy import select

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            domain = line.domain
            submitter_id = line.tg_id
            submitter_name = get_user_name_from_tg_id(submitter_id)
            line_status = line.status

            # 如果线路已批准，先解绑所有用户
            if line_status == "approved":
                logger.info(f"线路 {domain} 状态为 {line_status}，开始解绑所有用户")
                try:
                    success, unbind_count = await unbind_specified_line_for_all_users(
                        domain, "已被管理员删除"
                    )
                    if success and unbind_count > 0:
                        logger.info(f"已解绑 {unbind_count} 个用户的线路 {domain}")
                except Exception as e:
                    logger.error(f"解绑用户失败: {e}")

            # 立即结算当月流量积分
            logger.info(f"开始为删除的线路 {domain} 结算当月流量积分")
            try:
                await settle_custom_line_traffic(
                    line_domain=domain, force_current_month=True
                )
                logger.info(f"线路 {domain} 当月流量结算完成")
            except Exception as e:
                logger.error(f"结算线路 {domain} 流量失败: {e}")

            session.delete(line)
            session.commit()

            logger.info(
                f"管理员 {user.username or user.id} 删除了用户 {submitter_name} 的自定义线路: {domain} (原状态: {line_status})"
            )

            # 通知用户
            user_notification = f"""⚠️ 您的自定义线路已被管理员删除

🌐 域名: {line.domain}

如有疑问，请联系管理员。"""

            background_tasks.add_task(
                send_message_by_url,
                chat_id=submitter_id,
                text=user_notification,
            )

            return BaseResponse(success=True, message=f"已删除线路: {domain}")

    except Exception as e:
        logger.error(f"管理员删除自定义线路失败: {e}")
        from app.webapp.schemas import BaseResponse

        return BaseResponse(success=False, message=f"删除失败: {str(e)}")


@router.post("/custom-lines/{line_id}/tags")
@require_telegram_auth
async def admin_set_custom_line_tags(
    request: Request,
    line_id: int,
    tags: list[str],
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员设置自定义线路的标签"""
    check_admin_permission(user)

    try:
        from datetime import datetime

        from app.databases.session import get_session
        from app.models.models import CustomLine
        from app.webapp.schemas import BaseResponse
        from sqlalchemy import select

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 更新标签
            line.tags = tags if tags else []
            line.updated_at = int(datetime.now().timestamp())

            session.commit()

            logger.info(
                f"管理员 {user.username or user.id} 为自定义线路 {line.domain} 设置标签: {tags}"
            )

            return BaseResponse(
                success=True, message="已更新线路标签", data={"tags": tags}
            )

    except Exception as e:
        logger.error(f"管理员设置自定义线路标签失败: {e}")
        from app.webapp.schemas import BaseResponse

        return BaseResponse(success=False, message=f"设置标签失败: {str(e)}")
