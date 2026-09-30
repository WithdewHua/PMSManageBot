from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.domains.lines import catalog as line_catalog
from app.domains.lines import service as lines_service
from app.domains.lines.service import (
    disable_line_schedules_and_notify,
    handle_free_premium_lines_change,
    unbind_emby_premium_free,
    unbind_plex_premium_free,
    unbind_specified_line_for_all_users,
)
from app.domains.premium import service as premium_service
from app.domains.traffic import service as traffic_service
from app.integrations.telegram.messaging import send_message_by_url
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
        enabled = bool(data.get("enabled", False))
        old_status = lines_service.is_premium_free_enabled()
        lines_service.set_premium_free(enabled)

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
        logger.error(f"设置高级线路免费使用状态失败: {e!s}")
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
            if line not in line_catalog.premium_lines():
                return BaseResponse(
                    success=False, message=f"线路 {line} 不在高级线路列表中"
                )

        # 保存到数据库
        old_free_lines = line_catalog.free_premium_lines()
        line_catalog.set_free_premium_lines(free_lines)

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
        logger.error(f"设置免费 Premium 线路失败: {e!s}")
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
        credits = data.get("credits", premium_service.get_premium_daily_credits())

        # 验证积分值的合理性
        if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        premium_service.set_premium_daily_credits(credits)

        logger.info(
            f"管理员 {user.username or user.id} 设置解锁 Premium 每日所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"解锁 Premium 每日所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置 Premium 每日积分失败: {e!s}")
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
        traffic_limit = data.get(
            "traffic_limit", traffic_service.get_premium_user_traffic_limit()
        )

        if (
            isinstance(traffic_limit, bool)
            or not isinstance(traffic_limit, int)
            or traffic_limit < 0
        ):
            return BaseResponse(success=False, message="流量额度必须是非负整数")

        traffic_service.set_premium_user_traffic_limit(traffic_limit)

        logger.info(
            f"管理员 {user.username or user.id} 设置高级用户每日免费 Premium 流量额度为: {traffic_limit} 字节"
        )
        return BaseResponse(
            success=True,
            message=f"高级用户每日免费 Premium 流量额度已设置为 {traffic_limit} 字节",
        )
    except Exception as e:
        logger.error(f"设置高级用户每日免费 Premium 流量额度失败: {e!s}")
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
        enabled = bool(data.get("enabled", False))
        premium_service.set_premium_unlock_enabled(enabled)

        logger.info(
            f"管理员 {user.username or user.id} 设置 Premium 解锁开放状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"Premium 解锁已{'开放' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置 Premium 解锁开放状态失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")


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

        if line_name in line_catalog.premium_lines():
            return BaseResponse(success=False, message="该高级线路已存在")

        if line_name in line_catalog.normal_lines():
            return BaseResponse(success=False, message="该线路已存在于普通线路中")

        # 添加到高级线路列表
        line_catalog.add_line(line_name, premium=True)

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
        logger.error(f"添加高级线路失败: {e!s}")
        return BaseResponse(success=False, message="添加高级线路失败")


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
        if line_name not in line_catalog.premium_lines():
            return BaseResponse(success=False, message="该高级线路不存在")

        # 从高级线路列表中移除
        line_catalog.delete_line(line_name, premium=True)

        # 从免费高级线路列表中移除（如果存在）
        free_premium_lines = line_catalog.free_premium_lines()
        if line_name in free_premium_lines:
            free_premium_lines.remove(line_name)
            line_catalog.set_free_premium_lines(free_premium_lines)

        # 删除该线路的标签（如果有）
        line_catalog.delete_line_tags(line_name)

        # 处理绑定了该线路的用户
        await unbind_specified_line_for_all_users(line_name)
        # 禁用该线路的所有调度并通知用户
        await disable_line_schedules_and_notify(line_name, "高级线路已被管理员下线")

        logger.info(f"管理员 {user.username or user.id} 删除高级线路: {line_name}")
        return BaseResponse(success=True, message=f"高级线路 '{line_name}' 删除成功")
    except Exception as e:
        logger.error(f"删除高级线路失败: {e!s}")
        return BaseResponse(success=False, message="删除高级线路失败")


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


@router.delete("/emby-lines/premium/{line_name}")
@require_telegram_auth
async def delete_premium_line(
    line_name: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """删除高级线路（兼容性接口，推荐使用 /lines/premium/{line_name}）"""
    return await delete_premium_line_generic(line_name, request, user)


@router.post("/settings/credits-cost-per-10gb")
@require_telegram_auth
async def set_credits_cost_per_10gb(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置每 10GB 超额流量扣除的积分。"""
    check_admin_permission(user)
    try:
        credits = data.get("credits", premium_service.get_credits_cost_per_10gb())
        if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")
        premium_service.set_credits_cost_per_10gb(credits)
        return BaseResponse(success=True, message=f"每 10GB 流量扣费已设置为 {credits}")
    except Exception as error:
        logger.error(f"设置每 10GB 流量扣费失败: {error!s}")
        return BaseResponse(success=False, message="设置失败")
