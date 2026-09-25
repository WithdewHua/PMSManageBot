import time
import traceback

from sqlalchemy import delete, func, select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.auction.models import AuctionBids, Auctions
from app.domains.identity.models import Statistics


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

    def get_active_auctions(self, limit: int = 50) -> list[dict]:
        """获取活跃竞拍列表"""
        try:
            with get_session() as session:
                current_time = int(time.time())
                stmt = (
                    select(Auctions)
                    .where(Auctions.is_active == 1, Auctions.end_time > current_time)
                    .order_by(Auctions.created_at.desc())
                    .limit(limit)
                )
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
        """出价"""
        try:
            with get_session() as session:
                bid_time = int(time.time())

                # 检查竞拍是否存在且活跃
                auction = session.execute(
                    select(Auctions).where(Auctions.id == auction_id)
                ).scalar_one_or_none()

                if not auction or not auction.is_active or auction.end_time <= bid_time:
                    return False

                # 检查出价是否高于当前价格
                if bid_amount <= auction.current_price:
                    return False

                # 插入出价记录
                bid = AuctionBids(
                    auction_id=auction_id,
                    bidder_id=bidder_id,
                    bid_amount=bid_amount,
                    bid_time=bid_time,
                )
                session.add(bid)

                # 更新竞拍当前价格和出价次数
                session.execute(
                    update(Auctions)
                    .where(Auctions.id == auction_id)
                    .values(current_price=bid_amount, bid_count=Auctions.bid_count + 1)
                )
                return True
        except Exception as e:
            logger.error(f"Error placing bid: {e}")
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

                        # 获取用户当前积分
                        stats = session.execute(
                            select(Statistics).where(Statistics.tg_id == winner_id)
                        ).scalar_one_or_none()

                        if stats and stats.credits >= final_price:
                            session.execute(
                                update(Statistics)
                                .where(Statistics.tg_id == winner_id)
                                .values(credits=Statistics.credits - final_price)
                            )
                            credits_reduced = True
                            logger.info(
                                f"Auction {auction_id} finished: deducted {final_price} credits from winner {winner_id}"
                            )
                        else:
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
        """手动结束指定竞拍活动"""
        try:
            with get_session() as session:
                # 获取竞拍信息
                auction = session.execute(
                    select(Auctions).where(Auctions.id == auction_id)
                ).scalar_one_or_none()

                if not auction:
                    return False, f"竞拍 id {auction_id} 不存在"

                # 获取最高出价
                highest_bid_stmt = (
                    select(AuctionBids.bidder_id, AuctionBids.bid_amount)
                    .where(AuctionBids.auction_id == auction_id)
                    .order_by(AuctionBids.bid_amount.desc())
                    .limit(1)
                )
                highest_bid = session.execute(highest_bid_stmt).fetchone()

                winner_id = None
                final_price = auction.starting_price
                credits_reduced = False

                if highest_bid:
                    winner_id = highest_bid[0]
                    final_price = highest_bid[1]

                    # 扣除获胜者的积分
                    stats = session.execute(
                        select(Statistics).where(Statistics.tg_id == winner_id)
                    ).scalar_one_or_none()

                    if stats and stats.credits >= final_price:
                        session.execute(
                            update(Statistics)
                            .where(Statistics.tg_id == winner_id)
                            .values(credits=Statistics.credits - final_price)
                        )
                        credits_reduced = True

                # 更新竞拍状态
                session.execute(
                    update(Auctions)
                    .where(Auctions.id == auction_id)
                    .values(is_active=0, winner_id=winner_id, current_price=final_price)
                )
                return True, {
                    "id": auction_id,
                    "title": auction.title,
                    "winner_id": winner_id,
                    "final_price": final_price,
                    "credits_reduced": credits_reduced,
                }

        except Exception as e:
            logger.error(f"Error finishing auction {auction_id}: {e}")
            logger.error(traceback.format_exc())
            return False, str(e)

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
