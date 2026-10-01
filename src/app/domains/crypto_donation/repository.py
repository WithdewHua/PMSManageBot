from datetime import datetime

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.crypto_donation.config import CRYPTO_DONATION_CONFIG
from app.domains.crypto_donation.models import CryptoDonationOrders
from app.domains.identity.types import TgIdReassignIssue


def create_crypto_donation_order(
    user_id: int,
    order_id: str,
    crypto_type: str,
    amount: float,
    note: str | None = None,
) -> bool:
    """创建 crypto 捐赠订单"""
    try:
        # 验证加密货币类型是否支持
        if crypto_type not in CRYPTO_DONATION_CONFIG.get().upay_crypto_types:
            logger.error(f"不支持的加密货币类型: {crypto_type}")
            return False

        with get_session() as session:
            created_at = datetime.now(settings.TZ).isoformat()

            order = CryptoDonationOrders(
                user_id=user_id,
                order_id=order_id,
                crypto_type=crypto_type,
                amount=amount,
                created_at=created_at,
                note=note,
            )
            session.add(order)
            return True
    except Exception as e:
        logger.error(f"创建 crypto 捐赠订单失败: {e}")
        return False


def update_crypto_donation_order_upay_info(
    order_id: str,
    trade_id: str,
    actual_amount: float,
    payment_address: str,
    payment_url: str,
    expiration_time: int,
) -> bool:
    """更新 crypto 捐赠订单的 UPAY 信息"""
    try:
        with get_session() as session:
            updated_at = datetime.now(settings.TZ).isoformat()

            result = session.execute(
                update(CryptoDonationOrders)
                .where(CryptoDonationOrders.order_id == order_id)
                .values(
                    trade_id=trade_id,
                    actual_amount=actual_amount,
                    payment_address=payment_address,
                    payment_url=payment_url,
                    expiration_time=expiration_time,
                    updated_at=updated_at,
                )
            )
            return result.rowcount == 1
    except Exception as e:
        logger.error(f"更新 crypto 捐赠订单 UPAY 信息失败: {e}")
        return False


def get_crypto_donation_order_by_order_id(order_id: str) -> dict | None:
    """根据订单ID获取 crypto 捐赠订单"""
    try:
        with get_session() as session:
            stmt = select(CryptoDonationOrders).where(
                CryptoDonationOrders.order_id == order_id
            )
            result = session.execute(stmt).scalar_one_or_none()

            if result:
                return {
                    "id": result.id,
                    "user_id": result.user_id,
                    "order_id": result.order_id,
                    "trade_id": result.trade_id,
                    "crypto_type": result.crypto_type,
                    "amount": result.amount,
                    "actual_amount": result.actual_amount,
                    "payment_address": result.payment_address,
                    "block_transaction_id": result.block_transaction_id,
                    "status": result.status,
                    "payment_url": result.payment_url,
                    "expiration_time": result.expiration_time,
                    "created_at": result.created_at,
                    "updated_at": result.updated_at,
                    "paid_at": result.paid_at,
                    "note": result.note,
                }
            return None
    except Exception as e:
        logger.error(f"获取 crypto 捐赠订单失败: {e}")
        return None


def get_crypto_donation_order_by_trade_id(trade_id: str) -> dict | None:
    """根据交易ID获取 crypto 捐赠订单"""
    try:
        with get_session() as session:
            stmt = select(CryptoDonationOrders).where(
                CryptoDonationOrders.trade_id == trade_id
            )
            result = session.execute(stmt).scalar_one_or_none()

            if result:
                return {
                    "id": result.id,
                    "user_id": result.user_id,
                    "order_id": result.order_id,
                    "trade_id": result.trade_id,
                    "crypto_type": result.crypto_type,
                    "amount": result.amount,
                    "actual_amount": result.actual_amount,
                    "payment_address": result.payment_address,
                    "block_transaction_id": result.block_transaction_id,
                    "status": result.status,
                    "payment_url": result.payment_url,
                    "expiration_time": result.expiration_time,
                    "created_at": result.created_at,
                    "updated_at": result.updated_at,
                    "paid_at": result.paid_at,
                    "note": result.note,
                }
            return None
    except Exception as e:
        logger.error(f"获取 crypto 捐赠订单失败: {e}")
        return None


