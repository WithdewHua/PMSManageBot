"""Vaultwarden business services and redemption workflows."""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.log import uvicorn_logger as logger
from app.domains.credits import exceptions as credits_exceptions
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity import service as identity_service
from app.domains.vaultwarden import notifications, repository
from app.domains.vaultwarden.config import VAULTWARDEN_CONFIG
from app.domains.vaultwarden.exceptions import VaultwardenAccountNotBound
from app.domains.vaultwarden.types import RedeemInfo, RedeemResult
from app.integrations.telegram import profiles as telegram_profiles
from app.integrations.vaultwarden import Vaultwarden


def get_vaultwarden_config():
    return VAULTWARDEN_CONFIG.get()


def is_enabled() -> bool:
    return bool(VAULTWARDEN_CONFIG.get().enabled)


def get_redeem_credits() -> int:
    return int(VAULTWARDEN_CONFIG.get().redeem_credits)


def set_enabled(enabled: bool):
    return VAULTWARDEN_CONFIG.update(enabled=enabled)


def set_redeem_credits(credits: int) -> int:
    return int(VAULTWARDEN_CONFIG.update(redeem_credits=credits).redeem_credits)


def count_redemptions() -> int:
    """Count total Vaultwarden account redemptions for reports."""
    return repository.count_redemptions()


def get_redeem_info(tg_id: int) -> RedeemInfo:
    """Get redemption information and eligibility for a Telegram user."""
    required_credits = get_redeem_credits()

    if not is_enabled():
        return RedeemInfo(
            enabled=False,
            required_credits=required_credits,
            current_credits=0.0,
            can_redeem=False,
            error_message="Vaultwarden 兑换功能未启用",
        )

    stats = identity_service.get_statistics(tg_id)
    if not stats:
        raise VaultwardenAccountNotBound("用户未绑定 Plex/Emby 账户")

    user_credits = float(stats.credits)
    can_redeem = user_credits >= required_credits
    error_message = None if can_redeem else "积分不足，无法兑换 Vaultwarden 账户"

    return RedeemInfo(
        enabled=True,
        required_credits=required_credits,
        current_credits=user_credits,
        can_redeem=can_redeem,
        error_message=error_message,
    )


async def redeem(
    tg_id: int,
    email: str,
    *,
    vaultwarden_client: Any = None,
) -> RedeemResult:
    """Orchestrate Vaultwarden redemption: debit -> external invite -> record."""
    if not is_enabled():
        return RedeemResult(
            success=False,
            message="Vaultwarden 兑换功能未启用",
        )

    if not email or "@" not in email:
        return RedeemResult(
            success=False,
            message="请输入有效的邮箱地址",
        )

    stats = identity_service.get_statistics(tg_id)
    if not stats:
        raise VaultwardenAccountNotBound("用户未绑定 Plex/Emby 账户")

    required_credits = get_redeem_credits()
    user_credits = float(stats.credits)
    if user_credits < required_credits:
        return RedeemResult(
            success=False,
            message=f"积分不足，您当前积分 {user_credits}，需要 {required_credits} 积分才能兑换 Vaultwarden 账户",
        )

    # 1. Debit credits first
    try:
        mutation = credits_service.deduct(
            CreditAccount.tg(int(tg_id)), float(required_credits)
        )
        new_credits = mutation.after
    except credits_exceptions.InsufficientCredits as exc:
        return RedeemResult(
            success=False,
            message=f"积分不足，您当前积分 {exc.available}，需要 {required_credits} 积分才能兑换 Vaultwarden 账户",
        )
    except credits_exceptions.CreditAccountNotFound:
        raise VaultwardenAccountNotBound("用户未绑定 Plex/Emby 账户")

    # 2. External account creation in thread pool (constructor + call inside try)
    def _create_and_invite() -> bool:
        if isinstance(vaultwarden_client, type):
            client = vaultwarden_client()
        elif vaultwarden_client is not None:
            if callable(vaultwarden_client) and not hasattr(
                vaultwarden_client, "invite_user"
            ):
                client = vaultwarden_client()
            else:
                client = vaultwarden_client
        else:
            client = Vaultwarden()
        return bool(client.invite_user(email))

    try:
        invite_ok = await asyncio.to_thread(_create_and_invite)
    except Exception as exc:
        logger.error(f"调用 Vaultwarden 开号发生异常: {exc!s}")
        invite_ok = False

    # 3. Handle external creation failure: compensating refund
    if not invite_ok:
        refund_err: Exception | None = None
        try:
            credits_service.add(CreditAccount.tg(int(tg_id)), float(required_credits))
            logger.info(
                f"Vaultwarden 开号失败，已成功退还用户 {tg_id} 积分: {required_credits}"
            )
        except Exception as err:
            refund_err = err
            logger.error(
                f"Vaultwarden 开号失败后退还积分失败: tg_id={tg_id}, credits={required_credits}, error={err!s}"
            )

        if refund_err is not None:
            try:
                user_name = telegram_profiles.get_user_name_from_tg_id(tg_id)
            except Exception as name_err:
                logger.warning(f"获取用户名称失败 (tg_id={tg_id}): {name_err!s}")
                user_name = str(tg_id)

            try:
                await notifications.notify_admins_vaultwarden_refund_failed(
                    user_id=tg_id,
                    user_name=user_name,
                    email=email,
                    credits=float(required_credits),
                    error_detail=str(refund_err),
                )
            except Exception as notify_err:
                logger.error(f"发送退款失败管理员通知发生异常: {notify_err!s}")

        return RedeemResult(
            success=False,
            message="发送邀请失败，邮箱可能已被注册或服务出现错误，请稍后再试或联系管理员",
        )

    # 4. Handle creation success: write record to repository
    try:
        repository.record_redemption(
            tg_id=tg_id,
            email=email,
            credits_cost=float(required_credits),
        )
        logger.info(f"成功保存 Vaultwarden 兑换记录: tg_id={tg_id}, email={email}")
    except Exception as e:
        logger.error(f"保存 Vaultwarden 兑换记录失败: {e!s}")

    try:
        user_name = telegram_profiles.get_user_name_from_tg_id(tg_id)
    except Exception as name_err:
        logger.warning(f"获取用户名称失败 (tg_id={tg_id}): {name_err!s}")
        user_name = str(tg_id)

    logger.info(
        f"用户 {user_name} 成功兑换 Vaultwarden 账户，邮箱: {email}，扣除积分: {required_credits}"
    )

    try:
        await notifications.notify_admins_vaultwarden_redeem(
            user_id=tg_id,
            user_name=user_name,
            email=email,
            required_credits=float(required_credits),
            new_credits=float(new_credits),
        )
    except Exception as notify_err:
        logger.warning(f"发送管理员兑换通知失败: {notify_err!s}")

    return RedeemResult(
        success=True,
        message=f"兑换成功！邀请邮件已发送至 {email}，请查收邮件完成注册",
        credits_deducted=float(required_credits),
        remaining_credits=float(new_credits),
    )


__all__ = [
    "count_redemptions",
    "get_redeem_credits",
    "get_redeem_info",
    "get_vaultwarden_config",
    "is_enabled",
    "redeem",
    "set_enabled",
    "set_redeem_credits",
]
