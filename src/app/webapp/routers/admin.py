from app.cache import emby_last_user_defined_line_cache, emby_user_defined_line_cache
from app.config import settings
from app.db import DB
from app.log import uvicorn_logger as logger
from app.utils import send_message_by_url
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import BaseResponse, TelegramUser
from fastapi import APIRouter, Body, Depends, HTTPException, Request

router = APIRouter(prefix="/api/admin", tags=["admin"])


def check_admin_permission(user: TelegramUser):
    """检查用户是否为管理员"""
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
        settings_data = {
            "plex_register": settings.PLEX_REGISTER,
            "emby_register": settings.EMBY_REGISTER,
            "emby_premium_free": settings.EMBY_PREMIUM_FREE,
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

        logger.info(
            f"管理员 {user.username or user.id} 设置 Emby 注册状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"Emby 注册已{'开启' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置 Emby 注册状态失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/emby-premium-free")
@require_telegram_auth
async def set_emby_premium_free(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置Emby高级线路免费使用开关"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        old_status = settings.EMBY_PREMIUM_FREE
        settings.EMBY_PREMIUM_FREE = bool(enabled)

        # 如果从开启变为关闭，需要处理现有用户的高级线路绑定
        if old_status and not enabled:
            # 调用解绑所有普通用户的premium线路的函数
            flag, msg = await unbind_emby_premium_free()
            if not flag:
                return BaseResponse(success=False, message=msg)

        logger.info(
            f"管理员 {user.username or user.id} 设置 Emby 高级线路免费使用状态为: {enabled}"
        )
        return BaseResponse(
            success=True,
            message=f"Emby 高级线路免费使用已{'开启' if enabled else '关闭'}",
        )
    except Exception as e:
        logger.error(f"设置 Emby 高级线路免费使用状态失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


async def unbind_emby_premium_free():
    """解绑所有 Emby Premium Free（恢复普通用户）"""

    if settings.EMBY_PREMIUM_FREE:
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
            is_premium_line = False
            for _line in settings.EMBY_PREMIUM_STREAM_BACKEND:
                if _line in emby_line:
                    is_premium_line = True
                    break
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
                await send_message_by_url(
                    chat_id=tg_id,
                    text=f"通知：高级线路开放通道关闭，您绑定的线路已切换为 `{last_line}`",
                )
            else:
                emby_user_defined_line_cache.delete(str(emby_username).lower())
                await send_message_by_url(
                    chat_id=tg_id,
                    text="通知：高级线路开放通道已关闭，您绑定的线路已切换为 `AUTO`",
                )

        return True, None
    except Exception as e:
        logger.error(f"解绑所有普通用户的 premium 线路时发生错误: {str(e)}")
        return False, f"解绑所有普通用户的 premium 线路时发生错误: {str(e)}"
    finally:
        db.close()
        logger.debug("数据库连接已关闭")