def get_crypto_donation_orders_by_user(user_id: int, limit: int = 20) -> list[dict]:
    """获取用户的 crypto 捐赠订单历史"""
    try:
        with get_session() as session:
            stmt = (
                select(CryptoDonationOrders)
                .where(CryptoDonationOrders.user_id == user_id)
                .order_by(CryptoDonationOrders.created_at.desc())
                .limit(limit)
            )
            results = session.execute(stmt).scalars().all()

            orders = []
            for result in results:
                orders.append(
                    {
                        "id": result.id,
                        "user_id": result.user_id,
                        "order_id": result.order_id,
                        "trade_id": result.trade_id,
                        "crypto_type": result.crypto_type,
                        "amount": result.amount,
                        "actual_amount": result.actual_amount,
                        "payment_address": result.payment_address,
                        "block_transaction_id": result.block_transaction_id,
                        "status": result.status,
                        "payment_url": result.payment_url,
                        "expiration_time": result.expiration_time,
                        "created_at": result.created_at,
                        "updated_at": result.updated_at,
                        "paid_at": result.paid_at,
                        "note": result.note,
                    }
                )
            return orders
    except Exception as e:
        logger.error(f"获取用户 crypto 捐赠订单历史失败: {e}")
        return []


def get_all_crypto_donation_orders(
    limit: int = 100, offset: int = 0, status_filter: str | None = None
) -> list[dict]:
    """获取所有 crypto 捐赠订单历史（管理员用）"""
    try:
        with get_session() as session:
            # 构建查询
            stmt = select(CryptoDonationOrders)

            # 添加状态过滤
            if status_filter and status_filter in ["0", "1", "2", "3"]:
                stmt = stmt.where(CryptoDonationOrders.status == int(status_filter))

            # 排序和分页
            stmt = (
                stmt.order_by(CryptoDonationOrders.created_at.desc())
                .limit(limit)
                .offset(offset)
            )

            results = session.execute(stmt).scalars().all()

            orders = []
            for result in results:
                orders.append(
                    {
                        "id": result.id,
                        "user_id": result.user_id,
                        "order_id": result.order_id,
                        "trade_id": result.trade_id,
                        "crypto_type": result.crypto_type,
                        "amount": result.amount,
                        "actual_amount": result.actual_amount,
                        "payment_address": result.payment_address,
                        "block_transaction_id": result.block_transaction_id,
                        "status": result.status,
                        "payment_url": result.payment_url,
                        "expiration_time": result.expiration_time,
                        "created_at": result.created_at,
                        "updated_at": result.updated_at,
                        "paid_at": result.paid_at,
                        "note": result.note,
                    }
                )
            return orders
    except Exception as e:
        logger.error(f"获取所有 crypto 捐赠订单历史失败: {e}")
        return []


def get_crypto_donation_orders_count(status_filter: str | None = None) -> int:
    """获取 crypto 捐赠订单总数（管理员用）"""
    try:
        with get_session() as session:
            # 构建查询
            stmt = select(func.count(CryptoDonationOrders.id))

            # 添加状态过滤
            if status_filter and status_filter in ["0", "1", "2", "3"]:
                stmt = stmt.where(CryptoDonationOrders.status == int(status_filter))

            result = session.execute(stmt).scalar()
            return result if result else 0
    except Exception as e:
        logger.error(f"获取 crypto 捐赠订单总数失败: {e}")
        return 0


