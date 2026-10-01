import time
import traceback

from sqlalchemy import delete, func, select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.auction import exceptions as auction_exceptions
from app.domains.auction.models import AuctionBids, Auctions
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.identity.types import TgIdReassignIssue


class AuctionRepository:
    def create_auction(
        self,
        title: str,
        description: str,
        starting_price: float,
        end_time: int,
        created_by: int,
    ) -> int | None:
        """创建竞拍"""
        try:
            with get_session() as session:
                created_at = int(time.time())
                auction = Auctions(
                    title=title,
                    description=description,
                    starting_price=starting_price,
                    current_price=starting_price,
                    end_time=end_time,
                    created_by=created_by,
                    created_at=created_at,
                )
                session.add(auction)
                # flush, 拿到 id
                session.flush()
                return auction.id
        except Exception as e:
            logger.error(f"Error creating auction: {e}")
            return None

    def get_auction_by_id(self, auction_id: int) -> dict | None:
        """根据ID获取竞拍信息"""
        try:
            with get_session() as session:
                stmt = select(Auctions).where(Auctions.id == auction_id)
                auction = session.execute(stmt).scalar_one_or_none()

                if auction:
                    return {
                        "id": auction.id,
                        "title": auction.title or f"竞拍活动 #{auction.id}",
                        "description": auction.description or "无描述",
                        "starting_price": auction.starting_price or 0,
                        "current_price": auction.current_price
                        or auction.starting_price
                        or 0,
                        "end_time": auction.end_time,
                        "created_by": auction.created_by,
                        "created_at": auction.created_at,
                        "is_active": auction.is_active,
                        "winner_id": auction.winner_id,
                        "bid_count": auction.bid_count,
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting auction by id: {e}")
            return None

    def get_active_auctions(self, limit: int | None = None) -> list[dict]:
        """获取活跃竞拍列表"""
        try:
            with get_session() as session:
                current_time = int(time.time())
                stmt = (
                    select(Auctions)
                    .where(Auctions.is_active == 1, Auctions.end_time > current_time)
                    .order_by(Auctions.created_at.desc())
                )
                if limit is not None:
                    stmt = stmt.limit(limit)
                results = session.execute(stmt).scalars().all()

                auctions = []
                for auction in results:
                    auctions.append(
                        {
                            "id": auction.id,
                            "title": auction.title or f"竞拍活动 #{auction.id}",
                            "description": auction.description or "无描述",
                            "starting_price": auction.starting_price or 0,
                            "current_price": auction.current_price
                            or auction.starting_price
                            or 0,
                            "end_time": auction.end_time,
                            "created_by": auction.created_by,
                            "created_at": auction.created_at,
                            "is_active": auction.is_active,
                            "winner_id": auction.winner_id,
                            "bid_count": auction.bid_count,
                        }
                    )
                return auctions
        except Exception as e:
            logger.error(f"Error getting active auctions: {e}")
            return []

    def place_bid(self, auction_id: int, bidder_id: int, bid_amount: float) -> bool:
        """Place a bid while locking the auction row first."""
        try:
            with get_session() as session:
                bid_time = int(time.time())
                auction = session.execute(
                    select(Auctions)
                    .where(Auctions.id == int(auction_id))
                    .with_for_update()
                ).scalar_one_or_none()
                if not auction or not auction.is_active or auction.end_time <= bid_time:
                    return False
                if bid_amount <= auction.current_price:
                    return False
                session.add(
                    AuctionBids(
                        auction_id=int(auction_id),
                        bidder_id=int(bidder_id),
                        bid_amount=float(bid_amount),
                        bid_time=bid_time,
                    )
                )
                auction.current_price = float(bid_amount)
                auction.bid_count = int(auction.bid_count or 0) + 1
                return True
        except Exception as error:
            logger.error(f"Error placing bid: {error}")
            return False

    def get_auction_bids(self, auction_id: int, limit: int = 50) -> list[dict]:
        """获取竞拍出价记录"""
        try:
            with get_session() as session:
                stmt = (
                    select(AuctionBids)
                    .where(AuctionBids.auction_id == auction_id)
                    .order_by(AuctionBids.bid_time.desc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                bids = []
                for bid in results:
                    bids.append(
                        {
                            "id": bid.id,
                            "auction_id": bid.auction_id,
                            "bidder_id": bid.bidder_id,
                            "bid_amount": bid.bid_amount,
                            "bid_time": bid.bid_time,
                        }
                    )
                return bids
        except Exception as e:
            logger.error(f"Error getting auction bids: {e}")
            return []

    def get_user_highest_bid(self, auction_id: int, user_id: int) -> float | None:
        """获取用户在特定竞拍中的最高出价"""
        try:
            with get_session() as session:
                stmt = select(func.max(AuctionBids.bid_amount)).where(
                    AuctionBids.auction_id == auction_id,
                    AuctionBids.bidder_id == user_id,
                )
                result = session.execute(stmt).scalar()
                return result
        except Exception as e:
            logger.error(f"Error getting user highest bid: {e}")
            return None

    def get_auction_participants(
        self, auction_id: int, exclude_user_id: int | None = None
    ) -> list[int]:
        """获取拍卖的所有参与者（出价者）ID列表，可排除指定用户"""
        try:
            with get_session() as session:
                if exclude_user_id:
                    stmt = select(func.distinct(AuctionBids.bidder_id)).where(
                        AuctionBids.auction_id == auction_id,
                        AuctionBids.bidder_id != exclude_user_id,
                    )
                else:
                    stmt = select(func.distinct(AuctionBids.bidder_id)).where(
                        AuctionBids.auction_id == auction_id
                    )
                results = session.execute(stmt).scalars().all()
                return list(results)
        except Exception as e:
            logger.error(f"Error getting auction participants: {e}")
            return []

    def finish_expired_auctions(self) -> list[dict]:
        """结束过期的竞拍"""
        try:
            with get_session() as session:
                current_time = int(time.time())

                # 查找过期的活跃竞拍
                stmt = select(Auctions).where(
                    Auctions.is_active == 1, Auctions.end_time <= current_time
                )
                expired_auctions = session.execute(stmt).scalars().all()

                finished_auctions = []
                for auction in expired_auctions:
                    auction_id = auction.id

                    # 获取最高出价者
                    highest_bid_stmt = (
                        select(AuctionBids.bidder_id, func.max(AuctionBids.bid_amount))
                        .where(AuctionBids.auction_id == auction_id)
                        .group_by(AuctionBids.auction_id)
                    )
                    highest_bid = session.execute(highest_bid_stmt).fetchone()

                    winner_id = highest_bid[0] if highest_bid else None
                    final_price = auction.current_price
                    credits_reduced = False

                    # 如果有获胜者，扣除其积分
                    if winner_id and highest_bid:
                        final_price = highest_bid[1]

                        try:
                            credits_repository.deduct_tx(
                                session, CreditAccount.tg(int(winner_id)), final_price
                            )
                            credits_reduced = True
                            logger.info(
                                f"Auction {auction_id} finished: deducted {final_price} credits from winner {winner_id}"
                            )
                        except ValueError:
                            logger.warning(
                                f"Winner {winner_id} has insufficient credits for auction {auction_id} (price: {final_price})"
                            )

                    # 更新竞拍状态
                    session.execute(
                        update(Auctions)
                        .where(Auctions.id == auction_id)
                        .values(
                            is_active=0, winner_id=winner_id, current_price=final_price
                        )
                    )

                    finished_auctions.append(
                        {
                            "id": auction_id,
                            "title": auction.title or f"竞拍活动 #{auction_id}",
                            "winner_id": winner_id,
                            "final_price": final_price,
                            "credits_reduced": credits_reduced,
                        }
                    )
                return finished_auctions
        except Exception as e:
            logger.error(f"Error finishing expired auctions: {e}")
            logger.error(traceback.format_exc())
            return []

    def get_auction_stats(self) -> dict:
        """获取竞拍统计数据"""
        try:
            with get_session() as session:
                current_time = int(time.time())

                # 总竞拍数
                total_auctions = session.execute(
                    select(func.count(Auctions.id))
                ).scalar()

                # 活跃竞拍数
                active_auctions = session.execute(
                    select(func.count(Auctions.id)).where(
                        Auctions.is_active == 1, Auctions.end_time > current_time
                    )
                ).scalar()

                # 总出价数
                total_bids = session.execute(
                    select(func.count(AuctionBids.id))
                ).scalar()

                # 总成交价值
                total_value = (
                    session.execute(
                        select(func.sum(Auctions.current_price)).where(
                            Auctions.winner_id.isnot(None)
                        )
                    ).scalar()
                    or 0.0
                )

                return {
                    "total_auctions": total_auctions,
                    "active_auctions": active_auctions,
                    "total_bids": total_bids,
                    "total_value": float(total_value),
                }
        except Exception as e:
            logger.error(f"Error getting auction stats: {e}")
            return {
                "total_auctions": 0,
                "active_auctions": 0,
                "total_bids": 0,
                "total_value": 0.0,
            }

    def get_all_auctions(
        self, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        """获取所有竞拍活动（管理员用）"""
        try:
            with get_session() as session:
                current_time = int(time.time())

                if status == "active":
                    stmt = (
                        select(Auctions)
                        .where(
                            Auctions.is_active == 1, Auctions.end_time > current_time
                        )
                        .order_by(Auctions.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                elif status == "ended":
                    stmt = (
                        select(Auctions)
                        .where(
                            (Auctions.is_active == 0)
                            | (Auctions.end_time <= current_time)
                        )
                        .order_by(Auctions.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                else:
                    stmt = (
                        select(Auctions)
                        .order_by(Auctions.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )

                results = session.execute(stmt).scalars().all()

                auctions = []
                for auction in results:
                    # 获取出价数量
                    bid_count = session.execute(
                        select(func.count(AuctionBids.id)).where(
                            AuctionBids.auction_id == auction.id
                        )
                    ).scalar()

                    # 判断状态
                    if not auction.is_active or auction.end_time <= current_time:
                        auction_status = "ended"
                    else:
                        auction_status = "active"

                    auctions.append(
                        {
                            "id": auction.id,
                            "title": auction.title or f"竞拍活动 #{auction.id}",
                            "description": auction.description or "无描述",
                            "starting_price": auction.starting_price or 0,
                            "current_price": auction.current_price
                            or auction.starting_price
                            or 0,
                            "end_time": auction.end_time,
                            "created_by": auction.created_by,
                            "created_at": auction.created_at,
                            "is_active": bool(auction.is_active),
                            "winner_id": auction.winner_id,
                            "bid_count": bid_count,
                            "status": auction_status,
                        }
                    )

                return auctions
        except Exception as e:
            logger.error(f"Error getting all auctions: {e}")
            return []

    def update_auction(self, auction_id: int, update_data: dict) -> bool:
        """更新竞拍活动"""
        try:
            with get_session() as session:
                values_to_update = {}

                if "title" in update_data:
                    values_to_update["title"] = update_data["title"]
                if "description" in update_data:
                    values_to_update["description"] = update_data["description"]
                if "starting_price" in update_data:
                    values_to_update["starting_price"] = update_data["starting_price"]
                if "end_time" in update_data:
                    values_to_update["end_time"] = update_data["end_time"]

                if not values_to_update:
                    return False

                result = session.execute(
                    update(Auctions)
                    .where(Auctions.id == auction_id)
                    .values(**values_to_update)
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating auction: {e}")
            return False

    def delete_auction(self, auction_id: int) -> bool:
        """删除竞拍活动"""
        try:
            with get_session() as session:
                # 先删除相关的出价记录
                session.execute(
                    delete(AuctionBids).where(AuctionBids.auction_id == auction_id)
                )

                # 再删除竞拍活动
                result = session.execute(
                    delete(Auctions).where(Auctions.id == auction_id)
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting auction: {e}")
            return False

    def finish_auction_by_id(self, auction_id: int) -> tuple:
        """Finish an auction once, under the auction-row lock."""
        try:
            with get_session() as session:
                result = finish_auction_tx(session, int(auction_id))
                if result is None:
                    return False, "竞拍已结束"
                return True, result
        except auction_exceptions.AuctionError as error:
            return False, str(error)
        except Exception as error:
            logger.error(f"Error finishing auction {auction_id}: {error}")
            logger.error(traceback.format_exc())
            return False, str(error)

    def get_user_auction_history(self, user_id: int, limit: int = 20) -> list[dict]:
        """获取用户参与的竞拍历史"""
        try:
            with get_session() as session:
                # 获取用户参与的竞拍
                stmt = (
                    select(Auctions)
                    .join(AuctionBids, Auctions.id == AuctionBids.auction_id)
                    .where(AuctionBids.bidder_id == user_id)
                    .order_by(Auctions.created_at.desc())
                    .limit(limit)
                    .distinct()
                )
                results = session.execute(stmt).scalars().all()

                auctions = []
                for auction in results:
                    # 获取用户最高出价
                    highest_bid = session.execute(
                        select(func.max(AuctionBids.bid_amount)).where(
                            AuctionBids.auction_id == auction.id,
                            AuctionBids.bidder_id == user_id,
                        )
                    ).scalar()

                    auctions.append(
                        {
                            "id": auction.id,
                            "title": auction.title or f"竞拍活动 #{auction.id}",
                            "description": auction.description or "无描述",
                            "starting_price": auction.starting_price or 0,
                            "current_price": auction.current_price
                            or auction.starting_price
                            or 0,
                            "end_time": auction.end_time,
                            "created_by": auction.created_by,
                            "created_at": auction.created_at,
                            "is_active": bool(auction.is_active),
                            "winner_id": auction.winner_id,
                            "user_highest_bid": highest_bid,
                            "is_winner": auction.winner_id == user_id,
                        }
                    )

                return auctions
        except Exception as e:
            logger.error(f"Error getting user auction history: {e}")
            return []

    def get_detailed_auction_stats(
        self, start_date: int | None = None, end_date: int | None = None
    ) -> dict:
        """获取详细的竞拍统计数据"""
        try:
            with get_session() as session:
                # 设置默认时间范围（如果未提供）
                if not start_date:
                    start_date = 0
                if not end_date:
                    end_date = int(time.time())

                # 基本统计
                stats = self.get_auction_stats()

                # 时间段内的统计
                period_auctions = session.execute(
                    select(func.count(Auctions.id)).where(
                        Auctions.created_at.between(start_date, end_date)
                    )
                ).scalar()

                # 时间段内的出价数
                period_bids = session.execute(
                    select(func.count(AuctionBids.id))
                    .join(Auctions, AuctionBids.auction_id == Auctions.id)
                    .where(Auctions.created_at.between(start_date, end_date))
                ).scalar()

                # 平均出价数
                avg_bids = (
                    session.execute(
                        select(func.avg(func.count(AuctionBids.id))).group_by(
                            AuctionBids.auction_id
                        )
                    ).scalar()
                    or 0.0
                )

                # 最高成交价
                highest_price = (
                    session.execute(
                        select(func.max(Auctions.current_price)).where(
                            Auctions.winner_id.isnot(None)
                        )
                    ).scalar()
                    or 0.0
                )

                stats.update(
                    {
                        "period_auctions": period_auctions,
                        "period_bids": period_bids,
                        "avg_bids_per_auction": float(avg_bids),
                        "highest_transaction": float(highest_price),
                        "start_date": start_date,
                        "end_date": end_date,
                    }
                )

                return stats
        except Exception as e:
            logger.error(f"Error getting detailed auction stats: {e}")
            return self.get_auction_stats()


def count_participated_auctions_tx(session, tg_id: int, since: int, until: int) -> int:
    """指定时间窗内出价过的竞拍场次（按 auction 去重，闭区间，秒级时间戳）。"""
    return int(
        session.execute(
            select(func.count(func.distinct(AuctionBids.auction_id))).where(
                AuctionBids.bidder_id == int(tg_id),
                AuctionBids.bid_time >= int(since),
                AuctionBids.bid_time <= int(until),
            )
        ).scalar_one()
    )


# Module-level API used by the promoted service.  The transitional facade class
# remains available to legacy callers until the final facade-removal task.
_repository = AuctionRepository()


def finish_auction_tx(session, auction_id: int) -> dict | None:
    """Finish one auction under the auction-row lock.

    ``None`` means another worker already finished it.  The caller owns the
    transaction and therefore controls when post-commit notifications run.
    """
    auction = session.execute(
        select(Auctions).where(Auctions.id == int(auction_id)).with_for_update()
    ).scalar_one_or_none()
    if auction is None:
        raise auction_exceptions.not_found()
    if not auction.is_active:
        return None
    highest_bid = session.execute(
        select(AuctionBids)
        .where(AuctionBids.auction_id == int(auction_id))
        .order_by(
            AuctionBids.bid_amount.desc(),
            AuctionBids.bid_time.asc(),
            AuctionBids.id.asc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    winner_id = int(highest_bid.bidder_id) if highest_bid is not None else None
    final_price = float(
        highest_bid.bid_amount if highest_bid is not None else auction.starting_price
    )
    credits_reduced = False
    if winner_id is not None:
        try:
            credits_repository.deduct_tx(
                session, CreditAccount.tg(winner_id), final_price
            )
            credits_reduced = True
        except ValueError:
            logger.warning(
                "Winner %s has insufficient credits for auction %s (price: %s)",
                winner_id,
                auction_id,
                final_price,
            )
    session.execute(
        update(Auctions)
        .where(Auctions.id == int(auction_id), Auctions.is_active == 1)
        .values(is_active=0, winner_id=winner_id, current_price=final_price)
    )
    return {
        "id": int(auction_id),
        "title": auction.title or f"竞拍活动 #{auction_id}",
        "winner_id": winner_id,
        "final_price": final_price,
        "credits_reduced": credits_reduced,
    }


def finish_auction(auction_id: int) -> dict | None:
    with get_session() as session:
        return finish_auction_tx(session, int(auction_id))


def get_expired_auction_ids(*, now: int | None = None) -> list[int]:
    current_time = int(time.time()) if now is None else int(now)
    with get_session() as session:
        return [
            int(auction_id)
            for (auction_id,) in session.execute(
                select(Auctions.id)
                .where(Auctions.is_active == 1, Auctions.end_time <= current_time)
                .order_by(Auctions.id.asc())
            ).all()
        ]


def get_active_auction_ids() -> list[int]:
    with get_session() as session:
        return [
            int(auction_id)
            for (auction_id,) in session.execute(
                select(Auctions.id).where(Auctions.is_active == 1)
            )
            .scalars()
            .all()
        ]


def create_auction(
    *,
    title: str,
    description: str,
    starting_price: float,
    end_time: int,
    created_by: int,
) -> int | None:
    return _repository.create_auction(
        title, description, starting_price, end_time, created_by
    )


def get_auction_by_id(auction_id: int) -> dict | None:
    return _repository.get_auction_by_id(int(auction_id))


def get_active_auctions(*, limit: int | None = None) -> list[dict]:
    return _repository.get_active_auctions(
        limit=int(limit) if limit is not None else None
    )


def place_bid(*, auction_id: int, bidder_id: int, bid_amount: float) -> bool:
    return _repository.place_bid(int(auction_id), int(bidder_id), float(bid_amount))


def get_auction_bids(*, auction_id: int, limit: int = 50) -> list[dict]:
    return _repository.get_auction_bids(int(auction_id), limit=int(limit))


def get_user_highest_bid(auction_id: int, user_id: int) -> float | None:
    return _repository.get_user_highest_bid(int(auction_id), int(user_id))


def get_auction_participants(
    auction_id: int, *, exclude_user_id: int | None = None
) -> list[int]:
    return _repository.get_auction_participants(
        int(auction_id), exclude_user_id=exclude_user_id
    )


def finish_expired_auctions() -> list[dict]:
    return _repository.finish_expired_auctions()


def get_auction_stats() -> dict:
    return _repository.get_auction_stats()


def get_all_auctions(
    *, status: str | None = None, limit: int = 50, offset: int = 0
) -> list[dict]:
    return _repository.get_all_auctions(
        status=status, limit=int(limit), offset=int(offset)
    )


def update_auction(auction_id: int, update_data: dict) -> bool:
    return _repository.update_auction(int(auction_id), update_data)


def delete_auction(auction_id: int) -> bool:
    return _repository.delete_auction(int(auction_id))


def finish_auction_by_id(auction_id: int) -> tuple:
    return _repository.finish_auction_by_id(int(auction_id))


def get_user_auction_history(user_id: int, *, limit: int = 20) -> list[dict]:
    return _repository.get_user_auction_history(int(user_id), limit=int(limit))


def get_detailed_auction_stats(
    *, start_date: int | None = None, end_date: int | None = None
) -> dict:
    return _repository.get_detailed_auction_stats(
        start_date=start_date, end_date=end_date
    )


__all__ = [
    "AuctionRepository",
    "count_participated_auctions_tx",
    "create_auction",
    "delete_auction",
    "finish_auction",
    "finish_auction_by_id",
    "finish_auction_tx",
    "finish_expired_auctions",
    "get_active_auction_ids",
    "get_active_auctions",
    "get_all_auctions",
    "get_auction_bids",
    "get_auction_by_id",
    "get_auction_participants",
    "get_auction_stats",
    "get_detailed_auction_stats",
    "get_expired_auction_ids",
    "get_user_auction_history",
    "get_user_highest_bid",
    "place_bid",
    "update_auction",
]


REASSIGNED_TG_ID_COLUMNS: tuple[str, ...] = (
    "auction_bids.bidder_id",
    "auctions.winner_id",
    "auctions.created_by",
)


def check_tg_id_reassign_tx(
    session, old_tg_id: int, new_tg_id: int
) -> list[TgIdReassignIssue]:
    return []


def reassign_tg_id_tx(session, old_tg_id: int, new_tg_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model, column in (
        (AuctionBids, AuctionBids.bidder_id),
        (Auctions, Auctions.winner_id),
        (Auctions, Auctions.created_by),
    ):
        result = session.execute(
            update(model)
            .where(column == int(old_tg_id))
            .values({column: int(new_tg_id)})
        )
        counts[f"{model.__tablename__}.{column.key}"] = max(
            0, int(result.rowcount or 0)
        )
    return counts
