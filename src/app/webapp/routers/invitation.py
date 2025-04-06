from time import time
from uuid import NAMESPACE_URL, uuid3

from app.config import settings
from app.db import DB
from app.log import uvicorn_logger as logger
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.models import (
    GenerateInviteCodeResponse,
    InvitePointsResponse,
    TelegramUser,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status

# 创建路由器
router = APIRouter(
    prefix="/api/invite",
    tags=["invitation"],
    responses={404: {"description": "Not found"}},
)


@router.get("/points-info", response_model=InvitePointsResponse)
@require_telegram_auth
async def get_invite_points_info(
    request: Request, telegram_user: TelegramUser = Depends(get_telegram_user)
):
    """
    获取用户当前积分和生成邀请码所需的积分信息
    """
    try:
        user_id = telegram_user.id
        _db = DB()

        # 获取用户统计信息
        stats_info = _db.get_stats_by_tg_id(user_id)

        # 如果用户不存在
        if not stats_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户未绑定 Plex/Emby 账户",
            )

        # 获取用户当前积分
        user_credits = stats_info[2]

        # 获取邀请码所需积分
        required_points = settings.INVITATION_CREDITS

        # 判断用户是否有足够的积分
        can_generate = user_credits >= required_points
        error_message = None

        if not can_generate:
            error_message = "积分不足，无法生成邀请码"

        return InvitePointsResponse(
            required_points=required_points,
            current_points=user_credits,
            can_generate=can_generate,
            error_message=error_message,
        )

    except Exception as e:
        logger.error(f"获取邀请码积分信息失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取邀请码积分信息失败",
        )
    finally:
        _db.close()


@router.post("/generate", response_model=GenerateInviteCodeResponse)
@require_telegram_auth
async def generate_invite_code(
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """
    生成新的邀请码，消耗用户积分
    """
    try:
        user_id = telegram_user.id
        _db = DB()

        # 获取用户统计信息
        stats_info = _db.get_stats_by_tg_id(user_id)

        # 如果用户不存在
        if not stats_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户未绑定 Plex/Emby 账户",
            )

        # 获取用户当前积分
        user_credits = stats_info[2]

        # 获取邀请码所需积分
        required_points = settings.INVITATION_CREDITS

        # 检查剩余积分
        if user_credits < required_points:
            return GenerateInviteCodeResponse(
                success=False,
                message=f"积分不足，您当前积分 {user_credits}，需要 {required_points} 积分才能生成邀请码",
            )

        # 减去积分
        new_credits = user_credits - required_points

        # 生成邀请码
        invite_code = uuid3(NAMESPACE_URL, str(user_id + time())).hex

        # 先添加邀请码
        res = _db.add_invitation_code(code=invite_code, owner=user_id)
        if not res:
            return GenerateInviteCodeResponse(
                success=False, message="生成邀请码失败，请稍后再试"
            )

        # 然后更新积分
        res = _db.update_user_credits(new_credits, tg_id=user_id)
        if not res:
            # 如果更新积分失败，需要回滚邀请码
            # 实际应用中应该有更完善的事务处理
            return GenerateInviteCodeResponse(
                success=False, message="更新积分失败，请稍后再试"
            )

        return GenerateInviteCodeResponse(
            success=True,
            message=f"邀请码生成成功！已消耗 {required_points} 积分",
            code=invite_code,
        )

    except Exception as e:
        logger.error(f"生成邀请码失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="生成邀请码失败，请稍后再试",
        )
    finally:
        _db.close()
