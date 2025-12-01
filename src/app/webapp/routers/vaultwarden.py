from app.config import settings
from app.databases import db
from app.log import uvicorn_logger as logger
from app.modules.vaultwarden import Vaultwarden
from app.utils.utils import get_user_name_from_tg_id
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import (
    TelegramUser,
    VaultwardenRedeemInfoResponse,
    VaultwardenRedeemRequest,
    VaultwardenRedeemResponse,
)
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

# 创建路由器
router = APIRouter(
    prefix="/api/vaultwarden",
    tags=["vaultwarden"],
    responses={404: {"description": "Not found"}},
)


@router.get("/redeem-info", response_model=VaultwardenRedeemInfoResponse)
@require_telegram_auth
async def get_vaultwarden_redeem_info(
    request: Request, telegram_user: TelegramUser = Depends(get_telegram_user)
):
    """
    获取 Vaultwarden 兑换信息
    """
    try:
        user_id = telegram_user.id

        # 检查功能是否启用
        if not settings.VAULTWARDEN_ENABLED:
            return VaultwardenRedeemInfoResponse(
                enabled=False,
                required_credits=settings.VAULTWARDEN_REDEEM_CREDITS,
                current_credits=0,
                can_redeem=False,
                error_message="Vaultwarden 兑换功能未启用",
            )

        # 获取用户统计信息
        stats_info = db.get_stats_by_tg_id(user_id)

        # 如果用户不存在
        if not stats_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户未绑定 Plex/Emby 账户",
            )

        # 获取用户当前积分
        user_credits = stats_info[2]

        # 获取兑换所需积分
        required_credits = settings.VAULTWARDEN_REDEEM_CREDITS

        # 判断用户是否有足够的积分
        can_redeem = user_credits >= required_credits
        error_message = None

        if not can_redeem:
            error_message = "积分不足，无法兑换 Vaultwarden 账户"

        return VaultwardenRedeemInfoResponse(
            enabled=True,
            required_credits=required_credits,
            current_credits=user_credits,
            can_redeem=can_redeem,
            error_message=error_message,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Vaultwarden 兑换信息失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取 Vaultwarden 兑换信息失败",
        )


@router.post("/redeem", response_model=VaultwardenRedeemResponse)
@require_telegram_auth
async def redeem_vaultwarden_account(
    request: Request,
    data: VaultwardenRedeemRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """
    兑换 Vaultwarden 账户
    """
    try:
        user_id = telegram_user.id
        email = data.email

        # 检查功能是否启用
        if not settings.VAULTWARDEN_ENABLED:
            return VaultwardenRedeemResponse(
                success=False, message="Vaultwarden 兑换功能未启用"
            )

        # 验证邮箱格式（Pydantic 已经验证过了，这里只是额外检查）
        if not email or "@" not in email:
            return VaultwardenRedeemResponse(
                success=False, message="请输入有效的邮箱地址"
            )

        # 获取用户统计信息
        stats_info = db.get_stats_by_tg_id(user_id)

        # 如果用户不存在
        if not stats_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户未绑定 Plex/Emby 账户",
            )

        # 获取用户当前积分
        user_credits = stats_info[2]

        # 获取兑换所需积分
        required_credits = settings.VAULTWARDEN_REDEEM_CREDITS

        # 检查积分是否足够
        if user_credits < required_credits:
            return VaultwardenRedeemResponse(
                success=False,
                message=f"积分不足，您当前积分 {user_credits}，需要 {required_credits} 积分才能兑换 Vaultwarden 账户",
            )

        # 实例化 Vaultwarden 对象
        vw = Vaultwarden()

        # 发送邀请（Vaultwarden 会自动检查邮箱是否已注册）
        if not vw.invite_user(email):
            return VaultwardenRedeemResponse(
                success=False,
                message="发送邀请失败，邮箱可能已被注册或服务出现错误，请稍后再试或联系管理员",
            )

        # 扣除积分
        new_credits = user_credits - required_credits
        res = db.update_user_credits(new_credits, tg_id=user_id)
        if not res:
            logger.error(f"更新用户 {user_id} 积分失败")
            return VaultwardenRedeemResponse(
                success=False, message="兑换成功但更新积分失败，请联系管理员"
            )

        logger.info(
            f"用户 {get_user_name_from_tg_id(user_id)} 成功兑换 Vaultwarden 账户，邮箱: {email}，扣除积分: {required_credits}"
        )

        return VaultwardenRedeemResponse(
            success=True,
            message=f"兑换成功！邀请邮件已发送至 {email}，请查收邮件完成注册",
            credits_deducted=float(required_credits),
            remaining_credits=float(new_credits),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"兑换 Vaultwarden 账户失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="兑换 Vaultwarden 账户失败",
        )
