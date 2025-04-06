from time import time
from uuid import NAMESPACE_URL, uuid3

from app.config import settings
from app.db import DB
from app.emby import Emby
from app.log import uvicorn_logger as logger
from app.plex import Plex
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.models import (
    GenerateInviteCodeResponse,
    InvitePointsResponse,
    RedeemInviteCodeRequest,
    RedeemResponse,
    TelegramUser,
)
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

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


@router.get("/register-status")
async def get_register_status():
    """获取媒体服务的注册状态"""
    try:
        return {"plex": settings.PLEX_REGISTER, "emby": settings.EMBY_REGISTER}
    except Exception as e:
        logger.error(f"获取服务注册状态失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取服务注册状态失败",
        )


@router.post("/redeem/plex", response_model=RedeemResponse)
@require_telegram_auth
async def redeem_plex_code(
    request: Request,
    data: RedeemInviteCodeRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """兑换 Plex 邀请码"""
    try:
        code = data.code
        email = data.email

        # 检查是否允许注册
        if not settings.PLEX_REGISTER:
            return RedeemResponse(success=False, message="Plex 当前不接受新用户注册")

        # 验证邮箱格式
        if not email or "@" not in email:
            return RedeemResponse(success=False, message="请输入有效的邮箱地址")

        _db = DB()

        try:
            # 检查邀请码是否存在且未被使用
            res = _db.verify_invitation_code_is_used(code)
            if not res:
                return RedeemResponse(success=False, message="邀请码不存在")

            if res[0]:
                return RedeemResponse(success=False, message="邀请码已被使用")

            # 实例化 Plex 对象
            _plex = Plex()

            # 检查该用户是否已经被邀请
            if email in _plex.users_by_email:
                return RedeemResponse(
                    success=False, message="该邮箱账户已被邀请，请使用其他邮箱"
                )

            # 发送邀请
            if not _plex.invite_friend(email):
                return RedeemResponse(
                    success=False, message="邀请失败，请稍后再试或联系管理员"
                )

            # 更新邀请码状态
            res = _db.update_invitation_status(code=code, used_by=email)
            if not res:
                return RedeemResponse(
                    success=False, message="更新邀请码状态失败，请联系管理员"
                )

            # 返回成功响应
            return RedeemResponse(
                success=True, message="邀请码兑换成功！请登录 Plex 确认邀请"
            )
        finally:
            _db.close()

    except Exception as e:
        logger.error(f"兑换 Plex 邀请码失败: {str(e)}")
        return RedeemResponse(success=False, message="兑换过程出错，请稍后再试")


@router.post("/redeem/emby", response_model=RedeemResponse)
@require_telegram_auth
async def redeem_emby_code(
    request: Request,
    data: RedeemInviteCodeRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """兑换 Emby 邀请码"""
    try:
        code = data.code
        username = data.username

        # 检查是否允许注册
        if not settings.EMBY_REGISTER:
            return RedeemResponse(success=False, message="Emby 当前不接受新用户注册")

        # 验证用户名
        if not username or len(username) < 2:
            return RedeemResponse(success=False, message="请输入有效的用户名")

        _db = DB()

        try:
            # 检查邀请码是否存在且未被使用
            res = _db.verify_invitation_code_is_used(code)
            if not res:
                return RedeemResponse(success=False, message="邀请码不存在")

            if res[0]:
                return RedeemResponse(success=False, message="邀请码已被使用")

            # 检查该用户是否存在
            _emby = Emby()
            if _db.get_emby_info_by_emby_username(
                username
            ) or _emby.get_uid_from_username(username):
                return RedeemResponse(
                    success=False, message="该用户名已存在，请使用其他用户名"
                )

            # 创建用户
            flag, msg = _emby.add_user(username=username)
            if not flag:
                return RedeemResponse(success=False, message=f"创建用户失败: {msg}")

            # 更新邀请码状态
            res = _db.update_invitation_status(code=code, used_by=username)
            if not res:
                return RedeemResponse(
                    success=False, message="更新邀请码状态失败，请联系管理员"
                )

            # 添加 emby 用户信息
            _db.add_emby_user(username, emby_id=msg)

            # 返回成功响应
            return RedeemResponse(
                success=True,
                message=f"邀请码兑换成功！用户名为 {username}，密码为空，请及时登录 Emby 修改密码",
            )
        finally:
            _db.close()

    except Exception as e:
        logger.error(f"兑换 Emby 邀请码失败: {str(e)}")
        return RedeemResponse(success=False, message="兑换过程出错，请稍后再试")
