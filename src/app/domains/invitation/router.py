from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.domains.invitation import service as invitation_service
from app.domains.invitation.exceptions import InvitationError
from app.domains.invitation.schemas import (
    BatchCheckPrivilegedCodesRequest,
    BatchCheckPrivilegedCodesResponse,
    CheckPrivilegedCodeRequest,
    CheckPrivilegedCodeResponse,
    GenerateInviteCodeResponse,
    InvitePointsResponse,
    RedeemForCreditsRequest,
    RedeemForCreditsResponse,
    RedeemInviteCodeRequest,
    RedeemResponse,
)
from app.integrations.emby import Emby
from app.integrations.plex import Plex
from app.integrations.telegram.messaging import send_message_by_url
from app.integrations.telegram.profiles import refresh_tg_user_profile
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import TelegramUser

router = APIRouter(
    prefix="/api/invite",
    tags=["invitation"],
    responses={404: {"description": "Not found"}},
)


def _error_message(error: InvitationError) -> str:
    return str(error)


@router.get("/points-info", response_model=InvitePointsResponse)
@require_telegram_auth
async def get_invite_points_info(
    request: Request, telegram_user: TelegramUser = Depends(get_telegram_user)
):
    try:
        required, current, can_generate, error_message = (
            invitation_service.get_points_info(telegram_user.id)
        )
        return InvitePointsResponse(
            required_points=required,
            current_points=current,
            can_generate=can_generate,
            error_message=error_message,
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error("获取邀请码积分信息失败: %s", error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取邀请码积分信息失败",
        ) from error


@router.post("/generate", response_model=GenerateInviteCodeResponse)
@require_telegram_auth
async def generate_invite_code(
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        code = invitation_service.generate_one_code(telegram_user.id)
        required = invitation_service.get_invitation_credits()
        return GenerateInviteCodeResponse(
            success=True,
            message=f"邀请码生成成功！已消耗 {required} 积分",
            code=code,
        )
    except InvitationError as error:
        return GenerateInviteCodeResponse(success=False, message=_error_message(error))
    except HTTPException:
        raise
    except Exception as error:
        logger.error("生成邀请码失败: %s", error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="生成邀请码失败，请稍后再试",
        ) from error


@router.get("/register-status")
async def get_register_status():
    try:
        return invitation_service.get_register_status()
    except Exception as error:
        logger.error("获取服务注册状态失败: %s", error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取服务注册状态失败",
        ) from error


@router.post("/redeem/plex", response_model=RedeemResponse)
@require_telegram_auth
async def redeem_plex_code(
    request: Request,
    background_tasks: BackgroundTasks,
    data: RedeemInviteCodeRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        background_tasks.add_task(refresh_tg_user_profile, tg_id=telegram_user.id)
        telegram_bound, _ = await invitation_service.register_plex(
            code=data.code,
            email=data.email,
            bind_to_telegram=bool(data.bind_to_telegram),
            telegram_user_id=telegram_user.id,
            notify=send_message_by_url,
            plex_factory=Plex,
        )
        return RedeemResponse(
            success=True,
            message="邀请码兑换成功！请登录 Plex 确认邀请",
            telegram_bound=telegram_bound,
        )
    except InvitationError as error:
        return RedeemResponse(success=False, message=_error_message(error))
    except Exception as error:
        logger.error("兑换 Plex 邀请码失败: %s", error)
        return RedeemResponse(success=False, message="兑换过程出错，请稍后再试")


@router.post("/redeem/emby", response_model=RedeemResponse)
@require_telegram_auth
async def redeem_emby_code(
    request: Request,
    background_tasks: BackgroundTasks,
    data: RedeemInviteCodeRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        background_tasks.add_task(refresh_tg_user_profile, tg_id=telegram_user.id)
        telegram_bound, _, password = await invitation_service.register_emby(
            code=data.code,
            username=data.username or "",
            password=data.password,
            bind_to_telegram=bool(data.bind_to_telegram),
            telegram_user_id=telegram_user.id,
            notify=send_message_by_url,
            emby_factory=Emby,
        )
        background_tasks.add_task(
            invitation_service.refresh_emby_user_info,
            emby_username=data.username or "",
        )
        message = f"邀请码兑换成功！用户名为 {data.username or ''}，密码为 {password}"
        try:
            await send_message_by_url(
                chat_id=telegram_user.id,
                text=message,
                token=settings.TG_API_TOKEN,
            )
        except Exception:
            logger.exception("发送 Emby 注册结果通知失败: %s", telegram_user.id)
        return RedeemResponse(
            success=True,
            message=message,
            telegram_bound=telegram_bound,
        )
    except InvitationError as error:
        return RedeemResponse(success=False, message=_error_message(error))
    except Exception as error:
        logger.error("兑换 Emby 邀请码失败: %s", error)
        return RedeemResponse(success=False, message="兑换过程出错，请稍后再试")


@router.post("/check-privileged", response_model=CheckPrivilegedCodeResponse)
async def check_privileged_invite_code(
    request: Request,
    data: CheckPrivilegedCodeRequest = Body(...),
):
    try:
        privileged = invitation_service.check_privileged_code(data.code)
        return CheckPrivilegedCodeResponse(privileged=privileged)
    except Exception as error:
        logger.error("检查特权邀请码失败: %s", error)
        return CheckPrivilegedCodeResponse(privileged=False)


@router.post(
    "/batch-check-privileged", response_model=BatchCheckPrivilegedCodesResponse
)
async def batch_check_privileged_invite_codes(
    request: Request,
    data: BatchCheckPrivilegedCodesRequest = Body(...),
):
    try:
        results = invitation_service.batch_check_privileged_codes(data.codes)
        return BatchCheckPrivilegedCodesResponse(results=results)
    except Exception as error:
        logger.error("批量检查特权邀请码失败: %s", error)
        return BatchCheckPrivilegedCodesResponse(
            results={code: False for code in data.codes}
        )


@router.post("/redeem-for-credits", response_model=RedeemForCreditsResponse)
@require_telegram_auth
async def redeem_invite_code_for_credits(
    request: Request,
    data: RedeemForCreditsRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        credits_earned, current_credits = invitation_service.redeem_for_credits(
            telegram_user.id, data.code
        )
        return RedeemForCreditsResponse(
            success=True,
            message=f"成功兑换 {credits_earned} 积分！",
            credits_earned=credits_earned,
            current_credits=current_credits,
        )
    except InvitationError as error:
        return RedeemForCreditsResponse(success=False, message=_error_message(error))
    except Exception as error:
        logger.error("邀请码兑换积分失败: %s", error)
        return RedeemForCreditsResponse(
            success=False, message="兑换过程出错，请稍后再试"
        )
