"""HTTP adapters for public profile aggregation and user selection."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.core.log import uvicorn_logger as logger
from app.domains.profile import service
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import TelegramUser

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/info")
@require_telegram_auth
async def get_user_info(
    request: Request,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取用户信息"""
    background_tasks.add_task(service.refresh_tg_user_info, tg_id=user.id)
    try:
        return service.get_user_profile(user.id, user.username or user.first_name)
    except HTTPException:
        raise
    except Exception:
        logger.exception("获取用户信息时发生未预期的错误")
        raise HTTPException(status_code=500, detail="获取用户信息失败")


@router.get("/users")
@require_telegram_auth
async def get_all_users(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取所有用户信息（用于用户选择）"""
    try:
        return service.list_users_for_selection()
    except HTTPException:
        raise
    except Exception:
        logger.exception("获取用户列表失败")
        raise HTTPException(status_code=500, detail="获取用户列表失败")
