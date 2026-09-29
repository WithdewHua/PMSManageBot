from fastapi import APIRouter, Body, Depends, Request

from app.core.log import uvicorn_logger as logger
from app.domains.accounts import service as accounts_service
from app.domains.accounts.schemas import BindEmbyRequest, BindPlexRequest
from app.integrations.telegram.profiles import get_user_name_from_tg_id
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/user", tags=["user"])


@router.post("/bind/plex", response_model=BaseResponse)
@require_telegram_auth
async def bind_plex_account(
    request: Request,
    data: BindPlexRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """Bind a Plex account through the accounts service."""
    logger.info(
        "用户 %s 尝试绑定 Plex 账户 %s",
        get_user_name_from_tg_id(telegram_user.id),
        data.email,
    )
    try:
        success, message = accounts_service.bind_plex(telegram_user.id, data.email)
        return BaseResponse(success=success, message=message)
    except Exception as error:
        logger.error("绑定Plex账户时发生错误: %s", error)
        return BaseResponse(success=False, message="绑定失败，发生未知错误")


@router.post("/bind/emby", response_model=BaseResponse)
@require_telegram_auth
async def bind_emby_account(
    request: Request,
    data: BindEmbyRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """Bind an Emby account through the accounts service."""
    logger.info(
        "用户 %s 尝试绑定 Emby 账户 %s",
        get_user_name_from_tg_id(telegram_user.id),
        data.username,
    )
    try:
        success, message = accounts_service.bind_emby(telegram_user.id, data.username)
        return BaseResponse(success=success, message=message)
    except Exception as error:
        logger.error("绑定Emby账户时发生错误: %s", error)
        return BaseResponse(success=False, message="绑定失败，发生未知错误")
