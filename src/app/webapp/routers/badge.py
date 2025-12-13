from typing import List

from app.databases import db
from app.log import uvicorn_logger as logger
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.routers.admin import check_admin_permission
from app.webapp.schemas import TelegramUser
from app.webapp.schemas.badge import (
    BadgeCenterConfigResponse,
    BadgeCenterConfigUpdate,
    BadgeCreate,
    BadgeListResponse,
    BadgeRedeemRequest,
    BadgeRedeemResponse,
    BadgeResponse,
    BadgeUpdate,
    UserBadgeResponse,
)
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

# 创建路由器
router = APIRouter(
    prefix="/api/badges",
    tags=["badges"],
    responses={404: {"description": "Not found"}},
)


@router.get("/config", response_model=BadgeCenterConfigResponse)
@require_telegram_auth
async def get_badge_center_config(
    request: Request, telegram_user: TelegramUser = Depends(get_telegram_user)
):
    """
    获取勋章中心配置
    """
    try:
        enabled, message = db.get_badge_center_config()
        return BadgeCenterConfigResponse(enabled=enabled, message=message)
    except Exception as e:
        logger.error(f"获取勋章中心配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取勋章中心配置失败",
        )


@router.post("/config", response_model=BadgeCenterConfigResponse)
@require_telegram_auth
async def update_badge_center_config(
    request: Request,
    data: BadgeCenterConfigUpdate = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """
    管理员：更新勋章中心配置
    """
    # 检查管理员权限
    check_admin_permission(telegram_user)

    try:
        success = db.set_badge_center_config(
            enabled=data.enabled,
            message=data.message,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="更新勋章中心配置失败",
            )

        enabled, message = db.get_badge_center_config()
        return BadgeCenterConfigResponse(enabled=enabled, message=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新勋章中心配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新勋章中心配置失败",
        )


@router.get("/list", response_model=BadgeListResponse)
@require_telegram_auth
async def get_badges_list(
    request: Request, telegram_user: TelegramUser = Depends(get_telegram_user)
):
    """
    获取勋章列表（包含用户已拥有的勋章）
    """
    try:
        user_id = telegram_user.id

        # 检查功能是否启用
        enabled, message = db.get_badge_center_config()
        if not enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=message or "勋章中心功能未启用",
            )

        # 获取所有启用的勋章
        badges = db.get_all_badges(only_enabled=True)

        # 获取用户积分
        stats_info = db.get_stats_by_tg_id(user_id)
        if not stats_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户未绑定 Plex/Emby 账户",
            )
        user_credits = stats_info[2]

        # 获取用户已拥有的勋章
        user_badges = db.get_user_badges(user_id, only_active=True)

        # 转换为响应模型
        badge_responses = [BadgeResponse.model_validate(b) for b in badges]
        user_badge_responses = [
            UserBadgeResponse.model_validate(ub) for ub in user_badges
        ]

        return BadgeListResponse(
            badges=badge_responses,
            user_credits=user_credits,
            user_badges=user_badge_responses,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取勋章列表失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取勋章列表失败",
        )


@router.post("/redeem", response_model=BadgeRedeemResponse)
@require_telegram_auth
async def redeem_badge(
    request: Request,
    data: BadgeRedeemRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """
    兑换勋章
    """
    try:
        user_id = telegram_user.id
        badge_id = data.badge_id

        logger.info(f"用户 {user_id} 尝试兑换勋章 {badge_id}")

        # 检查功能是否启用
        enabled, message = db.get_badge_center_config()
        if not enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=message or "勋章中心功能未启用",
            )

        # 检查用户是否已绑定账户
        stats_info = db.get_stats_by_tg_id(user_id)
        if not stats_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户未绑定 Plex/Emby 账户",
            )

        # 兑换勋章
        success, msg, user_badge = db.redeem_badge(user_id, badge_id)

        if not success:
            return BadgeRedeemResponse(success=False, message=msg)

        # 获取剩余积分
        remaining_credits = db.get_user_credits(user_id)

        # 转换为响应模型
        user_badge_response = (
            UserBadgeResponse.model_validate(user_badge) if user_badge else None
        )

        return BadgeRedeemResponse(
            success=True,
            message=msg,
            user_badge=user_badge_response,
            credits_deducted=user_badge.get("credits_cost") if user_badge else None,
            remaining_credits=remaining_credits,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"兑换勋章失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="兑换勋章失败",
        )


