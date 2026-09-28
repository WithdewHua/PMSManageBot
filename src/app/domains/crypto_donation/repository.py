import time
from datetime import datetime

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.crypto_donation.config import CRYPTO_DONATION_CONFIG
from app.domains.crypto_donation.models import CryptoDonationOrders


class CryptoDonationRepository:
    def create_crypto_donation_order(
        self,
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
        self,
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

                session.execute(
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
                return True
        except Exception as e:
            logger.error(f"更新 crypto 捐赠订单 UPAY 信息失败: {e}")
            return False

    def complete_crypto_donation_order(
        self,
        trade_id: str,
        block_transaction_id: str,
        actual_amount: float,
    ) -> bool:
        """完成 crypto 捐赠订单支付"""
        try:
            with get_session() as session:
                paid_at = datetime.now(settings.TZ).isoformat()
                updated_at = paid_at

                session.execute(
                    update(CryptoDonationOrders)
                    .where(CryptoDonationOrders.trade_id == trade_id)
                    .values(
                        status=2,
                        block_transaction_id=block_transaction_id,
                        actual_amount=actual_amount,
                        paid_at=paid_at,
                        updated_at=updated_at,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"完成 crypto 捐赠订单支付失败: {e}")
            return False

    def get_crypto_donation_order_by_order_id(self, order_id: str) -> dict | None:
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

    def get_crypto_donation_order_by_trade_id(self, trade_id: str) -> dict | None:
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

    def get_crypto_donation_orders_by_user(
        self, user_id: int, limit: int = 20
    ) -> list[dict]:
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
        self, limit: int = 100, offset: int = 0, status_filter: str | None = None
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

    def get_crypto_donation_orders_count(self, status_filter: str | None = None) -> int:
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

    def get_expired_crypto_donation_orders(self) -> list[dict]:
        """获取所有已过期但状态仍为等待支付的 crypto 捐赠订单"""
        try:
            with get_session() as session:
                current_time = int(time.time() * 1000)  # 当前时间的毫秒时间戳

                stmt = (
                    select(CryptoDonationOrders)
                    .where(
                        CryptoDonationOrders.status == 1,
                        CryptoDonationOrders.expiration_time.isnot(None),
                        CryptoDonationOrders.expiration_time <= current_time,
                    )
                    .order_by(CryptoDonationOrders.created_at.asc())
                )
                results = session.execute(stmt).scalars().all()

                expired_orders = []
                for result in results:
                    expired_orders.append(
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
                return expired_orders
        except Exception as e:
            logger.error(f"获取过期 crypto 捐赠订单失败: {e}")
            return []

    def update_expired_crypto_donation_orders(self) -> int:
        """批量更新已过期的 crypto 捐赠订单状态为已过期(3)"""
        try:
            with get_session() as session:
                current_time = int(time.time() * 1000)  # 当前时间的毫秒时间戳
                updated_at = datetime.now(settings.TZ).isoformat()

                # 更新所有过期的订单状态
                result = session.execute(
                    update(CryptoDonationOrders)
                    .where(
                        CryptoDonationOrders.status == 1,
                        CryptoDonationOrders.expiration_time.isnot(None),
                        CryptoDonationOrders.expiration_time <= current_time,
                    )
                    .values(status=3, updated_at=updated_at)
                )
                updated_count = result.rowcount

                if updated_count > 0:
                    logger.info(
                        f"成功更新 {updated_count} 个过期的 crypto 捐赠订单状态"
                    )

                return updated_count
        except Exception as e:
            logger.error(f"更新过期 crypto 捐赠订单状态失败: {e}")
            return 0
