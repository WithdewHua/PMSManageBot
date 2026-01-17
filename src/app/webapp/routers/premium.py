"""
Premium 会员相关路由
"""

from typing import Optional

from app.config import settings
from app.databases import db
from app.log import uvicorn_logger as logger
from app.premium import update_premium_status
from app.utils.utils import get_user_name_from_tg_id, send_message_by_url
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import BaseResponse, TelegramUser
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
from pydantic import BaseModel


class PremiumStatisticsResponse(BaseModel):
    """Premium统计信息响应模型"""

    total_premium_users: int
    active_premium_users: int
    premium_plex_users: int
    premium_emby_users: int


class PremiumUnlockRequest(BaseModel):
    """Premium解锁请求模型"""

    service: str  # 'plex' 或 'emby'
    days: int  # 解锁天数
    total_cost: int  # 总费用


class PremiumUnlockResponse(BaseResponse):
    """Premium解锁响应模型"""

    current_credits: Optional[float] = None
    premium_expiry: Optional[str] = None


router = APIRouter(prefix="/api/premium", tags=["premium"])


@router.post("/unlock", response_model=PremiumUnlockResponse)
@require_telegram_auth
async def unlock_premium(
    request: Request,
    background_tasks: BackgroundTasks,
    data: PremiumUnlockRequest = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """解锁Premium会员"""
    tg_id = user.id
    service = data.service.lower()
    days = data.days
    total_cost = data.total_cost

    logger.info(
        f"用户 {get_user_name_from_tg_id(tg_id)} 尝试解锁 {service} Premium {days} 天，费用 {total_cost} 积分"
    )

    # 检查 Premium 解锁功能是否开放
    if not settings.PREMIUM_UNLOCK_ENABLED:
        raise HTTPException(status_code=403, detail="Premium 解锁功能暂未开放")

    # 验证参数
    if service not in ["plex", "emby"]:
        raise HTTPException(status_code=400, detail="不支持的服务类型")

    if days <= 0 or days > 365:
        raise HTTPException(status_code=400, detail="解锁天数必须在 1-365 天之间")

    # 验证费用计算（含折扣）
    daily_price = settings.PREMIUM_DAILY_CREDITS
    base_cost = days * daily_price

    # 计算折扣
    discount = 1.0
    if days >= 360:  # 年付 6 折
        discount = 0.6
    elif days >= 180:  # 半年付 7 折
        discount = 0.7
    elif days >= 30:  # 30 天以上 8 折
        discount = 0.8

    expected_cost = int(base_cost * discount)
    if total_cost != expected_cost:
        raise HTTPException(status_code=400, detail="费用计算错误")

    try:
        # 检查用户积分
        stats_info = db.get_stats_by_tg_id(tg_id)
        if not stats_info:
            raise HTTPException(status_code=400, detail="用户不存在")

        current_credits = stats_info[2]
        if current_credits < total_cost:
            raise HTTPException(status_code=400, detail="积分不足")

        try:
            new_expiry = update_premium_status(db, tg_id, service, days)
        except Exception as e:
            logger.error(f"更新 Premium 状态失败: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"更新 Premium 状态失败: {str(e)}"
            )

        # 扣除积分
        new_credits = current_credits - total_cost
        db.update_user_credits(new_credits, tg_id=tg_id)

        logger.info(
            f"用户 {get_user_name_from_tg_id(tg_id)} 成功解锁 {service} Premium {days} 天"
        )

        # 发送通知消息
        service_emoji = "🎬" if service == "plex" else "📺"
        service_name = service.upper()

        notification_text = f"""✨ Premium 解锁成功

👤 用户: {get_user_name_from_tg_id(tg_id)}
{service_emoji} 服务: {service_name}
⏰ 天数: {days} 天
💎 花费: {total_cost} 积分
💰 剩余: {new_credits} 积分
📅 到期: {new_expiry.strftime('%Y-%m-%d %H:%M:%S')}"""

        if discount < 1.0:
            discount_percent = int((1 - discount) * 100)
            notification_text += f"\n🎉 享受了 {discount_percent}折 优惠！"

        background_tasks.add_task(
            send_message_by_url,
            chat_id=settings.TG_ADMIN_CHAT_ID,
            text=notification_text,
        )

        return PremiumUnlockResponse(
            success=True,
            message=f"成功解锁 {days} 天 Premium 会员",
            current_credits=new_credits,
            premium_expiry=new_expiry.isoformat() if new_expiry else "",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"解锁 Premium 失败: {str(e)}")
        raise HTTPException(status_code=500, detail="解锁失败，请稍后再试")


@router.get("/statistics", response_model=PremiumStatisticsResponse)
@require_telegram_auth
async def get_premium_statistics(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取Premium用户统计信息"""
    try:
        stats = db.get_premium_statistics()
        logger.info(f"用户 {get_user_name_from_tg_id(user.id)} 获取 Premium 统计信息")
        return PremiumStatisticsResponse(**stats)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Premium 统计信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取统计信息失败")


@router.get("/line-traffic-stats")
@require_telegram_auth
async def get_premium_line_traffic_stats(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取Premium线路流量统计信息"""
    try:
        stats = db.get_premium_line_traffic_statistics()
        logger.info(
            f"用户 {get_user_name_from_tg_id(user.id)} 获取 Premium 线路流量统计信息"
        )
        return {"success": True, "data": stats}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Premium 线路流量统计失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取流量统计失败")
