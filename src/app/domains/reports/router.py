from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.log import uvicorn_logger as logger
from app.domains.reports import service as reports_service
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import TelegramUser

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/stats")
@require_telegram_auth
async def get_system_stats(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取系统统计信息（不需要管理员权限）"""
    logger.info(f"{user.username or user.first_name or user.id} 获取系统统计信息")

    try:
        stats = reports_service.get_system_stats()
        logger.info(f"系统统计信息: {stats}")
        return stats
    except Exception as e:
        logger.error(f"获取系统统计信息失败: {e!s}")
        raise HTTPException(status_code=500, detail="获取系统统计信息失败")


@router.get("/status")
async def get_system_status():
    """获取系统状态信息（公开接口，不需要登录）"""
    try:
        status_data = reports_service.get_system_status()
        logger.info("获取系统状态信息")
        return status_data
    except Exception as e:
        logger.error(f"获取系统状态信息失败: {e!s}")
        raise HTTPException(status_code=500, detail="获取系统状态信息失败")


@router.get("/traffic-overview")
@require_telegram_auth
async def get_traffic_overview(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取流量统计概览数据（不需要管理员权限）"""
    logger.info(f"{user.username or user.first_name or user.id} 获取流量统计概览")

    try:
        traffic_stats = reports_service.get_traffic_statistics()
        logger.info("流量统计概览数据获取成功")
        return {
            "success": True,
            "message": "获取成功",
            "data": traffic_stats,
        }
    except Exception as e:
        logger.error(f"获取流量统计概览失败: {e!s}")
        raise HTTPException(status_code=500, detail="获取流量统计失败")
