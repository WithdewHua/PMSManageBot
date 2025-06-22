from app.cache import (
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
    free_premium_lines_cache,
    get_line_tags,
    line_tags_cache,
    plex_last_user_defined_line_cache,
    plex_user_defined_line_cache,
)
from app.config import settings
from app.db import DB
from app.log import uvicorn_logger as logger
from app.utils import (
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

    if user.id not in settings.ADMIN_CHAT_ID:
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
        # 从Redis缓存获取免费高级线路列表
        from app.cache import free_premium_lines_cache

        free_premium_lines = free_premium_lines_cache.get("free_lines")
        free_premium_lines = free_premium_lines.split(",") if free_premium_lines else []

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
            "credits_transfer_enabled": settings.CREDITS_TRANSFER_ENABLED,  # 添加积分转移开关
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

        # 保存到 Redis 缓存
        old_free_lines = free_premium_lines_cache.get("free_lines")
        old_free_lines = old_free_lines.split(",") if old_free_lines else []
        free_premium_lines_cache.put("free_lines", ",".join(free_lines))

        removed_lines = set(old_free_lines) - set(free_lines)
        # 处理现有用户的线路绑定 - 如果某些原本免费的线路被移除，需要处理
        logger.info("增加免费高级线路变更处理任务")
        background_tasks.add_task(handle_free_premium_lines_change, removed_lines)

        logger.info(
            f"管理员 {user.username or user.id} 设置免费高级线路为: {free_lines}"
        )
        return BaseResponse(
            success=True, message=f"免费高级线路设置已更新，共 {len(free_lines)} 条线路"
        )
    except Exception as e:
        logger.error(f"设置免费高级线路失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/emby-free-premium-lines")
@require_telegram_auth
async def set_emby_free_premium_lines(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置免费的Emby高级线路列表（兼容性接口，推荐使用 /settings/free-premium-lines）"""
    return await set_free_premium_lines(request, data, user)


async def unbind_emby_premium_free():
    """解绑所有 Emby Premium Free（恢复普通用户）"""

    if settings.PREMIUM_FREE:
        logger.info("Emby Premium Free 功能未启用，跳过解绑操作")
        return True, None
    db = DB()
    try:
        # 获取所有绑定了 Emby 线路的用户
        users = db.get_emby_user_with_binded_line()
        for user in users:
            emby_username, tg_id, emby_line, is_premium = user
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
            db.set_emby_line(last_line, tg_id=tg_id)
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
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


async def unbind_plex_premium_free():
    """解绑所有 Plex Premium Free（恢复普通用户）"""

    if settings.PREMIUM_FREE:
        logger.info("Plex Premium Free 功能未启用，跳过解绑操作")
        return True, None
    db = DB()
    try:
        # 获取所有绑定了 Plex 线路的用户
        users = db.get_plex_user_with_binded_line()
        for user in users:
            plex_username, tg_id, plex_line, is_premium = user
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
            db.set_plex_line(last_line, tg_id=tg_id)
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
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


async def handle_free_premium_lines_change(removed_lines: list | set):
    """处理免费高级线路变更，检查并处理不再免费的线路"""
    db = DB()
    try:
        if not removed_lines:
            return True, None

        # 获取所有绑定了被移除线路的普通用户
        users = db.get_emby_user_with_binded_line()
        for user in users:
            emby_username, tg_id, emby_line, is_premium = user
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
            db.set_emby_line(last_line, tg_id=tg_id)
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
            plex_username, tg_id, plex_line, is_premium = user
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
            db.set_plex_line(last_line, tg_id=tg_id)
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

        return True, None
    except Exception as e:
        logger.error(f"处理免费高级线路变更时发生错误: {str(e)}")
        return False, f"处理免费高级线路变更时发生错误: {str(e)}"
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


async def unbind_specified_line_for_all_users(line: str):
    """解绑所有用户的指定线路（通用，同时支持Plex和Emby）"""
    db = DB()
    try:
        # 获取所有绑定了 Emby 线路的用户
        emby_users = db.get_emby_user_with_binded_line()
        for user in emby_users:
            emby_username, tg_id, user_emby_line, _ = user
            if line in user_emby_line:
                # 如果用户绑定的线路是指定的线路，解绑
                db.set_emby_line(line=None, tg_id=tg_id)
                emby_user_defined_line_cache.delete(str(emby_username).lower())
                emby_last_user_defined_line_cache.delete(str(emby_username).lower())
                # 发送通知给用户
                if tg_id:
                    await send_message_by_url(
                        chat_id=tg_id,
                        text=f"通知：您绑定的 Emby 线路 `{line}` 已被管理员下线，已切换为 `AUTO`",
                        parse_mode="markdownv2",
                    )

        # 处理Plex用户解绑逻辑
        plex_users = db.get_plex_user_with_binded_line()
        for user in plex_users:
            plex_username, tg_id, user_plex_line, _ = user
            if line in user_plex_line:
                # 如果用户绑定的线路是指定的线路，解绑
                db.set_plex_line(line=None, tg_id=tg_id)
                plex_user_defined_line_cache.delete(str(plex_username).lower())
                plex_last_user_defined_line_cache.delete(str(plex_username).lower())
                # 发送通知给用户
                if tg_id:
                    await send_message_by_url(
                        chat_id=tg_id,
                        text=f"通知：您绑定的 Plex 线路 `{line}` 已被管理员下线，已切换为 `AUTO`",
                        parse_mode="markdownv2",
                    )

        return True, None

    except Exception as e:
        logger.error(f"解绑所有用户的 {line} 线路时发生错误: {str(e)}")
        return False, f"解绑所有用户的 {line} 线路时发生错误: {str(e)}"
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


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

        db = DB()

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

            return BaseResponse(
                success=True, message=f"成功为 {user_name} 添加 {amount}元 捐赠记录"
            )
        else:
            return BaseResponse(success=False, message="更新捐赠记录失败")

    except Exception as e:
        logger.error(f"提交捐赠记录失败: {str(e)}")
        return BaseResponse(success=False, message="提交失败")
    finally:
        db.close()


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
        # 将标签列表转换为逗号分隔的字符串存储到Redis
        tags_str = ",".join(set(data.tags)) if set(data.tags) else ""

        if tags_str:
            line_tags_cache.put(data.line_name, tags_str)
            logger.info(
                f"管理员 {user.username or user.id} 设置线路 {data.line_name} 的标签: {data.tags}"
            )
        else:
            # 如果标签为空，删除该键
            line_tags_cache.delete(data.line_name)
            logger.info(
                f"管理员 {user.username or user.id} 清空线路 {data.line_name} 的标签"
            )

        return BaseResponse(
            success=True, message=f"线路 {data.line_name} 的标签设置成功"
        )
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
        tags = get_line_tags(line_name)
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
            tags = get_line_tags(line)
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
        existing_tags = get_line_tags(line_name)
        if existing_tags:
            line_tags_cache.delete(line_name)
            logger.info(
                f"管理员 {user.username or user.id} 删除线路 {line_name} 的所有标签"
            )
            return BaseResponse(success=True, message=f"线路 {line_name} 的标签已清空")
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
        return BaseResponse(success=True, message=f"普通线路 '{line_name}' 添加成功")
    except Exception as e:
        logger.error(f"添加普通线路失败: {str(e)}")
        return BaseResponse(success=False, message="添加普通线路失败")


@router.post("/lines/premium")
@require_telegram_auth
async def add_premium_line_generic(
    request: Request,
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
        line_tags_cache.delete(line_name)
        # 解绑所有绑定了该线路的用户
        await unbind_specified_line_for_all_users(line_name)

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
        from app.cache import free_premium_lines_cache

        free_premium_lines = free_premium_lines_cache.get("free_lines")
        if free_premium_lines:
            free_lines_list = free_premium_lines.split(",")
            if line_name in free_lines_list:
                free_lines_list.remove(line_name)
                free_premium_lines_cache.put("free_lines", ",".join(free_lines_list))

        # 删除该线路的标签（如果有）
        line_tags_cache.delete(line_name)

        # 处理绑定了该线路的用户
        await unbind_specified_line_for_all_users(line_name)

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
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """添加普通线路（兼容性接口，推荐使用 /lines/normal）"""
    return await add_normal_line_generic(request, data, user)


@router.post("/emby-lines/premium")
@require_telegram_auth
async def add_premium_line(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """添加高级线路（兼容性接口，推荐使用 /lines/premium）"""
    return await add_premium_line_generic(request, data, user)


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
        db = DB()

        tg_id = data.get("tg_id")
        count = data.get("count", 1)
        is_premium = data.get("is_premium", False)
        note = data.get("note", "")

        if not tg_id or count <= 0 or count > 100:
            return BaseResponse(success=False, message="参数错误")

        # 导入生成邀请码的函数
        from app.update_db import add_redeem_code

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
🎫 管理员为您生成了{'特权' if is_premium else '普通'}邀请码！

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
    finally:
        db.close()
