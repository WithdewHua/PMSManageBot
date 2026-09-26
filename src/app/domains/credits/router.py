from fastapi import APIRouter, Body, Depends, Request

from app.core.auth import get_telegram_user, require_telegram_auth
from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.schemas import TelegramUser
from app.core.telegram import send_message_by_url
from app.domains.credits import exceptions as credits_exceptions
from app.domains.credits import service as credits_service
from app.domains.profile.schemas import CreditsTransferRequest, CreditsTransferResponse

router = APIRouter(prefix="/api/user", tags=["user"])


@router.post("/transfer-credits", response_model=CreditsTransferResponse)
@require_telegram_auth
async def transfer_credits(
    request: Request,
    data: CreditsTransferRequest = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """
    积分转移功能

    转移积分给其他用户，收取手续费
    """
    try:
        # 检查积分转移功能是否开启
        if not settings.CREDITS_TRANSFER_ENABLED:
            return CreditsTransferResponse(success=False, message="积分转移功能已关闭")

        sender_id = user.id
        target_tg_id = data.target_tg_id
        amount = data.amount
        note = data.note

        # 验证不能给自己转移积分
        if sender_id == target_tg_id:
            return CreditsTransferResponse(success=False, message="不能向自己转移积分")

        # 验证转移数量
        if amount <= 0:
            return CreditsTransferResponse(
                success=False, message="转移积分数量必须大于0"
            )

        if amount > 10000:
            return CreditsTransferResponse(
                success=False, message="单次转移积分不能超过10000"
            )

        # The service locks both statistics rows in ascending TG-ID order and
        # commits the debit and credit together.
        try:
            transfer = credits_service.transfer(sender_id, target_tg_id, amount)
        except credits_exceptions.InsufficientCredits as error:
            return CreditsTransferResponse(
                success=False,
                message=f"积分不足，需要 {error.requested:.2f} 积分（包含 {error.requested - amount:.2f} 手续费）",
            )
        except credits_exceptions.CreditAccountNotFound as error:
            if error.account == f"tg:{sender_id}":
                return CreditsTransferResponse(
                    success=False, message="您尚未绑定 Plex/Emby 账户"
                )
            return CreditsTransferResponse(
                success=False, message="目标用户不存在或未绑定账户"
            )

        fee_amount = transfer.fee

        # 记录转移日志
        from app.core.telegram import get_user_name_from_tg_id

        sender_name = get_user_name_from_tg_id(sender_id)
        target_name = get_user_name_from_tg_id(target_tg_id)

        logger.info(
            f"积分转移成功: {sender_name}({sender_id}) -> {target_name}({target_tg_id}), "
            f"金额: {amount}, 手续费: {fee_amount:.2f}"
            + (f", 备注: {note}" if note else "")
        )

        # 可以在这里发送通知给接收方用户
        try:
            await send_message_by_url(
                chat_id=target_tg_id,
                text=f"""
您收到了来自 {sender_name} 的积分转移: {amount} 积分
"""
                + (f"""备注: {note}""" if note else ""),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"发送积分转移通知失败: {e!s}")

        return CreditsTransferResponse(
            success=True,
            message=f"成功转移 {amount} 积分给用户 {target_name}",
            transferred_amount=amount,
            fee_amount=fee_amount,
            current_credits=transfer.current_sender_balance,
        )

    except Exception as e:
        logger.error(f"积分转移失败: {e!s}")
        return CreditsTransferResponse(
            success=False, message="转移过程出错，请稍后再试"
        )
