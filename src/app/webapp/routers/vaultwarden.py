from datetime import datetime
from time import time

from app.config import settings
from app.databases import db
from app.databases.session import get_session
from app.log import uvicorn_logger as logger
from app.models.models import VaultwardenRedeemRecords
from app.modules.vaultwarden import Vaultwarden
from app.utils.utils import get_user_name_from_tg_id, send_message_by_url
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import (
    TelegramUser,
    VaultwardenRedeemInfoResponse,
    VaultwardenRedeemRequest,
    VaultwardenRedeemResponse,
)
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)

# 创建路由器
router = APIRouter(
    prefix="/api/vaultwarden",
    tags=["vaultwarden"],
    responses={404: {"description": "Not found"}},
)


async def _notify_admins_vaultwarden_redeem(
    user_id: int,
    user_name: str,
    email: str,
    required_credits: float,
    new_credits: float,
):
    """后台发送 Vaultwarden 兑换成功管理员通知"""
    for admin in settings.TG_ADMIN_CHAT_ID:
        try:
            await send_message_by_url(
                chat_id=admin,
                text=(
                    f"📬 <b>Vaultwarden 兑换通知</b>\n\n"
                    f"用户 <b>{user_name}</b>（TG ID: <code>{user_id}</code>）\n"
                    f"成功兑换 Vaultwarden 账户\n"
                    f"邮箱：<code>{email}</code>\n"
                    f"消耗积分：{required_credits}\n"
                    f"剩余积分：{new_credits}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"发送管理员通知失败 {admin}: {e}")


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
    background_tasks: BackgroundTasks,
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

        # 存储兑换记录到数据库
        try:
            redeem_date = datetime.now(settings.TZ).strftime("%Y-%m-%d %H:%M:%S")
            created_at = int(time())

            with get_session() as session:
                redeem_record = VaultwardenRedeemRecords(
                    tg_id=user_id,
                    email=email,
                    credits_cost=float(required_credits),
                    redeem_date=redeem_date,
                    created_at=created_at,
                )
                session.add(redeem_record)
                session.commit()

            logger.info(
                f"成功保存 Vaultwarden 兑换记录: tg_id={user_id}, email={email}"
            )
        except Exception as e:
            logger.error(f"保存 Vaultwarden 兑换记录失败: {str(e)}")
            # 不影响兑换流程，仅记录错误

        logger.info(
            f"用户 {get_user_name_from_tg_id(user_id)} 成功兑换 Vaultwarden 账户，邮箱: {email}，扣除积分: {required_credits}"
        )

        # 发送管理员通知（BackgroundTasks 后台执行，不阻塞请求）
        user_name = get_user_name_from_tg_id(user_id)
        background_tasks.add_task(
            _notify_admins_vaultwarden_redeem,
            user_id=user_id,
            user_name=user_name,
            email=email,
            required_credits=required_credits,
            new_credits=new_credits,
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