@router.get("/my-badges", response_model=List[UserBadgeResponse])
@require_telegram_auth
async def get_my_badges(
    request: Request, telegram_user: TelegramUser = Depends(get_telegram_user)
):
    """
    获取当前用户的勋章
    """
    try:
        user_id = telegram_user.id
        user_badges = db.get_user_badges(user_id, only_active=True)
        return [UserBadgeResponse.model_validate(ub) for ub in user_badges]
    except Exception as e:
        logger.error(f"获取用户勋章失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户勋章失败",
        )


@router.get("/user/{tg_id}/badges", response_model=List[UserBadgeResponse])
@require_telegram_auth
async def get_user_badges_by_id(
    request: Request,
    tg_id: int,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """
    获取指定用户的勋章（用于展示在排行榜等地方）
    """
    try:
        user_badges = db.get_user_badges(tg_id, only_active=True)
        return [UserBadgeResponse.model_validate(ub) for ub in user_badges]
    except Exception as e:
        logger.error(f"获取用户勋章失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户勋章失败",
        )


# ==================== 管理员接口 ====================


@router.post("/create", response_model=BadgeResponse)
@require_telegram_auth
async def admin_create_badge(
    request: Request,
    data: BadgeCreate = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """
    管理员：创建勋章
    """
    # 检查管理员权限
    check_admin_permission(telegram_user)

    try:
        badge = db.create_badge(
            badge_type=data.badge_type,
            name=data.name,
            description=data.description,
            icon_url=data.icon_url,
            credits_cost=data.credits_cost,
            bonus_percentage=data.bonus_percentage,
            valid_days=data.valid_days,
            is_enabled=data.is_enabled,
        )
        if not badge:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="创建勋章失败，可能该类型已存在",
            )
        return BadgeResponse.model_validate(badge)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建勋章失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建勋章失败",
        )


@router.put("/{badge_id}", response_model=BadgeResponse)
@require_telegram_auth
async def admin_update_badge(
    request: Request,
    badge_id: int,
    data: BadgeUpdate = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """
    管理员：更新勋章
    """
    # 检查管理员权限
    check_admin_permission(telegram_user)

    try:
        update_data = data.model_dump(exclude_unset=True)
        success = db.update_badge(badge_id, **update_data)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="勋章不存在或更新失败",
            )
        badge = db.get_badge_by_id(badge_id)
        if not badge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="勋章不存在",
            )
        return BadgeResponse.model_validate(badge)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新勋章失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新勋章失败",
        )


@router.get("/all", response_model=List[BadgeResponse])
@require_telegram_auth
async def admin_get_all_badges(
    request: Request, telegram_user: TelegramUser = Depends(get_telegram_user)
):
    """
    管理员：获取所有勋章（包括禁用的）
    """
    # 检查管理员权限
    check_admin_permission(telegram_user)

    try:
        badges = db.get_all_badges(only_enabled=False)
        return [BadgeResponse.model_validate(b) for b in badges]
    except Exception as e:
        logger.error(f"获取所有勋章失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取所有勋章失败",
        )


@router.delete("/{badge_id}")
@require_telegram_auth
async def admin_delete_badge(
    request: Request,
    badge_id: int,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """
    管理员：删除勋章
    """
    # 检查管理员权限
    check_admin_permission(telegram_user)

    try:
        success = db.delete_badge(badge_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="勋章不存在或删除失败",
            )
        return {"success": True, "message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除勋章失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除勋章失败",
        )