def settle_payment_tx(
    session,
    *,
    trade_id: str,
    callback_amount: float,
    actual_amount: float,
    block_transaction_id: str | None,
    multiplier: float,
) -> dict | None:
    """Claim and credit one pending payment in the caller's transaction.

    None denotes an already committed callback. Any failure propagates so neither
    the order state nor either ledger can commit without the other.
    """
    from app.core import events
    from app.domains.credits import repository as credits_repository
    from app.domains.credits.types import CreditAccount
    from app.domains.crypto_donation import events as payment_events
    from app.domains.crypto_donation import exceptions, rules
    from app.domains.donation import repository as donation_repository
    from app.domains.identity import repository as identity_repository

    order = session.execute(
        select(CryptoDonationOrders)
        .where(CryptoDonationOrders.trade_id == trade_id)
        .with_for_update()
    ).scalar_one_or_none()
    if order is None:
        raise exceptions.PaymentOrderNotFound()
    if not rules.amounts_match(order.amount, callback_amount):
        raise exceptions.PaymentAmountMismatch()
    if order.status == 2:
        return None
    now = datetime.now(settings.TZ).isoformat()
    claimed = session.execute(
        update(CryptoDonationOrders)
        .where(CryptoDonationOrders.id == order.id, CryptoDonationOrders.status == 1)
        .values(
            status=2,
            actual_amount=actual_amount,
            block_transaction_id=block_transaction_id,
            paid_at=now,
            updated_at=now,
        )
    )
    if claimed.rowcount != 1:
        raise exceptions.PaymentStateRejected()
    tg_id = int(order.user_id)
    identity_repository.ensure_statistics_tx(session, tg_id)
    donation_total = donation_repository.add_donation_tx(
        session, tg_id, float(order.amount)
    )
    reward = round(float(order.amount) * multiplier, 2)
    mutation = credits_repository.add_tx(session, CreditAccount.tg(tg_id), reward)
    events.publish(session, payment_events.CryptoDonationCompleted(tg_id))
    return {
        "order": {
            column.name: getattr(order, column.name)
            for column in CryptoDonationOrders.__table__.columns
        },
        "credits_reward": reward,
        "new_donation": donation_total,
        "new_credits": mutation.after,
    }


def settle_payment(
    *,
    trade_id: str,
    callback_amount: float,
    actual_amount: float,
    block_transaction_id: str | None,
    multiplier: float,
) -> dict | None:
    with get_session() as session:
        return settle_payment_tx(
            session,
            trade_id=trade_id,
            callback_amount=callback_amount,
            actual_amount=actual_amount,
            block_transaction_id=block_transaction_id,
            multiplier=multiplier,
        )


def delete_unpaid_order(order_id: str) -> bool:
    """Clean up a failed provider order without ever deleting a paid receipt."""
    from sqlalchemy import delete

    with get_session() as session:
        result = session.execute(
            delete(CryptoDonationOrders).where(
                CryptoDonationOrders.order_id == order_id,
                CryptoDonationOrders.status == 1,
            )
        )
        return result.rowcount == 1


def expire_orders(now_ms: int) -> list[dict]:
    """Claim expired orders and return only records actually transitioned."""
    with get_session() as session:
        result = session.execute(
            update(CryptoDonationOrders)
            .where(
                CryptoDonationOrders.status == 1,
                CryptoDonationOrders.expiration_time.is_not(None),
                CryptoDonationOrders.expiration_time <= now_ms,
            )
            .values(status=3, updated_at=datetime.now(settings.TZ).isoformat())
            .returning(*CryptoDonationOrders.__table__.columns)
        )
        return sorted(
            (dict(row) for row in result.mappings()), key=lambda row: row["created_at"]
        )


REASSIGNED_TG_ID_COLUMNS: tuple[str, ...] = ("crypto_donation_orders.user_id",)


def check_tg_id_reassign_tx(
    session, old_tg_id: int, new_tg_id: int
) -> list[TgIdReassignIssue]:
    return []


def reassign_tg_id_tx(session, old_tg_id: int, new_tg_id: int) -> dict[str, int]:
    result = session.execute(
        update(CryptoDonationOrders)
        .where(CryptoDonationOrders.user_id == int(old_tg_id))
        .values(user_id=int(new_tg_id))
    )
    return {"crypto_donation_orders.user_id": max(0, int(result.rowcount or 0))}
