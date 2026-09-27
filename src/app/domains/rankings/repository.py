from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.db import get_session
from app.core.log import logger
from app.domains.badges.models import UserBadge
from app.domains.blackjack import service as blackjack_service
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.invitation.models import Invitation
from app.domains.luckywheel.models import WheelStats
from app.domains.treasure.models import TreasureIssue


class RankingsRepository:
    def get_credits_rank(self) -> list:
        """获取积分排行"""
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.credits).order_by(
                Statistics.credits.desc()
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_donation_rank(self) -> list:
        """获取捐赠排行"""
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.donation).order_by(
                Statistics.donation.desc()
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_plex_watched_time_rank(self) -> list:
        """获取 Plex 观看时长排行"""
        with get_session() as session:
            stmt = select(
                PlexUser.plex_id,
                PlexUser.tg_id,
                PlexUser.plex_username,
                PlexUser.watched_time,
                PlexUser.is_premium,
            ).order_by(PlexUser.watched_time.desc())
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def get_emby_watched_time_rank(self) -> list:
        """获取 Emby 观看时长排行"""
        with get_session() as session:
            stmt = select(
                EmbyUser.emby_id,
                EmbyUser.emby_username,
                EmbyUser.emby_watched_time,
                EmbyUser.is_premium,
                EmbyUser.tg_id,
            ).order_by(EmbyUser.emby_watched_time.desc())
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def get_invitation_rank(self) -> list:
        """获取邀请排行榜数据"""
        with get_session() as session:
            stmt = (
                select(
                    Invitation.owner,
                    func.count(func.distinct(Invitation.used_by)).label("invite_count"),
                )
                .where(Invitation.is_used == 1, Invitation.used_by.isnot(None))
                .group_by(Invitation.owner)
                .order_by(func.count(func.distinct(Invitation.used_by)).desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_wheel_credits_rank(self) -> list:
        """获取幸运大转盘积分变动排行榜（统计所有游戏结果）"""
        with get_session() as session:
            total_credits_change = func.sum(WheelStats.credits_change).label(
                "total_credits_change"
            )
            play_count = func.count(WheelStats.id).label("play_count")
            stmt = (
                select(WheelStats.tg_id, total_credits_change, play_count)
                .group_by(WheelStats.tg_id)
                .order_by(total_credits_change.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], float(r[1] or 0), int(r[2] or 0)) for r in results]

    def get_wheel_invite_code_rank(self) -> list:
        """获取幸运大转盘邀请码获得排行榜"""
        with get_session() as session:
            invite_count = func.count(WheelStats.id).label("invite_count")
            stmt = (
                select(WheelStats.tg_id, invite_count)
                .where(WheelStats.item_name == "邀请码 1 枚")
                .group_by(WheelStats.tg_id)
                .order_by(invite_count.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], int(r[1] or 0)) for r in results if int(r[1] or 0) > 0]

    def get_blackjack_skill_ranks(self, min_hands: int | None = None) -> dict:
        """Return blackjack accuracy and win-rate rankings."""
        return blackjack_service.get_blackjack_skill_ranks(min_hands)

    def get_blackjack_accuracy_rank(self, min_hands: int | None = None) -> list:
        return self.get_blackjack_skill_ranks(min_hands)["accuracy"]

    def get_blackjack_win_rate_rank(self, min_hands: int | None = None) -> list:
        return self.get_blackjack_skill_ranks(min_hands)["win_rate"]

    def get_blackjack_max_win_rank(self) -> list:
        return blackjack_service.get_blackjack_max_win_rank()

    def get_treasure_win_issue_rank(self) -> list:
        """获取夺宝奇兵中奖期数排行榜"""
        with get_session() as session:
            win_count = func.count(TreasureIssue.id).label("win_count")
            stmt = (
                select(TreasureIssue.winner_tg_id, win_count)
                .where(
                    TreasureIssue.status == 2,
                    TreasureIssue.winner_tg_id.isnot(None),
                )
                .group_by(TreasureIssue.winner_tg_id)
                .order_by(win_count.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], int(r[1] or 0)) for r in results if int(r[1] or 0) > 0]

    def get_treasure_win_credits_rank(self) -> list:
        """获取夺宝奇兵中奖积分排行榜"""
        with get_session() as session:
            win_credits = func.sum(TreasureIssue.prize_credits).label("win_credits")
            stmt = (
                select(TreasureIssue.winner_tg_id, win_credits)
                .where(
                    TreasureIssue.status == 2,
                    TreasureIssue.winner_tg_id.isnot(None),
                )
                .group_by(TreasureIssue.winner_tg_id)
                .order_by(win_credits.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], int(r[1] or 0)) for r in results if int(r[1] or 0) > 0]

    def get_badge_rank(self) -> list[dict]:
        """
        获取勋章排行榜数据（按用户拥有的勋章数量排序）

        Returns:
            用户勋章排行数据列表，包含 tg_id, badge_count, badges 信息
        """
        try:
            with get_session() as session:
                # 查询每个用户拥有的勋章数量，并获取勋章详情
                stmt = (
                    select(
                        UserBadge.tg_id,
                        func.count(UserBadge.id).label("badge_count"),
                    )
                    .where(UserBadge.is_active == 1)
                    .group_by(UserBadge.tg_id)
                    .order_by(func.count(UserBadge.id).desc())
                )
                results = session.execute(stmt).fetchall()

                rank_data = []
                for row in results:
                    tg_id = row[0]
                    badge_count = row[1]

                    # 获取该用户的所有勋章详情
                    badges_stmt = (
                        select(UserBadge)
                        .options(joinedload(UserBadge.badge))
                        .where(UserBadge.tg_id == tg_id, UserBadge.is_active == 1)
                        .order_by(UserBadge.redeemed_at.desc())
                    )
                    user_badges = session.execute(badges_stmt).scalars().unique().all()

                    rank_data.append(
                        {
                            "tg_id": tg_id,
                            "badge_count": badge_count,
                            "badges": [
                                self._user_badge_to_dict(ub) for ub in user_badges
                            ],
                        }
                    )

                return rank_data
        except Exception as e:
            logger.error(f"获取勋章排行榜失败: {e}")
            return []


rankings_repository = RankingsRepository()


def get_blackjack_skill_ranks(min_hands: int | None = None) -> dict:
    return rankings_repository.get_blackjack_skill_ranks(min_hands)


def get_blackjack_max_win_rank() -> list:
    return rankings_repository.get_blackjack_max_win_rank()
