from datetime import datetime

from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.donation.models import DonationRegistrations
from app.domains.identity.models import Statistics


class DonationRepository:
    def update_user_donation(self, donation: float, tg_id: int) -> bool:
        """更新用户捐赠金额"""
        try:
            with get_session() as session:
                session.execute(
                    update(Statistics)
                    .where(Statistics.tg_id == tg_id)
                    .values(donation=donation)
                )
                return True
        except Exception as e:
            logger.error(f"Error updating user donation: {e}")
            return False

    def create_donation_registration(
        self,
        user_id: int,
        payment_method: str,
        amount: float,
        note: str | None = None,
        is_donation_registration: bool = False,
    ) -> bool:
        """创建捐赠登记记录"""
        try:
            with get_session() as session:
                created_at = datetime.now(settings.TZ).isoformat()

                # 确保统计信息存在以通过外键校验
                stats_exists = session.execute(
                    select(Statistics.tg_id).where(Statistics.tg_id == user_id)
                ).scalar_one_or_none()
                if not stats_exists:
                    session.add(Statistics(tg_id=user_id, credits=0, donation=0))
                    session.flush()

                donation = DonationRegistrations(
                    user_id=user_id,
                    payment_method=payment_method,
                    amount=amount,
                    note=note,
                    created_at=created_at,
                    is_donation_registration=int(is_donation_registration),
                )
                session.add(donation)
                return True
        except Exception as e:
            logger.error(f"创建捐赠登记失败: {e}")
            return False

    def get_donation_registration_by_id(self, registration_id: int) -> dict | None:
        """根据ID获取捐赠登记信息"""
        try:
            from app.core.telegram import get_user_name_from_tg_id

            with get_session() as session:
                stmt = select(DonationRegistrations).where(
                    DonationRegistrations.id == registration_id
                )
                result = session.execute(stmt).scalar_one_or_none()

                if result:
                    user_id = result.user_id
                    processed_by = result.processed_by

                    return {
                        "id": result.id,
                        "user_id": user_id,
                        "payment_method": result.payment_method,
                        "amount": result.amount,
                        "note": result.note,
                        "status": result.status,
                        "admin_note": result.admin_note,
                        "created_at": result.created_at,
                        "processed_at": result.processed_at,
                        "processed_by": processed_by,
                        "is_donation_registration": bool(
                            result.is_donation_registration
                        ),
                        "username": get_user_name_from_tg_id(user_id),
                        "processed_by_username": get_user_name_from_tg_id(processed_by)
                        if processed_by
                        else None,
                    }
                return None
        except Exception as e:
            logger.error(f"获取捐赠登记信息失败: {e}")
            return None

    def get_donation_registrations_by_user(
        self, user_id: int, limit: int = 20
    ) -> list[dict]:
        """获取用户的捐赠登记历史"""
        try:
            from app.core.telegram import get_user_name_from_tg_id

            with get_session() as session:
                stmt = (
                    select(DonationRegistrations)
                    .where(DonationRegistrations.user_id == user_id)
                    .order_by(DonationRegistrations.created_at.desc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                registrations = []
                for result in results:
                    user_id_result = result.user_id
                    processed_by = result.processed_by

                    registrations.append(
                        {
                            "id": result.id,
                            "user_id": user_id_result,
                            "payment_method": result.payment_method,
                            "amount": result.amount,
                            "note": result.note,
                            "status": result.status,
                            "admin_note": result.admin_note,
                            "created_at": result.created_at,
                            "processed_at": result.processed_at,
                            "processed_by": processed_by,
                            "is_donation_registration": bool(
                                result.is_donation_registration
                            ),
                            "username": get_user_name_from_tg_id(user_id_result),
                            "processed_by_username": get_user_name_from_tg_id(
                                processed_by
                            )
                            if processed_by
                            else None,
                        }
                    )
                return registrations
        except Exception as e:
            logger.error(f"获取用户捐赠登记历史失败: {e}")
            return []

    def get_pending_donation_registrations(self, limit: int = 50) -> list[dict]:
        """获取待处理的捐赠登记列表"""
        try:
            from app.core.telegram import get_user_name_from_tg_id

            with get_session() as session:
                stmt = (
                    select(DonationRegistrations)
                    .where(DonationRegistrations.status == "pending")
                    .order_by(DonationRegistrations.created_at.asc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                registrations = []
                for result in results:
                    user_id = result.user_id
                    processed_by = result.processed_by

                    registrations.append(
                        {
                            "id": result.id,
                            "user_id": user_id,
                            "payment_method": result.payment_method,
                            "amount": result.amount,
                            "note": result.note,
                            "status": result.status,
                            "admin_note": result.admin_note,
                            "created_at": result.created_at,
                            "processed_at": result.processed_at,
                            "processed_by": processed_by,
                            "is_donation_registration": bool(
                                result.is_donation_registration
                            ),
                            "username": get_user_name_from_tg_id(user_id),
                            "processed_by_username": get_user_name_from_tg_id(
                                processed_by
                            )
                            if processed_by
                            else None,
                        }
                    )
                return registrations
        except Exception as e:
            logger.error(f"获取待处理捐赠登记失败: {e}")
            return []

    def confirm_donation_registration(
        self,
        registration_id: int,
        approved: bool,
        admin_note: str | None = None,
        processed_by: int | None = None,
    ) -> bool:
        """确认捐赠登记状态"""
        try:
            with get_session() as session:
                processed_at = datetime.now(settings.TZ).isoformat()
                status = "approved" if approved else "rejected"

                session.execute(
                    update(DonationRegistrations)
                    .where(DonationRegistrations.id == registration_id)
                    .values(
                        status=status,
                        admin_note=admin_note,
                        processed_at=processed_at,
                        processed_by=processed_by,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"确认捐赠登记失败: {e}")
            return False

    def delete_donation_registration(self, registration_id: int) -> bool:
        """删除捐赠登记记录"""
        try:
            with get_session() as session:
                session.execute(
                    delete(DonationRegistrations).where(
                        DonationRegistrations.id == registration_id
                    )
                )
                return True
        except Exception as e:
            logger.error(f"删除捐赠登记失败: {e}")
            return False

    def get_donation_statistics(self) -> dict:
        """获取捐赠统计信息"""
        try:
            with get_session() as session:
                # 总登记数
                total_registrations = session.execute(
                    select(func.count(DonationRegistrations.id))
                ).scalar()

                # 待处理数
                pending_registrations = session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "pending"
                    )
                ).scalar()

                # 已批准数
                approved_registrations = session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "approved"
                    )
                ).scalar()

                # 已拒绝数
                rejected_registrations = session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "rejected"
                    )
                ).scalar()

                # 总捐赠金额（已批准的）
                total_amount = session.execute(
                    select(func.sum(DonationRegistrations.amount)).where(
                        DonationRegistrations.status == "approved"
                    )
                ).scalar()
                total_amount = float(total_amount) if total_amount else 0.0

                return {
                    "total_registrations": total_registrations,
                    "pending_registrations": pending_registrations,
                    "approved_registrations": approved_registrations,
                    "rejected_registrations": rejected_registrations,
                    "total_approved_amount": total_amount,
                }
        except Exception as e:
            logger.error(f"获取捐赠统计信息失败: {e}")
            return {
                "total_registrations": 0,
                "pending_registrations": 0,
                "approved_registrations": 0,
                "rejected_registrations": 0,
                "total_approved_amount": 0.0,
            }


def update_donation_credits(old_multiplier: float, new_multiplier: float) -> None:
    """Reprice all donation credits in one caller-owned transaction."""
    from app.domains.credits import repository as credits_repository
    from app.domains.credits import service as credits_service
    from app.domains.credits.types import CreditAccount

    with get_session() as session:
        donations = session.execute(
            select(Statistics.tg_id, Statistics.donation, Statistics.credits)
            .where(Statistics.donation > 0)
            .with_for_update()
        ).all()
        for tg_id, donation, credits in donations:
            delta = round(float(donation) * (new_multiplier - old_multiplier), 2)
            if delta > 0:
                mutation = credits_repository.add_tx(
                    session, CreditAccount.tg(int(tg_id)), delta
                )
            elif delta < 0:
                mutation = credits_repository.deduct_tx(
                    session, CreditAccount.tg(int(tg_id)), -delta
                )
            else:
                continue
            credits_service.register_cache_invalidation(session, mutation)
            logger.info(
                f"用户 {tg_id} 捐赠：{donation}, 更新积分: {credits} -> {mutation.after}"
            )
