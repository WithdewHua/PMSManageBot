from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)

from app.core.log import uvicorn_logger as logger
from app.domains.vaultwarden import service as vaultwarden_service
from app.domains.vaultwarden.exceptions import VaultwardenAccountNotBound
from app.domains.vaultwarden.schemas import (
    VaultwardenRedeemInfoResponse,
    VaultwardenRedeemRequest,
    VaultwardenRedeemResponse,
)
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import TelegramUser

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
        info = vaultwarden_service.get_redeem_info(user_id)
        return VaultwardenRedeemInfoResponse(
            enabled=info.enabled,
            required_credits=info.required_credits,
            current_credits=info.current_credits,
            can_redeem=info.can_redeem,
            error_message=info.error_message,
        )
    except HTTPException:
        raise
    except VaultwardenAccountNotBound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as e:
        logger.error(f"获取 Vaultwarden 兑换信息失败: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取 Vaultwarden 兑换信息失败",
        ) from e


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
        result = await vaultwarden_service.redeem(user_id, email)
        return VaultwardenRedeemResponse(
            success=result.success,
            message=result.message,
            credits_deducted=result.credits_deducted,
            remaining_credits=result.remaining_credits,
        )
    except HTTPException:
        raise
    except VaultwardenAccountNotBound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as e:
        logger.error(f"兑换 Vaultwarden 账户失败: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="兑换 Vaultwarden 账户失败",
        ) from e
