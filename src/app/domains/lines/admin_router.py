from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.databases import db
from app.domains.lines import service as lines_service
from app.domains.lines.service import (
    disable_line_schedules_and_notify,
    unbind_specified_line_for_all_users,
)
from app.domains.profile.schemas import (
    AllLineTagsResponse,
    LineTagRequest,
    LineTagResponse,
)
from app.integrations.telegram.messaging import send_message_by_url
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
        logger.error(f"设置线路标签失败: {e!s}")
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
        logger.error(f"获取线路标签失败: {e!s}")
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
        logger.error(f"获取所有线路标签失败: {e!s}")
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
        logger.error(f"删除线路标签失败: {e!s}")
        return BaseResponse(success=False, message="删除标签失败")


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
        credits = data.get("credits", lines_service.get_line_schedule_unlock_credits())

        # 验证积分值的合理性
        if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        lines_service.set_line_schedule_unlock_credits(credits)

        logger.info(
            f"管理员 {user.username or user.id} 设置解锁线路调度功能所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"解锁线路调度功能所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置解锁线路调度功能积分失败: {e!s}")
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
        logger.error(f"获取线路配置失败: {e!s}")
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
        logger.error(f"添加普通线路失败: {e!s}")
        return BaseResponse(success=False, message="添加普通线路失败")


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
        logger.error(f"删除普通线路失败: {e!s}")
        return BaseResponse(success=False, message="删除普通线路失败")


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


@router.delete("/emby-lines/normal/{line_name}")
@require_telegram_auth
async def delete_normal_line(
    line_name: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """删除普通线路（兼容性接口，推荐使用 /lines/normal/{line_name}）"""
    return await delete_normal_line_generic(line_name, request, user)
