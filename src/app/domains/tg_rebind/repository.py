import traceback

from sqlalchemy import func, select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.auction.models import AuctionBids, Auctions
from app.domains.badges.models import UserBadge
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.crypto_donation.models import CryptoDonationOrders
from app.domains.custom_lines.models import CustomLine
from app.domains.donation.models import DonationRegistrations
from app.domains.identity.models import EmbyUser, Overseerr, PlexUser, Statistics
from app.domains.invitation.models import Invitation
from app.domains.lines.models import LineSchedule
from app.domains.luckywheel.models import WheelStats
from app.domains.prediction.models import (
    PredictionBet,
    PredictionMarket,
    PredictionMarketSubmission,
)
from app.domains.treasure.models import TreasureIssue, TreasureParticipation
from app.domains.vaultwarden.models import VaultwardenRedeemRecords


class TgRebindRepository:
    def rebind_user_tg_id(
        self,
        new_tg_id: int,
        plex_email: str | None = None,
        emby_username: str | None = None,
    ) -> bool:
        """
        换绑用户 Telegram ID
        通过 plex_email 或 emby_username 查找用户并更新其 tg_id
        会同时更新所有相关表（PlexUser/EmbyUser, Statistics, Overseerr, WheelStats,
        VaultwardenRedeemRecords, LineSchedule, UserBadge, Invitation, Auctions,
        AuctionBids, DonationRegistrations, CryptoDonationOrders, TreasureIssue,
        TreasureParticipation, PredictionMarket, PredictionMarketSubmission,
        PredictionBet, CustomLine）

        Args:
            new_tg_id: 新的 Telegram ID
            plex_email: Plex 用户邮箱（可选）
            emby_username: Emby 用户名（可选）

        Returns:
            bool: 操作是否成功
        """
        if plex_email is None and emby_username is None:
            logger.error("Error: plex_email and emby_username cannot both be None")
            return False

        try:
            with get_session() as session:
                old_tg_ids = set()
                updated = False

                # 处理 Plex 用户
                if plex_email is not None:
                    # 先获取旧的 tg_id
                    stmt = select(PlexUser.tg_id).where(
                        func.lower(PlexUser.plex_email) == plex_email.lower()
                    )
                    old_tg_id = session.execute(stmt).scalar_one_or_none()

                    # 更新 PlexUser 表
                    result = session.execute(
                        update(PlexUser)
                        .where(func.lower(PlexUser.plex_email) == plex_email.lower())
                        .values(tg_id=new_tg_id)
                    )
                    if result.rowcount > 0:
                        updated = True
                        if old_tg_id is not None:
                            old_tg_ids.add(old_tg_id)
                        logger.info(
                            f"Updated tg_id for Plex user '{plex_email}' to {new_tg_id}"
                        )
                    else:
                        logger.warning(f"No Plex user found with email '{plex_email}'")

                # 处理 Emby 用户
                if emby_username is not None:
                    # 先获取旧的 tg_id
                    stmt = select(EmbyUser.tg_id).where(
                        EmbyUser.emby_username == emby_username
                    )
                    old_tg_id = session.execute(stmt).scalar_one_or_none()

                    # 更新 EmbyUser 表
                    result = session.execute(
                        update(EmbyUser)
                        .where(EmbyUser.emby_username == emby_username)
                        .values(tg_id=new_tg_id)
                    )
                    if result.rowcount > 0:
                        updated = True
                        if old_tg_id is not None:
                            old_tg_ids.add(old_tg_id)
                        logger.info(
                            f"Updated tg_id for Emby user '{emby_username}' to {new_tg_id}"
                        )
                    else:
                        logger.warning(
                            f"No Emby user found with username '{emby_username}'"
                        )

                # 更新所有其他相关表的 tg_id
                if updated and old_tg_ids:
                    # 引用 statistics.tg_id 但未建外键约束的列：任何换绑场景都需显式迁移
                    plain_ref_columns = [
                        (Overseerr, "tg_id"),
                        (WheelStats, "tg_id"),
                        (Invitation, "owner"),
                        (Auctions, "created_by"),
                        (Auctions, "winner_id"),
                        (AuctionBids, "bidder_id"),
                        (TreasureIssue, "winner_tg_id"),
                        (TreasureIssue, "created_by"),
                        (TreasureParticipation, "tg_id"),
                        (PredictionMarket, "created_by"),
                        (PredictionMarket, "resolved_by"),
                        (PredictionMarketSubmission, "submitter_tg_id"),
                        (PredictionMarketSubmission, "reviewed_by"),
                        (PredictionBet, "tg_id"),
                    ]
                    # 设有 statistics.tg_id 外键（ON UPDATE CASCADE）的列：
                    # 换绑到全新 ID 时随 statistics 主键更新自动级联，无需显式迁移；
                    # 合并到已存在 ID 时不触发级联，需显式迁移
                    fk_ref_columns = [
                        (VaultwardenRedeemRecords, "tg_id"),
                        (LineSchedule, "tg_id"),
                        (UserBadge, "tg_id"),
                        (DonationRegistrations, "user_id"),
                        (DonationRegistrations, "processed_by"),
                        (CryptoDonationOrders, "user_id"),
                        (CustomLine, "tg_id"),
                        (CustomLine, "approved_by"),
                    ]

                    for old_tg_id in old_tg_ids:
                        # tg_id 未变化时无需迁移
                        if old_tg_id == new_tg_id:
                            continue

                        locked_ids = sorted({int(old_tg_id), int(new_tg_id)})
                        locked_stats = {
                            tg_id: session.execute(
                                select(Statistics)
                                .where(Statistics.tg_id == tg_id)
                                .with_for_update()
                            )
                            .scalars()
                            .one_or_none()
                            for tg_id in locked_ids
                        }
                        old_stat = locked_stats.get(int(old_tg_id))
                        new_stat = locked_stats.get(int(new_tg_id))
                        merging = old_stat is not None and new_stat is not None

                        # 无外键约束的列在任何场景都需显式迁移
                        columns_to_migrate = list(plain_ref_columns)

                        if old_stat is not None and new_stat is None:
                            # 目标为全新 ID：直接改 statistics 主键，
                            # 引用它且设了 ON UPDATE CASCADE 的子表会自动跟随
                            old_stat.tg_id = new_tg_id
                            session.flush()
                            logger.info(
                                f"Migrated Statistics tg_id (cascade): {old_tg_id} -> {new_tg_id}"
                            )
                        elif merging:
                            # 目标 ID 已存在：合并积分；外键列不触发级联，需显式迁移
                            new_stat.donation += old_stat.donation
                            old_credits = float(old_stat.credits or 0)
                            if old_credits > 0:
                                mutation = credits_service.add_tx(
                                    session,
                                    CreditAccount.tg(int(new_tg_id)),
                                    old_credits,
                                )
                                credits_service.register_cache_invalidation(
                                    session, mutation
                                )
                            session.flush()
                            columns_to_migrate += fk_ref_columns

                        for model, attr in columns_to_migrate:
                            column = getattr(model, attr)
                            result = session.execute(
                                update(model)
                                .where(column == old_tg_id)
                                .values({column: new_tg_id})
                            )
                            if result.rowcount > 0:
                                logger.info(
                                    f"Migrated {result.rowcount} {model.__tablename__}.{attr}: {old_tg_id} -> {new_tg_id}"
                                )

                        if merging:
                            # 外键引用均已迁出，删除旧 Statistics 记录
                            session.delete(old_stat)
                            session.flush()
                            logger.info(
                                f"Removed merged Statistics record: {old_tg_id} -> {new_tg_id}"
                            )

                return updated
        except Exception as e:
            logger.error(f"Error rebinding user tg_id: {e}")
            traceback.print_exc()
            return False
