"""Crypto donation use cases; payment state and ledgers commit atomically."""

import time

from app.core.log import logger
from app.domains.crypto_donation import exceptions, notifications, repository, rules
from app.domains.crypto_donation.config import CRYPTO_DONATION_CONFIG
from app.domains.crypto_donation.types import NewOrder, UPayCallbackData
from app.domains.donation import service as donation_service
from app.domains.identity import service as identity_service
from app.integrations import upay


def get_supported_crypto_types() -> list[str]:
    return list(CRYPTO_DONATION_CONFIG.get().upay_crypto_types)


def set_supported_crypto_types(values: list[str]) -> list[str]:
    return list(
        CRYPTO_DONATION_CONFIG.update(upay_crypto_types=values).upay_crypto_types
    )


def _is_bound(user_id: int) -> bool:
    try:
        return bool(
            identity_service.find_emby_by_tg(user_id)
            or identity_service.find_plex_by_tg(user_id)
        )
    except Exception:
        logger.exception("检查用户绑定状态失败")
        return False


async def create_order(user_id: int, order_data: NewOrder) -> dict:
    if not user_id:
        raise exceptions.CryptoDonationError("missing_user", "用户信息不完整")
    if not _is_bound(user_id):
        raise exceptions.CryptoDonationError(
            "account_not_bound",
            "不接受无帐号捐赠，请先绑定 Emby 或 Plex 账号后再进行捐赠",
            status_code=403,
        )
    provider = upay.UPayService()
    if not upay.upay_secret_configured():
        raise exceptions.CryptoDonationError(
            "provider_not_configured", "UPAY 服务未配置", status_code=503
        )
    order_id = provider.generate_order_id()
    if not repository.create_crypto_donation_order(
        user_id=user_id,
        order_id=order_id,
        crypto_type=order_data.crypto_type,
        amount=order_data.amount,
        note=order_data.note,
    ):
        raise exceptions.CryptoDonationError(
            "order_create_failed", "创建订单失败", status_code=500
        )
    try:
        result = await provider.create_order(
            crypto_type=order_data.crypto_type,
            amount=order_data.amount,
            order_id=order_id,
        )
        if not result or not repository.update_crypto_donation_order_upay_info(
            order_id=order_id,
            trade_id=result.get("trade_id"),
            actual_amount=result.get("actual_amount"),
            payment_address=result.get("token"),
            payment_url=result.get("payment_url"),
            expiration_time=result.get("expiration_time"),
        ):
            raise exceptions.CryptoDonationError(
                "provider_create_failed",
                "创建支付订单失败，请稍后重试",
                status_code=500,
            )
    except Exception:
        repository.delete_unpaid_order(order_id)
        raise
    order = repository.get_crypto_donation_order_by_order_id(order_id)
    if order is None:
        raise exceptions.CryptoDonationError(
            "order_read_failed", "获取订单信息失败", status_code=500
        )
    await notifications.notify_created(user_id, order_id, order_data, result, order)
    return order


async def process_callback(callback_data: dict) -> None:
    """Authenticate before parsing, then settle with an idempotent DB claim."""
    logger.info(
        "接收到 UPAY 回调: order_id=%s trade_id=%s",
        callback_data.get("order_id"),
        callback_data.get("trade_id"),
    )
    if not upay.UPayService().verify_callback_signature(callback_data):
        raise exceptions.CryptoDonationError(
            "invalid_signature", "signature verification failed"
        )
    try:
        callback = UPayCallbackData(**callback_data)
    except Exception as error:
        # Do not log the signed payload or validation input (may contain secrets).
        raise exceptions.CryptoDonationError(
            "invalid_callback", "invalid callback data"
        ) from error
    if callback.status != 2:
        return
    order = repository.get_crypto_donation_order_by_trade_id(callback.trade_id)
    if order is None:
        raise exceptions.PaymentOrderNotFound()
    if not rules.amounts_match(order["amount"], callback.amount):
        await notifications.notify_admins(
            "⚠️ <b>UPay 回调金额不一致</b>\n\n"
            f"订单号: <code>{callback.order_id}</code>\n"
            f"交易号: <code>{callback.trade_id}</code>\n"
            f"订单金额: {float(order['amount']):.2f} CNY\n"
            f"回调金额: {callback.amount:.2f} CNY"
        )
        raise exceptions.PaymentAmountMismatch()
    if order["status"] == 2:
        return
    result = repository.settle_payment(
        trade_id=callback.trade_id,
        callback_amount=callback.amount,
        actual_amount=callback.actual_amount,
        block_transaction_id=callback.block_transaction_id,
        multiplier=donation_service.get_donation_multiplier(),
    )
    if result is not None:
        await notifications.notify_payment(callback, result)


def get_order(order_id: str) -> dict | None:
    return repository.get_crypto_donation_order_by_order_id(order_id)


def get_user_orders(user_id: int, limit: int = 20) -> list[dict]:
    return repository.get_crypto_donation_orders_by_user(user_id, limit)


def get_all_orders(
    limit: int = 100, offset: int = 0, status_filter: str | None = None
) -> list[dict]:
    return repository.get_all_crypto_donation_orders(limit, offset, status_filter)


def get_order_count(status_filter: str | None = None) -> int:
    return repository.get_crypto_donation_orders_count(status_filter)


def expire_pending_orders() -> list[dict]:
    return repository.expire_orders(int(time.time() * 1000))


async def process_expired_orders() -> None:
    logger.info("开始检查过期的 crypto 捐赠订单")
    orders = expire_pending_orders()
    if not orders:
        logger.info("没有找到过期的 crypto 捐赠订单")
        return
    logger.info("成功更新 %s 个过期的 crypto 捐赠订单状态", len(orders))
    await notifications.notify_expired(orders)
